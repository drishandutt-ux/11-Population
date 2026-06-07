"""
Comprehensive YouTube extractor — captures everything a human sees:
  • Full metadata (title, channel, views, likes, tags, categories, duration)
  • Hook / intro (first 90s highlighted separately)
  • Full timestamped transcript (YouTube captions preferred; Whisper fallback)
  • Chapters
  • Thumbnail — downloaded and described by Claude Vision
  • Key visual frames — extracted from video and described by Claude Vision
  • Top viewer comments (by likes)
  • Full video description
"""

import asyncio
import base64
import os
import re
import subprocess
import tempfile
from typing import Any, Optional


# YouTube's default web/ios player clients stopped exposing captions and many
# formats to yt-dlp (they now require a PO token), which silently breaks
# transcript extraction. The `android` client still serves captions/formats,
# so we force it on every yt-dlp call. `web` is kept as a fallback.
_YT_PLAYER_CLIENTS = ["android", "web"]


def _with_client(opts: dict) -> dict:
    """Inject the working YouTube player client(s) into a yt-dlp options dict,
    merging with any existing extractor_args.youtube settings."""
    opts = dict(opts)
    extractor_args = dict(opts.get("extractor_args") or {})
    youtube_args = dict(extractor_args.get("youtube") or {})
    youtube_args.setdefault("player_client", _YT_PLAYER_CLIENTS)
    extractor_args["youtube"] = youtube_args
    opts["extractor_args"] = extractor_args
    return opts


async def extract_youtube(url: str) -> str:
    return await asyncio.to_thread(_extract_sync, url)


# ─────────────────────────────────────────────────────────────────────────────
# Main sync entry point
# ─────────────────────────────────────────────────────────────────────────────

def _extract_sync(url: str) -> str:
    import yt_dlp
    import anthropic as anthropic_lib
    from app.core.config import get_settings

    settings = get_settings()
    claude = anthropic_lib.Anthropic(api_key=settings.anthropic_api_key)
    vision_model = getattr(settings, "model_orchestration", "claude-3-5-sonnet-20241022")

    with tempfile.TemporaryDirectory() as tmpdir:

        # 1. Metadata (no video download)
        print("[yt] Fetching metadata…")
        meta = _get_metadata(url)

        # 2. Transcript — captions first, Whisper fallback
        print("[yt] Getting transcript…")
        transcript = _get_transcript(url, tmpdir, meta)

        # 3. Thumbnail → Claude Vision
        print("[yt] Analysing thumbnail…")
        thumbnail_desc = _analyse_thumbnail(meta.get("thumbnail_url", ""), claude, vision_model)

        # 4. Key frames from video → Claude Vision
        print("[yt] Extracting key frames…")
        frame_descs = _analyse_key_frames(url, tmpdir, meta.get("duration", 300), claude, vision_model)

        # 5. Top comments
        print("[yt] Fetching comments…")
        comments = _get_comments(url)

        # 6. Assemble
        return _build_document(meta, transcript, thumbnail_desc, frame_descs, comments)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Metadata
# ─────────────────────────────────────────────────────────────────────────────

