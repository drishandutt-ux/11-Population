"""The Visual Lab, steps 2 and 3 (2026-10-26): generate, read, remake and check images.

The rule that makes this safe: **the words on an image are never drawn by an image model.** The
model writes a *layout* — headline, sub-line, claim lines, call to action, small print, palette
and a prompt for the hero visual — and this module composites the text itself with Pillow over
a hero image. The hero comes from an image provider (OpenAI or Google, by key) or, with none
configured, from a placeholder drawn in code, so the pipeline runs everywhere and the text layer
is exact everywhere. A claim that must appear word for word therefore *does* appear word for
word, and the keep-list check can prove it mechanically before any twin sees the picture.

The flow for every generated or remade image:
  brief (what the session knows + the note or the change) → layout (one structured call)
  → enforce the keep-list on the layout → hero (provider or placeholder) → composite
  → normalise → keep-list check (text: mechanical; present / absent items: one vision call)
  → stored on the row with its parent, brief, layout and check, status ready or failed.

A remake of an *uploaded* image first reads the image into a layout (one vision call), so the
remake starts from what is actually on the poster, not from nothing. A proposed remake
(step 3) reads a Visuals run on the image — what put people off, the one change each would
make, who said so — and writes the change note with the twins cited.
"""
from __future__ import annotations

import base64
import colorsys
import hashlib
import io
import math
import re
import time
import traceback
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select

from app.core import database as _db
from app.core.config import get_settings
from app.models.measurement import Probe, SessionImage
from app.services.evidence.llm import analyze, arr, b, clip, enum, obj, s
from app.services.measurement import images as images_mod

KEEP_TYPES = ("text", "present", "absent")
MAX_KEEP = 12
CANVAS = (1200, 1600)                 # a portrait poster; the provider draws the hero at 3:4
FONT_DIR = __import__("os").path.join(__import__("os").path.dirname(__file__), "..", "..", "data", "fonts")
PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

# ── the keep-list ─────────────────────────────────────────────────────────────

def normalise_keep_list(raw: Any) -> list[dict]:
    """[{type: text|present|absent, value}] from whatever the client sent; junk dropped."""
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str):
            t, v = "text", item
        elif isinstance(item, dict):
            t, v = str(item.get("type") or "text").strip().lower(), item.get("value")
        else:
            continue
        v = " ".join(str(v or "").split()).strip()
        if not v or t not in KEEP_TYPES:
            continue
        if not any(o["type"] == t and o["value"].lower() == v.lower() for o in out):
            out.append({"type": t, "value": v[:200]})
    return out[:MAX_KEEP]


def _norm_text(t: str) -> str:
    return " ".join(str(t or "").lower().replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-").split())


# ── the layout ────────────────────────────────────────────────────────────────

LAYOUT_SCHEMA = obj({
    "rationale": s("2-4 sentences: why this layout, what it leads with, what it answers in the audience's reactions, what it keeps"),
    "headline": s("The headline, 2-7 words, in the audience's own register"),
    "subline": s("One supporting line under the headline, up to 12 words; '' if none"),
    "body_lines": arr(s("One short line of body copy, up to 12 words"), "0-3 lines of body copy", max_items=3),
    "claim_lines": arr(s("A line that must read exactly as given — a claim, a price, a legal line"), "Every exact-text keep item, each as its own line, verbatim", max_items=6),
    "cta": s("The call to action, 2-6 words; '' if none"),
    "small_print": s("Small print at the foot, up to 20 words; '' if none"),
    "palette": obj({
        "bg": s("Background colour as #rrggbb"),
        "fg": s("Text colour as #rrggbb, legible on bg"),
        "accent": s("Accent colour as #rrggbb, for the call to action panel"),
    }),
    "hero_prompt": s("A 1-3 sentence description of the picture for an image model: subject, setting, mood, style. NO words, logos or text in the picture; name nothing on the must-not-show list"),
    "hero_placement": enum(["top", "left", "none"], "Where the picture sits: top (picture above the words), left (picture beside the words), none (type only)"),
    "kept": arr(s("One keep-list item this layout honours, repeated word for word"), "Every keep-list item, restated", max_items=MAX_KEEP),
})

LAYOUT_SYSTEM = (
    "You are a senior creative at a communications agency writing the layout of one poster-style piece. "
    "You are given what the session knows about the audience, a note from the analyst, and sometimes a "
    "previous version with the audience's reactions and a change to make. Write ONE layout with the tool.\n"
    "Rules:\n"
    "- Every item on the must-read-exactly list appears VERBATIM as its own claim line. Never paraphrase a claim, "
    "a price, a legal line or a call to action that is on that list. Never add claims that are not on it.\n"
    "- Items on the must-show list are in the picture (describe them in the hero prompt) or on the page.\n"
    "- Items on the must-not-show list appear nowhere: not in the words, not in the hero prompt.\n"
    "- The hero prompt describes a picture with NO words in it; the words are set separately.\n"
    "- Plain, specific language in the audience's register. Lead with what they said mattered. "
    "If a change is asked for, make that change and keep everything else that was working.\n"
    "- Colours as #rrggbb with real contrast between bg and fg."
)


def _keep_block(keep: list[dict]) -> str:
    texts = [k["value"] for k in keep if k["type"] == "text"]
    present = [k["value"] for k in keep if k["type"] == "present"]
    absent = [k["value"] for k in keep if k["type"] == "absent"]
    lines = ["THE KEEP-LIST (what every version must honour):"]
    lines.append("Must read exactly (each as its own line, word for word): " + ("; ".join(f'"{t}"' for t in texts) if texts else "nothing listed"))
    lines.append("Must show: " + ("; ".join(present) if present else "nothing listed"))
    lines.append("Must not show: " + ("; ".join(absent) if absent else "nothing listed"))
    return "\n".join(lines)


def layout_text_fields(layout: dict) -> list[str]:
    """Every string the composite will set in type, in reading order."""
    out = [str(layout.get("headline") or ""), str(layout.get("subline") or "")]
    out += [str(x) for x in (layout.get("body_lines") or [])]
    out += [str(x) for x in (layout.get("claim_lines") or [])]
    out += [str(layout.get("cta") or ""), str(layout.get("small_print") or "")]
    return [x for x in out if x.strip()]


def enforce_keep_list(layout: dict, keep: list[dict]) -> dict:
    """Make the mechanical guarantee: every exact-text item is set in type, verbatim. A text item
    the model dropped is appended as a claim line; the model's paraphrase, if any, stays beside it
    (the check will show both). Forbidden words are stripped from the hero prompt."""
    layout = dict(layout or {})
    claims = [str(x) for x in (layout.get("claim_lines") or []) if str(x).strip()]
    fields = [_norm_text(x) for x in layout_text_fields(layout)]
    for k in keep:
        if k["type"] != "text":
            continue
        want = _norm_text(k["value"])
        if not any(want in f for f in fields):
            claims.append(k["value"])
            fields.append(want)
    layout["claim_lines"] = claims[:6]
    absent = [k["value"] for k in keep if k["type"] == "absent"]
    prompt = str(layout.get("hero_prompt") or "")
    for word in absent:
        prompt = re.sub(re.escape(word), "", prompt, flags=re.I)
    layout["hero_prompt"] = " ".join(prompt.split())
    return layout


def _reactions_block(probe: Optional[Probe]) -> str:
    """What the twins said about the parent image, from a Visuals run: the headline, what put them
    off, the one change each would make, and the words of those it did not work on."""
    if not probe:
        return ""
    agg = probe.aggregates or {}
    if not agg.get("n"):
        return ""
    lines = ["WHAT THE AUDIENCE SAID ABOUT THE PREVIOUS VERSION (a Visuals run, " + str(agg.get("n")) + " twins):", str(agg.get("sentence") or "")]
    put_off = agg.get("put_off") or []
    if put_off:
        lines.append("What put them off: " + "; ".join(f"{p.get('value')} ({p.get('count')})" for p in put_off[:6]))
    noticed = agg.get("noticed") or []
    if noticed:
        lines.append("What they noticed first: " + "; ".join(f"{p.get('value')} ({p.get('count')})" for p in noticed[:5]))
    changes = agg.get("changes") or []
    if changes:
        lines.append("The one thing each would change:\n- " + "\n- ".join(f"{c.get('name')} ({c.get('verdict')}): {c.get('change_one')}" for c in changes[:10]))
    verbs = agg.get("verbatims") or {}
    for bucket in ("no", "mixed"):
        for v in (verbs.get(bucket) or [])[:3]:
            lines.append(f"- {v.get('name')} ({bucket}): \"{clip(v.get('reasoning', ''), 220)}\"" + (f" — put off by: {v.get('put_off')}" if v.get("put_off") else ""))
    return "\n".join(x for x in lines if x)


async def session_context(session_id: str) -> str:
    """What the session knows, for the brief: the question, the Lab brief when one is on file (never
    built here — that is a strong-tier call the analyst asks for), and the latest Lab sentences."""
    from app.models.session import AnalysisSession
    parts: list[str] = []
    async with _db.AsyncSessionLocal() as db:
        sess = await db.get(AnalysisSession, session_id)
        if sess:
            parts.append(f"THE QUESTION THIS SESSION IS ABOUT: {sess.query}")
        probes = (await db.execute(
            select(Probe).where(Probe.session_id == session_id, Probe.status == "complete", Probe.experiment_id.is_(None))
            .order_by(Probe.created_at.desc()).limit(6)
        )).scalars().all()
    try:
        from app.services.measurement import lab_brief
        b_ = await lab_brief.get(session_id)
        if b_ and b_.get("brief"):
            parts.append(lab_brief.brief_for_prompt(b_["brief"], 2500))
    except Exception as e:  # noqa: BLE001 — the brief is a bonus
        print(f"[visual_gen] lab brief unavailable: {type(e).__name__}: {e}")
    sentences = [f"- {p.instrument}: {clip(str((p.aggregates or {}).get('sentence') or ''), 260)}" for p in probes if (p.aggregates or {}).get("sentence")]
    if sentences:
        parts.append("WHAT THE LAB HAS ALREADY FOUND:\n" + "\n".join(sentences[:6]))
    return "\n\n".join(parts)


async def write_layout(
    *, session_id: str, note: str, keep: list[dict], model: str, context: str = "",
    parent_layout: Optional[dict] = None, change: str = "", reactions: str = "",
) -> dict:
    """One structured call → a layout, then the keep-list enforced on it mechanically."""
    blocks = []
    if context:
        blocks.append(context)
    blocks.append(_keep_block(keep))
    if parent_layout:
        prev = {k: parent_layout.get(k) for k in ("headline", "subline", "body_lines", "claim_lines", "cta", "small_print", "palette", "hero_prompt", "hero_placement") if parent_layout.get(k) not in (None, "", [])}
        blocks.append("THE PREVIOUS VERSION'S LAYOUT:\n" + "\n".join(f"{k}: {v}" for k, v in prev.items()))
    if reactions:
        blocks.append(reactions)
    if change:
        blocks.append(f"THE CHANGE TO MAKE (keep everything else that was working): {change}")
    if note:
        blocks.append(f"THE ANALYST'S NOTE: {note}")
    if not note and not change:
        blocks.append("THE ANALYST'S NOTE: none — write the piece the audience's own words call for.")
    blocks.append("Write the layout with the tool.")
    out = await analyze(LAYOUT_SCHEMA, LAYOUT_SYSTEM, "\n\n".join(blocks), session_id=session_id, label="visual:layout", model=model, max_tokens=1400)
    return enforce_keep_list(out, keep)


# ── reading an uploaded image into a layout ───────────────────────────────────

READ_SCHEMA = obj({
    "description": s("2-3 sentences: what the picture shows and how it is laid out"),
    "headline": s("The largest line of text, exactly as written; '' if none"),
    "subline": s("The line under it, exactly as written; '' if none"),
    "body_lines": arr(s("Another line of text, exactly as written"), "Other text on the image, exactly as written, in reading order", max_items=6),
    "claim_lines": arr(s("A claim, price, offer or legal line, exactly as written"), "Lines that read like claims, prices, offers or legal text", max_items=6),
    "cta": s("The call to action, exactly as written; '' if none"),
    "small_print": s("Small print, as much as is legible; '' if none"),
    "palette": obj({"bg": s("Dominant background colour as #rrggbb"), "fg": s("Main text colour as #rrggbb"), "accent": s("Accent colour as #rrggbb")}),
    "hero_prompt": s("A 1-3 sentence description of the picture part (not the words) that an image model could redraw"),
    "hero_placement": enum(["top", "left", "none"], "Where the picture sits relative to the words"),
    "visible_items": arr(s("A thing visibly present: a logo, a product, a person, a symbol"), "Notable things on the image", max_items=8),
})

READ_SYSTEM = (
    "You read a marketing image for a creative team. Transcribe its text EXACTLY as written (do not correct, "
    "paraphrase or invent; if a line is illegible write what you can and nothing more). Describe the picture "
    "part so it could be redrawn. Record the answer with the tool."
)


async def read_image(row: SessionImage, *, model: str) -> dict:
    """One vision call: the words on an uploaded image, exactly, and what the picture shows."""
    img = {"id": row.id, "label": row.label or row.filename or "image", "option": "", "media_type": row.media_type,
           "data_b64": base64.b64encode(row.data).decode("ascii"), "width": row.width, "height": row.height}
    content = images_mod.vision_content([img], "Read this image with the tool.")
    out = await analyze(READ_SCHEMA, READ_SYSTEM, "Read this image.", session_id=row.session_id, label="visual:read", model=model,
                        max_tokens=1200, messages=[{"role": "user", "content": content}])
    out["read_from_image"] = True
    return out


# ── the hero visual ───────────────────────────────────────────────────────────

def provider_name() -> str:
    st = get_settings()
    p = (st.image_provider or "auto").strip().lower()
    if p == "auto":
        if st.openai_api_key:
            return "openai"
        if st.google_api_key:
            return "google"
        return "none"
    if p == "openai" and not st.openai_api_key:
        return "none"
    if p == "google" and not st.google_api_key:
        return "none"
    return p if p in ("openai", "google", "none") else "none"


async def _openai_hero(prompt: str) -> bytes:
    import httpx
    st = get_settings()
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {st.openai_api_key}"},
            json={"model": st.image_model_openai, "prompt": prompt, "n": 1, "size": "1024x1536", "quality": "medium"},
        )
        r.raise_for_status()
        data = r.json()["data"][0]
        if data.get("b64_json"):
            return base64.b64decode(data["b64_json"])
        img = await client.get(data["url"])
        img.raise_for_status()
        return img.content