def _get_metadata(url: str) -> dict[str, Any]:
    import yt_dlp

    ydl_opts = {"quiet": True, "skip_download": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(_with_client(ydl_opts)) as ydl:
        info = ydl.extract_info(url, download=False)

    duration = info.get("duration") or 0
    h, rem = divmod(int(duration), 3600)
    m, s = divmod(rem, 60)
    duration_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def fmt_count(n):
        if not n:
            return "unknown"
        n = int(n)
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.1f}K"
        return str(n)

    # Chapters
    chapters = []
    for ch in info.get("chapters") or []:
        st = int(ch.get("start_time", 0))
        ch_m, ch_s = divmod(st, 60)
        ch_h, ch_m = divmod(ch_m, 60)
        ts = f"{ch_h}:{ch_m:02d}:{ch_s:02d}" if ch_h else f"{ch_m}:{ch_s:02d}"
        chapters.append(f"{ts} — {ch.get('title', '')}")

    # Best thumbnail URL
    thumbnail_url = info.get("thumbnail", "")
    for t in sorted(info.get("thumbnails") or [], key=lambda x: x.get("preference") or 0, reverse=True):
        if t.get("url"):
            thumbnail_url = t["url"]
            break

    raw_date = info.get("upload_date", "")
    upload_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}" if len(raw_date) == 8 else raw_date

    return {
        "title": info.get("title", "Unknown"),
        "channel": info.get("uploader") or info.get("channel", "Unknown"),
        "upload_date": upload_date,
        "duration": duration,
        "duration_str": duration_str,
        "views": fmt_count(info.get("view_count")),
        "likes": fmt_count(info.get("like_count")),
        "description": (info.get("description") or "").strip(),
        "tags": (info.get("tags") or [])[:20],
        "categories": (info.get("categories") or [])[:5],
        "thumbnail_url": thumbnail_url,
        "chapters": chapters,
        # Pass through for subtitle download
        "_subtitles": info.get("subtitles") or {},
        "_auto_captions": info.get("automatic_captions") or {},
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Transcript
# ─────────────────────────────────────────────────────────────────────────────

def _get_transcript(url: str, tmpdir: str, meta: dict) -> dict:
    """Returns {'full', 'hook', 'timestamped': [(ts_str, text), ...]}"""
    import yt_dlp

    subs = meta.get("_subtitles", {})
    auto = meta.get("_auto_captions", {})

    cap_lang = next(
        (l for l in ["en", "en-US", "en-GB", "en-AU"] if l in subs or l in auto),
        None,
    )

    if cap_lang:
        try:
            sub_out = os.path.join(tmpdir, "subs")
            ydl_opts = {
                "quiet": True,
                "skip_download": True,
                "writesubtitles": cap_lang in subs,
                "writeautomaticsub": cap_lang in auto,
                "subtitleslangs": [cap_lang],
                "subtitlesformat": "vtt",
                "outtmpl": sub_out + ".%(ext)s",
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(_with_client(ydl_opts)) as ydl:
                ydl.download([url])

            vtt_files = [f for f in os.listdir(tmpdir) if f.endswith(".vtt")]
            if vtt_files:
                vtt_path = os.path.join(tmpdir, vtt_files[0])
                with open(vtt_path, encoding="utf-8") as f:
                    return _parse_vtt(f.read(), meta.get("duration", 0))
        except Exception as e:
            print(f"[yt] Caption download failed: {e} — falling back to Whisper")

    # Fallback: download audio + Whisper
    try:
        import faster_whisper

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmpdir, "audio.%(ext)s"),
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav", "preferredquality": "0"}],
            "quiet": True,
        }
        with yt_dlp.YoutubeDL(_with_client(ydl_opts)) as ydl:
            ydl.download([url])

        wav_files = [f for f in os.listdir(tmpdir) if f.endswith(".wav")]
        if not wav_files:
            return _empty_transcript()

        model = faster_whisper.WhisperModel("base", device="cpu", compute_type="int8")
        segs, _ = model.transcribe(os.path.join(tmpdir, wav_files[0]), beam_size=5)

        timestamped = []
        for seg in segs:
            m, s = divmod(int(seg.start), 60)
            timestamped.append((f"{m}:{s:02d}", seg.text.strip()))

        full = " ".join(t for _, t in timestamped)
        hook = " ".join(t for ts, t in timestamped if _ts_secs(ts) <= 90)
        return {"full": full, "hook": hook, "timestamped": timestamped}

    except Exception as e:
        print(f"[yt] Whisper failed: {e}")
        return _empty_transcript()