async def _google_hero(prompt: str) -> bytes:
    import httpx
    st = get_settings()
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{st.image_model_google}:predict",
            headers={"x-goog-api-key": st.google_api_key},
            json={"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1, "aspectRatio": "3:4"}},
        )
        r.raise_for_status()
        return base64.b64decode(r.json()["predictions"][0]["bytesBase64Encoded"])


def _hex(c: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(c or "").strip())
    if not m:
        return default
    h = m.group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def placeholder_hero(prompt: str, size: tuple[int, int], accent: tuple[int, int, int]) -> bytes:
    """A hero drawn in code when no provider is configured: a gradient and a few shapes seeded from
    the prompt, so the same prompt draws the same picture and the page is never blank. It is
    labelled a placeholder on the row; the brief says which key to set."""
    from PIL import Image, ImageDraw
    seed = int(hashlib.sha256(prompt.encode()).hexdigest()[:8], 16)
    rnd = __import__("random").Random(seed)
    w, h = size
    hue = (seed % 360) / 360.0
    top = tuple(int(255 * c) for c in colorsys.hls_to_rgb(hue, 0.78, 0.45))
    bottom = tuple(int(255 * c) for c in colorsys.hls_to_rgb((hue + 0.08) % 1.0, 0.55, 0.5))
    img = Image.new("RGB", size, top)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        col = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=col)
    for _ in range(rnd.randint(3, 6)):
        r = rnd.randint(w // 8, w // 3)
        x, y = rnd.randint(0, w), rnd.randint(0, h)
        a = rnd.randint(50, 140)
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        col = accent if rnd.random() < 0.5 else (255, 255, 255)
        od.ellipse([x - r, y - r, x + r, y + r], fill=col + (a,))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        d = ImageDraw.Draw(img)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


async def generate_hero(prompt: str, *, session_id: str, size: tuple[int, int], accent: tuple[int, int, int]) -> tuple[bytes, str, Optional[str]]:
    """(bytes, provider, error). Falls back to the placeholder when the provider fails, with the
    error kept on the brief so the analyst knows the picture is not the model's."""
    from app.core.monitoring import record_image_call
    name = provider_name()
    st = get_settings()
    if name == "none":
        return placeholder_hero(prompt, size, accent), "none", None
    started = time.monotonic()
    try:
        data = await (_openai_hero(prompt) if name == "openai" else _google_hero(prompt))
        record_image_call(model=st.image_model_openai if name == "openai" else st.image_model_google, session_id=session_id,
                          label="visual:hero", cost_usd=st.image_cost_openai_usd if name == "openai" else st.image_cost_google_usd,
                          elapsed_sec=time.monotonic() - started, status="success")
        return data, name, None
    except Exception as e:  # noqa: BLE001
        record_image_call(model=st.image_model_openai if name == "openai" else st.image_model_google, session_id=session_id,
                          label="visual:hero", cost_usd=0.0, elapsed_sec=time.monotonic() - started, status="error")
        err = f"{name}: {type(e).__name__}: {str(e)[:200]}"
        print(f"[visual_gen] hero failed, placeholder used — {err}")
        return placeholder_hero(prompt, size, accent), "none", err


# ── compositing the text layer ────────────────────────────────────────────────

def _font(bold: bool, size: int):
    from PIL import ImageFont
    import os
    path = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    try:
        return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001 — never fail a composite for want of a font
        return ImageFont.load_default()


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = str(text).split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit(draw, text: str, bold: bool, max_width: int, start: int, min_size: int, max_lines: int) -> tuple[Any, list[str]]:
    size = start
    while size > min_size:
        f = _font(bold, size)
        lines = _wrap(draw, text, f, max_width)
        if len(lines) <= max_lines:
            return f, lines
        size -= 6
    f = _font(bold, min_size)
    return f, _wrap(draw, text, f, max_width)[:max_lines]


def _luma(c: tuple[int, int, int]) -> float:
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def compose(layout: dict, hero: Optional[bytes], *, size: tuple[int, int] = CANVAS) -> bytes:
    """Set the layout's words over the hero with Pillow. Returns PNG bytes.

    `top`: hero in the upper 52%, words below. `left`: hero in the left 46%, words to the right.
    `none`: type only. Every text field is wrapped and shrunk to fit; claim lines are set in the
    accent colour so a claim reads as the thing it is."""
    from PIL import Image, ImageDraw
    w, h = size
    pal = layout.get("palette") or {}
    bg = _hex(pal.get("bg"), (24, 32, 48))
    fg = _hex(pal.get("fg"), (250, 250, 250))
    accent = _hex(pal.get("accent"), (240, 160, 60))
    if abs(_luma(bg) - _luma(fg)) < 90:                     # the model picked two similar colours
        fg = (250, 250, 250) if _luma(bg) < 128 else (20, 20, 20)
    placement = str(layout.get("hero_placement") or "top")
    if not hero:
        placement = "none"
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    pad = int(w * 0.06)

    hero_box = None
    if placement == "top":
        hero_box = (0, 0, w, int(h * 0.52))
    elif placement == "left":
        hero_box = (0, 0, int(w * 0.46), h)
    if hero_box:
        try:
            hi = Image.open(io.BytesIO(hero)).convert("RGB")
            bw, bh = hero_box[2] - hero_box[0], hero_box[3] - hero_box[1]
            scale = max(bw / hi.width, bh / hi.height)
            hi = hi.resize((max(1, int(hi.width * scale)), max(1, int(hi.height * scale))), Image.LANCZOS)
            left, top = (hi.width - bw) // 2, (hi.height - bh) // 2
            img.paste(hi.crop((left, top, left + bw, top + bh)), (hero_box[0], hero_box[1]))
        except Exception as e:  # noqa: BLE001
            print(f"[visual_gen] hero could not be placed: {type(e).__name__}: {e}")
            hero_box = None

    # The text column.
    if placement == "left" and hero_box:
        x0, y, x1 = hero_box[2] + pad, pad, w - pad
    elif placement == "top" and hero_box:
        x0, y, x1 = pad, hero_box[3] + pad, w - pad
    else:
        x0, y, x1 = pad, pad, w - pad
    col_w = x1 - x0
    y_max = h - pad

    def put(text: str, *, bold: bool, start: int, min_size: int, max_lines: int, colour=fg, gap: int = 10) -> None:
        nonlocal y
        if not str(text).strip() or y >= y_max:
            return
        f, lines = _fit(d, text, bold, col_w, start, min_size, max_lines)
        for ln in lines:
            if y >= y_max:
                return
            d.text((x0, y), ln, font=f, fill=colour)
            y += int(f.size * 1.18)
        y += gap

    put(layout.get("headline", ""), bold=True, start=int(w * 0.09), min_size=44, max_lines=3, gap=14)
    put(layout.get("subline", ""), bold=False, start=int(w * 0.045), min_size=28, max_lines=2, gap=18)
    for line in (layout.get("body_lines") or [])[:3]:
        put(line, bold=False, start=int(w * 0.036), min_size=24, max_lines=2, gap=6)
    claims = [c for c in (layout.get("claim_lines") or []) if str(c).strip()][:6]
    if claims:
        y += 10
        for c in claims:
            put(c, bold=True, start=int(w * 0.04), min_size=26, max_lines=2, colour=accent, gap=6)
    cta = str(layout.get("cta") or "").strip()
    small = str(layout.get("small_print") or "").strip()
    # The call to action is a panel pinned above the small print at the foot of the column.
    if small:
        f_small = _font(False, max(18, int(w * 0.018)))
        small_lines = _wrap(d, small, f_small, col_w)[:3]
        sy = y_max - len(small_lines) * int(f_small.size * 1.25)
        for ln in small_lines:
            d.text((x0, sy), ln, font=f_small, fill=tuple(int(fg[i] * 0.75 + bg[i] * 0.25) for i in range(3)))
            sy += int(f_small.size * 1.25)
        y_max = sy - len(small_lines) * int(f_small.size * 1.25) - 16
    if cta:
        f_cta, cta_lines = _fit(d, cta, True, col_w - 2 * 28, int(w * 0.04), 24, 2)
        panel_h = len(cta_lines) * int(f_cta.size * 1.2) + 2 * 22
        py1 = y_max - 8
        py0 = max(y + 8, py1 - panel_h)
        if py0 < py1:
            d.rounded_rectangle([x0, py0, x1, py1], radius=18, fill=accent)
            cta_fg = (255, 255, 255) if _luma(accent) < 150 else (20, 20, 20)
            ty = py0 + 22
            for ln in cta_lines:
                d.text((x0 + 28, ty), ln, font=f_cta, fill=cta_fg)
                ty += int(f_cta.size * 1.2)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


# ── the keep-list check ───────────────────────────────────────────────────────

CHECK_SCHEMA = obj({
    "items": arr(obj({
        "index": s("The item's number, as given"),
        "ok": b("true if the item is honoured: a must-show item is visibly there, a must-not-show item is absent, an exact-text item is legible word for word"),
        "note": s("A few words of evidence: what you saw, or what is missing / present instead"),
    }), "One entry per numbered item"),
})

CHECK_SYSTEM = (
    "You check a finished marketing image against a list of requirements. Look carefully; answer each item "
    "from what is actually visible. Do not assume. Record the answer with the tool."
)


def mechanical_check(layout: Optional[dict], keep: list[dict]) -> dict[int, dict]:
    """Exact-text items against the layout the text layer was set from: a mechanical pass, not a read."""
    out: dict[int, dict] = {}
    if not layout:
        return out
    fields = [_norm_text(x) for x in layout_text_fields(layout)]
    for k, item in enumerate(keep):
        if item["type"] != "text":
            continue
        want = _norm_text(item["value"])
        hit = any(want in f for f in fields)
        out[k] = {"ok": hit, "how": "text", "note": "set in type, word for word" if hit else "not set in type"}
    return out


async def check_image(*, session_id: str, data: bytes, media_type: str, width: int, height: int,
                      layout: Optional[dict], keep: list[dict], model: str, label: str = "image") -> dict:
    """The keep-list check: text items mechanically (when the words were authored by us), everything
    else — and text items on an uploaded image — by one vision call."""
    results = mechanical_check(layout if (layout and not layout.get("read_from_image")) else None, keep)
    pending = [(k, item) for k, item in enumerate(keep) if k not in results]
    if pending:
        # Numbered 1..n over the items that go to vision, and mapped back by that number.
        listing = "\n".join(
            f"{n}. {'Must read exactly' if it['type'] == 'text' else 'Must show' if it['type'] == 'present' else 'Must NOT show'}: \"{it['value']}\""
            for n, (k, it) in enumerate(pending, 1)
        )
        img = {"id": "check", "label": label, "option": "", "media_type": media_type, "data_b64": base64.b64encode(data).decode("ascii"), "width": width, "height": height}
        content = images_mod.vision_content([img], f"REQUIREMENTS:\n{listing}\n\nCheck each one against the image with the tool.")
        try:
            out = await analyze(CHECK_SCHEMA, CHECK_SYSTEM, "Check the image.", session_id=session_id, label="visual:check", model=model,
                                max_tokens=900, messages=[{"role": "user", "content": content}])
            by_index = {}
            for it in out.get("items") or []:
                try:
                    by_index[int(str(it.get("index")).strip().rstrip(".")) - 1] = it
                except (TypeError, ValueError):
                    continue
            for n, (k, item) in enumerate(pending):
                got = by_index.get(n)
                results[k] = {"ok": bool(got.get("ok")) if got else False, "how": "vision",
                              "note": str((got or {}).get("note") or "the check did not answer this item")[:200]}
        except Exception as e:  # noqa: BLE001
            print(f"[visual_gen] vision check failed: {type(e).__name__}: {e}")
            for k, item in pending:
                results[k] = {"ok": False, "how": "vision", "note": f"check failed: {type(e).__name__}"}
    items = [{"type": keep[k]["type"], "value": keep[k]["value"], **results.get(k, {"ok": False, "how": "none", "note": "not checked"})} for k in range(len(keep))]
    return {"passed": all(i["ok"] for i in items), "items": items, "checked_at": datetime.utcnow().isoformat(), "model": model}


# ── proposing a change from a Visuals run (step 3) ────────────────────────────

PROPOSE_SCHEMA = obj({
    "change": s("The one change to make, in one or two sentences a designer could act on"),
    "keep": arr(s("Something that is working and must stay"), "What to keep, from what the audience responded to", max_items=5),
    "why": s("2-4 sentences: which reactions drove this, in plain words"),
    "cites": arr(s("A twin's name whose reaction this rests on"), "The twins whose words drove the change", max_items=6),
    "expected": s("What should move if the change works, in one sentence — the audience it is aimed at and what it gives up elsewhere, if anything"),
})

PROPOSE_SYSTEM = (
    "You are a planner reading an audience's reactions to one image and proposing the single most useful change. "
    "Read what put people off, what they noticed first, the one thing each would change and the words of those it did "
    "not work on. Propose ONE change that answers the most common or most damaging reaction, name what to keep, and say "
    "plainly who said what. Never propose removing anything on the keep-list. Record the answer with the tool."
)


async def propose_change(*, row: SessionImage, probe: Probe, model: str) -> dict:
    reactions = _reactions_block(probe)
    if not reactions:
        raise ValueError("That run has no answers to read.")
    keep = normalise_keep_list(row.keep_list)
    layout = row.layout or {}
    blocks = [reactions]
    if layout:
        blocks.append("THE IMAGE'S LAYOUT:\n" + "\n".join(f"{k}: {layout.get(k)}" for k in ("headline", "subline", "body_lines", "claim_lines", "cta") if layout.get(k)))
    blocks.append(_keep_block(keep))
    blocks.append("Propose the one change with the tool.")
    out = await analyze(PROPOSE_SCHEMA, PROPOSE_SYSTEM, "\n\n".join(blocks), session_id=row.session_id, label="visual:propose", model=model, max_tokens=900)
    out["probe_id"] = probe.id
    return out


async def latest_visual_probe(session_id: str, image_id: str) -> Optional[Probe]:
    """The newest complete Visuals run that showed this image on its own."""
    async with _db.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Probe).where(Probe.session_id == session_id, Probe.instrument == "visual", Probe.status == "complete")
            .order_by(Probe.created_at.desc())
        )).scalars().all()
    for p in rows:
        refs = images_mod.refs_in(p.spec or {})
        if len(refs) == 1 and refs[0]["id"] == image_id and (p.aggregates or {}).get("n"):
            return p
    return None


# ── the jobs ──────────────────────────────────────────────────────────────────

async def _set(image_id: str, **fields) -> None:
    async with _db.AsyncSessionLocal() as db:
        row = await db.get(SessionImage, image_id)
        if not row:
            return
        for k, v in fields.items():
            setattr(row, k, v)
        await db.commit()


async def start_generate(session_id: str, *, note: str, keep_list: Any, mode: str) -> SessionImage:
    """Create the row (status generating) so the page shows it forming; `run_generate` fills it."""
    keep = normalise_keep_list(keep_list)
    model = get_settings().agent_model(mode)
    row = SessionImage(
        session_id=session_id, label=(note or "Generated").strip()[:60] or "Generated", filename="", media_type="image/png",
        width=1, height=1, size_bytes=len(PLACEHOLDER_PNG), sha256="", source="generated", status="generating",
        keep_list=keep, brief={"note": note or "", "mode": mode, "model": model}, data=PLACEHOLDER_PNG,
    )
    async with _db.AsyncSessionLocal() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def start_remake(session_id: str, parent: SessionImage, *, change: str, keep_list: Any, probe_id: Optional[str], proposal: Optional[dict], mode: str) -> SessionImage:
    keep = normalise_keep_list(keep_list if keep_list is not None else parent.keep_list)
    model = get_settings().agent_model(mode)
    row = SessionImage(
        session_id=session_id, label=f"{parent.label or 'image'} · remake"[:200], filename="", media_type="image/png",
        width=1, height=1, size_bytes=len(PLACEHOLDER_PNG), sha256="", source="remake", status="generating", parent_id=parent.id,
        change_note=(change or "").strip(), keep_list=keep,
        brief={"change": (change or "").strip(), "probe_id": probe_id, "proposal": proposal, "mode": mode, "model": model}, data=PLACEHOLDER_PNG,
    )
    async with _db.AsyncSessionLocal() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def _finish(row_id: str, *, layout: dict, hero_provider: str, hero_error: Optional[str], rationale_extra: dict, model: str) -> None:
    async with _db.AsyncSessionLocal() as db:
        row = await db.get(SessionImage, row_id)
        if not row:
            return
        session_id, keep, brief = row.session_id, normalise_keep_list(row.keep_list), dict(row.brief or {})
    pal = layout.get("palette") or {}
    accent = _hex(pal.get("accent"), (240, 160, 60))
    hero_bytes, provider, err = await generate_hero(str(layout.get("hero_prompt") or ""), session_id=session_id, size=(1024, 1366), accent=accent) \
        if str(layout.get("hero_placement") or "top") != "none" else (None, "none", None)
    png = compose(layout, hero_bytes)
    norm = images_mod.normalise(png, "generated.png")
    check = await check_image(session_id=session_id, data=norm["data"], media_type=norm["media_type"], width=norm["width"], height=norm["height"],
                              layout=layout, keep=keep, model=model, label=str(layout.get("headline") or "image"))
    brief.update({**rationale_extra, "rationale": layout.get("rationale", ""), "hero_prompt": layout.get("hero_prompt", ""),
                  "hero_provider": provider, "hero_error": err, "kept": layout.get("kept") or []})
    await _set(row_id, data=norm["data"], media_type=norm["media_type"], width=norm["width"], height=norm["height"], size_bytes=len(norm["data"]),
               sha256=norm["sha256"], layout=layout, brief=brief, check_result=check, status="ready", error=None,
               label=(str(layout.get("headline") or "").strip()[:80] or None) or "Generated")