def _parse_vtt(content: str, duration: int) -> dict:
    timestamped: list[tuple[str, str]] = []
    seen: set[str] = set()
    current_ts: Optional[str] = None
    current_lines: list[str] = []

    for raw in content.splitlines():
        line = raw.strip()
        ts_m = re.match(r"(\d+:\d+:\d+\.\d+|\d+:\d+\.\d+)\s*-->", line)
        if ts_m:
            if current_lines and current_ts is not None:
                text = re.sub(r"<[^>]+>", "", " ".join(current_lines)).strip()
                if text and text not in seen:
                    seen.add(text)
                    timestamped.append((current_ts, text))
            current_ts = _vtt_ts_to_simple(ts_m.group(1))
            current_lines = []
        elif line and not line.startswith("WEBVTT") and not re.match(r"^\d+$", line) and "-->" not in line:
            current_lines.append(line)

    if current_lines and current_ts is not None:
        text = re.sub(r"<[^>]+>", "", " ".join(current_lines)).strip()
        if text and text not in seen:
            timestamped.append((current_ts, text))

    full = " ".join(t for _, t in timestamped)
    hook = " ".join(t for ts, t in timestamped if _ts_secs(ts) <= 90)
    return {"full": full, "hook": hook, "timestamped": timestamped}


def _vtt_ts_to_simple(ts: str) -> str:
    parts = ts.replace(",", ".").split(":")
    if len(parts) == 3:
        total = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
    else:
        total = int(parts[0]) * 60 + int(float(parts[1]))
    m, s = divmod(total, 60)
    return f"{m}:{s:02d}"


def _ts_secs(ts: str) -> int:
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return int(parts[0]) * 60 + int(parts[1])


def _empty_transcript() -> dict:
    return {"full": "", "hook": "", "timestamped": []}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Thumbnail → Claude Vision
# ─────────────────────────────────────────────────────────────────────────────

def _analyse_thumbnail(url: str, claude, model: str) -> str:
    if not url:
        return ""
    try:
        import requests
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return ""

        img_b64 = base64.standard_b64encode(resp.content).decode()
        ext = url.lower().split("?")[0].rsplit(".", 1)[-1]
        media_type = {"png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")

        response = claude.messages.create(
            model=model,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_b64}},
                    {"type": "text", "text": (
                        "Analyse this YouTube thumbnail as a media strategist would. Describe: "
                        "(1) visual composition and main subject, (2) any text overlays or titles, "
                        "(3) emotional tone and colour palette, (4) who/what is shown, "
                        "(5) what the thumbnail promises or implies about the video content. "
                        "Be concise but thorough — 4-5 sentences."
                    )},
                ],
            }],
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[yt] Thumbnail Vision failed: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# 4. Key frames → Claude Vision
# ─────────────────────────────────────────────────────────────────────────────