async def run_generate(image_id: str) -> None:
    """Background: brief → layout → hero → composite → check."""
    try:
        async with _db.AsyncSessionLocal() as db:
            row = await db.get(SessionImage, image_id)
            if not row:
                return
            session_id, note, keep, brief = row.session_id, str((row.brief or {}).get("note") or ""), normalise_keep_list(row.keep_list), dict(row.brief or {})
            model = str(brief.get("model") or get_settings().agent_model("fast"))
        context = await session_context(session_id)
        layout = await write_layout(session_id=session_id, note=note, keep=keep, model=model, context=context)
        await _finish(image_id, layout=layout, hero_provider="", hero_error=None, rationale_extra={"from": "session", "context_chars": len(context)}, model=model)
        print(f"[visual_gen] generated {image_id}: {str(layout.get('headline'))[:60]}")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        await _set(image_id, status="failed", error=f"{type(e).__name__}: {str(e)[:300]}")


async def run_remake(image_id: str) -> None:
    """Background: the parent's layout (read from the image if it was uploaded) + the change + the
    audience's reactions → a new layout → hero → composite → check."""
    try:
        async with _db.AsyncSessionLocal() as db:
            row = await db.get(SessionImage, image_id)
            if not row or not row.parent_id:
                return
            parent = await db.get(SessionImage, row.parent_id)
            if not parent:
                raise ValueError("the parent image is gone")
            session_id, change, keep, brief = row.session_id, row.change_note, normalise_keep_list(row.keep_list), dict(row.brief or {})
            model = str(brief.get("model") or get_settings().agent_model("fast"))
            probe = await db.get(Probe, brief["probe_id"]) if brief.get("probe_id") else None
            parent_layout = parent.layout
            parent_id = parent.id
        if not parent_layout:
            async with _db.AsyncSessionLocal() as db:
                parent = await db.get(SessionImage, parent_id)
            parent_layout = await read_image(parent, model=model)
            await _set(parent_id, layout=parent_layout)
        if probe is None:
            probe = await latest_visual_probe(session_id, parent_id)
        context = await session_context(session_id)
        layout = await write_layout(session_id=session_id, note="", keep=keep, model=model, context=context,
                                    parent_layout=parent_layout, change=change, reactions=_reactions_block(probe))
        await _finish(image_id, layout=layout, hero_provider="", hero_error=None,
                      rationale_extra={"from": "remake", "parent_id": parent_id, "reactions_probe_id": probe.id if probe else None}, model=model)
        print(f"[visual_gen] remade {image_id} from {parent_id}: {str(layout.get('headline'))[:60]}")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        await _set(image_id, status="failed", error=f"{type(e).__name__}: {str(e)[:300]}")


async def recheck(row: SessionImage, *, model: str) -> dict:
    keep = normalise_keep_list(row.keep_list)
    return await check_image(session_id=row.session_id, data=row.data, media_type=row.media_type, width=row.width, height=row.height,
                             layout=row.layout, keep=keep, model=model, label=row.label or "image")