def _analyse_key_frames(url: str, tmpdir: str, duration: int, claude, model: str) -> list[tuple[str, str]]:
    """Download video in lowest quality, extract 5 frames, describe each."""
    import yt_dlp

    frames_dir = os.path.join(tmpdir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    # Download worst quality video (typically 144p–240p, 5–30 MB)
    video_out = os.path.join(tmpdir, "kf.%(ext)s")
    ydl_opts = {
        "format": "worstvideo[ext=mp4]/worstvideo/worst[ext=mp4]/worst",
        "outtmpl": video_out,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": 80_000_000,   # 80 MB hard cap
        "socket_timeout": 30,
    }
    try:
        with yt_dlp.YoutubeDL(_with_client(ydl_opts)) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"[yt] Video download for frames failed: {e}")
        return []

    video_files = [
        f for f in os.listdir(tmpdir)
        if any(f.endswith(ext) for ext in (".mp4", ".webm", ".mkv", ".mov"))
    ]
    if not video_files:
        return []

    video_path = os.path.join(tmpdir, video_files[0])
    results: list[tuple[str, str]] = []
    num_frames = 5

    # Spread evenly; skip the first 5s (often cold open/card) and last 10s (outro)
    effective = max(30, duration - 10)
    interval = effective / (num_frames + 1)

    for i in range(1, num_frames + 1):
        seek = min(5 + int(interval * i), effective)
        frame_path = os.path.join(frames_dir, f"frame_{i:02d}.jpg")
        try:
            proc = subprocess.run(
                ["ffmpeg", "-ss", str(seek), "-i", video_path,
                 "-frames:v", "1", "-q:v", "3", "-y", frame_path],
                capture_output=True, timeout=30,
            )
            if proc.returncode != 0 or not os.path.exists(frame_path):
                continue
        except Exception as e:
            print(f"[yt] ffmpeg frame {i} failed: {e}")
            continue

        with open(frame_path, "rb") as f:
            frame_b64 = base64.standard_b64encode(f.read()).decode()

        m, s = divmod(seek, 60)
        ts = f"{m}:{s:02d}"

        try:
            response = claude.messages.create(
                model=model,
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": frame_b64}},
                        {"type": "text", "text": (
                            "Describe what's shown in this video frame in 2 sentences. Include: "
                            "what is visually on screen (people, setting, graphics, text overlays), "
                            "the activity or topic being shown, and any notable visual elements."
                        )},
                    ],
                }],
            )
            results.append((ts, response.content[0].text.strip()))
        except Exception as e:
            print(f"[yt] Frame Vision {i} failed: {e}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 5. Comments
# ─────────────────────────────────────────────────────────────────────────────

def _get_comments(url: str) -> list[dict]:
    import yt_dlp

    try:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "getcomments": True,
            "extractor_args": {"youtube": {"comment_sort": ["top"], "max_comments": ["40,20"]}},
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(_with_client(ydl_opts)) as ydl:
            info = ydl.extract_info(url, download=False)

        raw = sorted(
            info.get("comments") or [],
            key=lambda c: c.get("like_count") or 0,
            reverse=True,
        )[:20]

        return [
            {
                "text": (c.get("text") or "").strip(),
                "likes": c.get("like_count") or 0,
                "author": c.get("author", "Anonymous"),
            }
            for c in raw
            if (c.get("text") or "").strip()
        ]
    except Exception as e:
        print(f"[yt] Comments failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 6. Assemble document
# ─────────────────────────────────────────────────────────────────────────────

def _build_document(
    meta: dict,
    transcript: dict,
    thumbnail_desc: str,
    frame_descs: list[tuple[str, str]],
    comments: list[dict],
) -> str:
    sections: list[str] = []

    # Metadata
    md_lines = [
        "=== VIDEO METADATA ===",
        f"Title:     {meta['title']}",
        f"Channel:   {meta['channel']}",
        f"Published: {meta['upload_date']}",
        f"Duration:  {meta['duration_str']}",
        f"Views:     {meta['views']}",
        f"Likes:     {meta['likes']}",
    ]
    if meta.get("categories"):
        md_lines.append(f"Category:  {', '.join(meta['categories'])}")
    if meta.get("tags"):
        md_lines.append(f"Tags:      {', '.join(meta['tags'][:15])}")
    sections.append("\n".join(md_lines))

    # Thumbnail analysis
    if thumbnail_desc:
        sections.append(f"=== THUMBNAIL VISUAL ANALYSIS ===\n{thumbnail_desc}")

    # Description
    desc = meta.get("description", "").strip()
    if desc:
        sections.append(f"=== VIDEO DESCRIPTION ===\n{desc[:3000]}{'…' if len(desc) > 3000 else ''}")

    # Chapters
    if meta.get("chapters"):
        sections.append("=== CHAPTERS ===\n" + "\n".join(meta["chapters"]))

    # Hook / opening
    hook = transcript.get("hook", "").strip()
    if hook:
        sections.append(f"=== HOOK / OPENING (first 90 seconds) ===\n{hook}")

    # Key visual frames
    if frame_descs:
        fl = ["=== KEY VISUAL MOMENTS ==="]
        for ts, desc in frame_descs:
            fl.append(f"[{ts}]  {desc}")
        sections.append("\n".join(fl))

    # Full timestamped transcript
    ts_segs = transcript.get("timestamped") or []
    if ts_segs:
        tl = ["=== FULL TRANSCRIPT (with timestamps) ==="]
        for ts, text in ts_segs:
            tl.append(f"[{ts}]  {text}")
        sections.append("\n".join(tl))
    elif transcript.get("full"):
        sections.append(f"=== FULL TRANSCRIPT ===\n{transcript['full']}")

    # Comments
    if comments:
        cl = ["=== TOP VIEWER COMMENTS ==="]
        for c in comments:
            likes = f"  ({c['likes']:,} likes)" if c["likes"] else ""
            cl.append(f"• {c['text']}{likes}")
        sections.append("\n".join(cl))

    return "\n\n".join(sections)
