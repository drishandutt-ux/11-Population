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


def _reactions_block(probe: Optional[Probe], *, full: bool = False) -> str:
    """What the twins said about the parent image, from a Visuals run: the headline, what put them
    off, the one change each would make, and the words of those it did not work on."""
    if not probe:
        return ""
    agg = probe.aggregates or {}
    if not agg.get("n"):
        return ""
    lines = ["WHAT THE AUDIENCE SAID ABOUT THE PREVIOUS VERSION (a Visuals run, " + str(agg.get("n")) + " twins):", str(agg.get("sentence") or "")]
    if full and agg.get("verdict"):
        lines.append("Verdict split: " + "; ".join(f"{v.get('value')} {v.get('count')}" for v in agg.get("verdict") or []))
    put_off = agg.get("put_off") or []
    if put_off:
        lines.append("What put them off: " + "; ".join(f"{p.get('value')} ({p.get('count')})" for p in put_off[:6]))
    noticed = agg.get("noticed") or []
    if noticed:
        lines.append("What they noticed first: " + "; ".join(f"{p.get('value')} ({p.get('count')})" for p in noticed[:5]))
    changes = agg.get("changes") or []
    if changes:
        lines.append("The one thing each would change:\n- " + "\n- ".join(f"{c.get('name')} ({c.get('verdict')}): {c.get('change_one')}" for c in changes[:(24 if full else 10)]))
    verbs = agg.get("verbatims") or {}
    for bucket in (("no", "mixed", "yes") if full else ("no", "mixed")):
        for v in (verbs.get(bucket) or [])[:(4 if full else 3)]:
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
    parent_layout: Optional[dict] = None, change: str = "", reactions: str = "", facts: Optional[list[str]] = None,
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
    if facts:
        blocks.append("FACTS THAT MUST NOT CHANGE — copy each word for word into the new layout; the change does not touch them:\n- " + "\n- ".join(facts))
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


def _ext(data: bytes) -> str:
    """The real format of stored bytes (uploads are normalised to JPEG unless they had transparency)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "jpg"


_WORKING_MODEL: Optional[str] = None          # the first OpenAI image model that answered, kept for the process
_LAST: dict = {}                               # {"model", "edit"} of the last successful call, for the brief and the ledger


def _model_candidates() -> list[str]:
    st = get_settings()
    out: list[str] = []
    for m in ([_WORKING_MODEL] if _WORKING_MODEL else []) + [st.image_model_openai] + [x.strip() for x in (st.image_model_openai_fallbacks or "").split(",")]:
        if m and m not in out:
            out.append(m)
    return out


def _is_missing_model(err: str) -> bool:
    """Errors that mean *try the next model*: the model is missing, retired or restricted for this
    key, or it rejects a parameter the chain's known-good set sends (size, quality, edits)."""
    return bool(re.search(r"does not exist|model_not_found|do(?:es)? not have access|unknown model|invalid model|not found|deprecated|retired|"
                          r"unsupported model|not supported|unsupported parameter|unknown parameter|unsupported value|invalid value|"
                          r"invalid size|invalid quality|is not a valid", err, re.I))


async def openai_image_models() -> list[str]:
    """The image-capable models the configured key can see (GET /v1/models) — the diagnosis when a
    model 'does not exist': an unverified organisation or a project that restricts models."""
    import httpx
    st = get_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {st.openai_api_key}"})
        r.raise_for_status()
        ids = [str(m.get("id")) for m in (r.json().get("data") or [])]
    return sorted(i for i in ids if re.search(r"image|dall-e", i, re.I))


async def log_visible_image_models(reason: str = "") -> None:
    if provider_name() != "openai":
        return
    try:
        models = await openai_image_models()
        print(f"[visual_gen] image models visible to the OpenAI key{reason}: {', '.join(models) or 'none — verify the organisation at platform.openai.com/settings/organization/general, or lift the project model restriction'}")
    except Exception as e:  # noqa: BLE001
        print(f"[visual_gen] could not list the OpenAI models{reason}: {type(e).__name__}: {str(e)[:200]}")


async def _openai_call(model: str, prompt: str, *, quality: str, references: Optional[list[bytes]]) -> bytes:
    """One call to one model. gpt-image-* models edit from references and take low/medium/high;
    DALL·E 3 only generates (the reference is dropped) at 1024x1792, standard/hd."""
    import httpx
    st = get_settings()
    headers = {"Authorization": f"Bearer {st.openai_api_key}"}
    dalle = model.lower().startswith("dall-e")
    if dalle:
        references = None
    size = "1024x1792" if dalle else "1024x1536"
    q = ("hd" if quality == "high" else "standard") if dalle else quality
    async with httpx.AsyncClient(timeout=180) as client:
        if references:
            field = "image[]" if len(references) > 1 else "image"
            r = await client.post(
                "https://api.openai.com/v1/images/edits", headers=headers,
                data={"model": model, "prompt": prompt, "n": "1", "size": size, "quality": q},
                files=[(field, (f"reference{k + 1}.{_ext(b)}", b, f"image/{_ext(b).replace('jpg', 'jpeg')}")) for k, b in enumerate(references[:16])],
            )
        else:
            r = await client.post(
                "https://api.openai.com/v1/images/generations", headers=headers,
                json={"model": model, "prompt": prompt[:4000] if dalle else prompt, "n": 1, "size": size, "quality": q},
            )
        if r.status_code >= 400:
            # OpenAI's own message is the diagnosis (a model the key cannot see, an unverified
            # organisation, a moderation block, an unsupported parameter) — keep it, not just the status.
            try:
                msg = str((r.json().get("error") or {}).get("message") or r.text)
            except Exception:  # noqa: BLE001
                msg = r.text
            raise RuntimeError(f"OpenAI {r.status_code} on {'edits' if references else 'generations'} with {model}: {msg[:300]}")
        data = r.json()["data"][0]
        _LAST.update({"model": model, "edit": bool(references)})
        if data.get("b64_json"):
            return base64.b64decode(data["b64_json"])
        img = await client.get(data["url"])
        img.raise_for_status()
        return img.content


async def _openai_render(prompt: str, *, quality: str = "medium", references: Optional[list[bytes]] = None) -> bytes:
    """gpt-image-1 by default; when the key cannot see a model, the next candidate is tried
    (`IMAGE_MODEL_OPENAI_FALLBACKS`), the one that answers is remembered for the process, and the
    models the key can actually see are logged once so the fix is visible in the logs."""
    global _WORKING_MODEL
    last: Optional[Exception] = None
    for model in _model_candidates():
        try:
            data = await _openai_call(model, prompt, quality=quality, references=references)
            if _WORKING_MODEL != model:
                print(f"[visual_gen] OpenAI image model in use: {model}")
                _WORKING_MODEL = model
            return data
        except RuntimeError as e:
            last = e
            if _is_missing_model(str(e)):
                print(f"[visual_gen] {e} — trying the next image model")
                continue
            raise
    await log_visible_image_models(" (no candidate answered)")
    raise last or RuntimeError("no OpenAI image model answered")


async def _openai_hero(prompt: str) -> bytes:
    return await _openai_render(prompt, quality="medium")


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


# ── what must survive a remake, and the story the image model is told ─────────

_FACT_RE = re.compile(r"\d|£|€|\$|%|www\.|https?://|\.(?:org|com|co\.uk|uk|net|charity)\b|@", re.I)


def protected_facts(layout: Optional[dict]) -> list[str]:
    """The lines on the previous version that carry information — claims, small print, and any line
    with a number, price, percentage, web address or handle. These must survive a remake word for
    word unless the change explicitly replaces one."""
    if not layout:
        return []
    out: list[str] = []
    for line in layout.get("claim_lines") or []:
        out.append(str(line))
    if layout.get("small_print"):
        out.append(str(layout["small_print"]))
    for f in ("headline", "subline", "cta"):
        if layout.get(f) and _FACT_RE.search(str(layout[f])):
            out.append(str(layout[f]))
    for line in layout.get("body_lines") or []:
        if _FACT_RE.search(str(line)):
            out.append(str(line))
    seen: list[str] = []
    for x in out:
        x = " ".join(x.split()).strip()
        if x and x not in seen:
            seen.append(x)
    return seen[:10]


def change_touches(fact: str, change: str) -> bool:
    """True when the change text names this fact — by a number, a web address or the fact itself —
    so the fact is the thing being changed and must not be locked."""
    c = (change or "").lower()
    if not c:
        return False
    f = fact.lower()
    if f in c:
        return True
    for tok in re.findall(r"\d[\d,.\s]{1,}\d|\d+|[a-z0-9.-]+\.(?:org|com|co\.uk|uk|net)\b", f):
        tok = tok.strip()
        if len(tok) >= 2 and tok in c:
            return True
    return False


async def story_for_prompt(session_id: str, probe: Optional[Probe], proposal: Optional[dict], change: str) -> str:
    """The whole story in a few hundred words: what the session asks, what the audience was asked and
    said about the last version, and what is being changed and why — so the image model works from
    the brief, not from a bare instruction."""
    from app.models.session import AnalysisSession
    parts: list[str] = []
    async with _db.AsyncSessionLocal() as db:
        sess = await db.get(AnalysisSession, session_id)
    if sess and sess.query:
        parts.append(f"The campaign question: {clip(str(sess.query), 300)}")
    try:
        from app.services.measurement import lab_brief
        b_ = await lab_brief.get(session_id)
        if b_ and b_.get("brief"):
            parts.append("The brief: " + clip(lab_brief.brief_for_prompt(b_["brief"], 700), 700))
    except Exception:  # noqa: BLE001 — the brief is a bonus
        pass
    agg = (probe.aggregates or {}) if probe else {}
    if agg.get("n"):
        q = str((probe.spec or {}).get("question") or "").strip()
        where = str((probe.spec or {}).get("setting") or "").strip()
        parts.append(f"{agg.get('n')} people were shown the last version" + (f" ({where})" if where else "") + (f" and asked: {q}" if q else "") + ".")
        if agg.get("sentence"):
            parts.append("What they said: " + clip(str(agg["sentence"]), 400))
        put_off = agg.get("put_off") or []
        if put_off:
            parts.append("What put them off: " + "; ".join(f"{x.get('value')} ({x.get('count')})" for x in put_off[:4]))
        noticed = agg.get("noticed") or []
        if noticed:
            parts.append("What they noticed first: " + "; ".join(f"{x.get('value')} ({x.get('count')})" for x in noticed[:3]))
    if proposal and proposal.get("changes"):
        lines = []
        for c in proposal["changes"][:4]:
            if isinstance(c, dict) and c.get("change"):
                lines.append(f"- {c['change']}" + (f" — {c.get('why')}" if c.get("why") else "") + (f" ({c.get('share')})" if c.get("share") else ""))
        if lines:
            parts.append("The changes this version makes, and why:\n" + "\n".join(lines))
        if proposal.get("expected"):
            parts.append("What should move: " + clip(str(proposal["expected"]), 200))
    elif change:
        parts.append("The change this version makes: " + clip(change, 400))
    return "\n".join(parts)


# ── the whole poster drawn by the provider (full render, 2026-10-26) ──────────

def render_mode() -> str:
    """"full": the provider draws the whole poster, words included (OpenAI only — Imagen's lettering
    is not reliable enough); "layered": a hero picture with the words set in type by the system."""
    st = get_settings()
    m = (st.image_render or "auto").strip().lower()
    if m == "auto":
        return "full" if provider_name() == "openai" else "layered"
    if m == "full":
        return "full" if provider_name() == "openai" else "layered"
    return "layered"


def poster_prompt(layout: dict, keep: list[dict], *, change: str = "", edit: bool = False, previous_issues: Optional[list[str]] = None,
                  story: str = "", other_posters: Optional[list[str]] = None, facts: Optional[list[str]] = None) -> str:
    """What the image model is asked for when it draws the whole poster: the whole story (why the
    poster exists, what the audience said, what is being changed and why), the photograph, the exact
    words, the palette, the keep-list, the facts that must not change — and, on a remake, which of
    the images provided is the base and what the others are for. Never an infographic: that is what
    came back when the words were the picture."""
    pal = layout.get("palette") or {}
    words = []
    if layout.get("headline"):
        words.append(f'HEADLINE (largest): "{layout["headline"]}"')
    if layout.get("subline"):
        words.append(f'SUB-LINE: "{layout["subline"]}"')
    for line in layout.get("body_lines") or []:
        words.append(f'LINE: "{line}"')
    for line in layout.get("claim_lines") or []:
        words.append(f'CLAIM (prominent, in the accent colour): "{line}"')
    if layout.get("cta"):
        words.append(f'CALL TO ACTION (a clear button or band): "{layout["cta"]}"')
    if layout.get("small_print"):
        words.append(f'SMALL PRINT (small, legible, at the foot): "{layout["small_print"]}"')
    must_show = [k["value"] for k in keep if k["type"] == "present"]
    must_not = [k["value"] for k in keep if k["type"] == "absent"]
    exact = [k["value"] for k in keep if k["type"] == "text"]
    parts = []
    if edit:
        parts.append(("Image 1 is the poster to remake. " if other_posters else "The image provided is the poster to remake. ")
                     + "Make its next version: keep its photograph, subject, composition, colours and feel — it must read as the same campaign. "
                     + (f"Make these changes and nothing else: {change}" if change else "Refresh it without changing what it says."))
        if other_posters:
            parts.append("The other images provided are the posters the audience compared it with — "
                         + "; ".join(f"image {k + 2} = \"{lbl}\"" for k, lbl in enumerate(other_posters))
                         + ". They are reference only: take from them exactly what the changes ask for (a picture, a warmth, a layout idea the audience preferred) and nothing else; do not copy their words.")
    else:
        parts.append("A finished, print-ready portrait poster (3:4), art-directed like real campaign work.")
    if story:
        parts.append("THE STORY — why this poster exists and what the audience said about the last version:\n" + story)
    parts.append("STYLE: a real photograph as the main picture — real people or animals in a real place, natural light, editorial quality. "
                 "NOT an infographic, NOT a diagram, NOT clip art or icon grids, NOT a stock-vector look, no watermark, no fake logos.")
    parts.append("THE PICTURE: " + str(layout.get("hero_prompt") or "a photograph that makes the headline true")
                 + (f" Place the picture at the {layout.get('hero_placement')} with the words beside or below it." if str(layout.get("hero_placement") or "top") in ("top", "left") else ""))
    if words:
        parts.append("THE WORDS — render every line below exactly as written, spelled exactly, in this order of prominence, and write NOTHING else on the poster:\n" + "\n".join(words))
    parts.append(f"TYPOGRAPHY: clean, large, highly legible, strong contrast. COLOURS: background {pal.get('bg') or 'dark'}, text {pal.get('fg') or 'white'}, accent {pal.get('accent') or 'warm orange'}.")
    locked = list(dict.fromkeys([*(facts or []), *exact]))
    if locked:
        parts.append("FACTS THAT MUST NOT CHANGE — render each exactly as written: " + "; ".join(f'"{x}"' for x in locked))
    parts.append("Never invent a phone number, address, web address, price, date, statistic, name or logo that is not in THE WORDS above.")
    if must_show:
        parts.append("MUST SHOW: " + "; ".join(must_show))
    if must_not:
        parts.append("MUST NOT SHOW: " + "; ".join(must_not))
    if previous_issues:
        parts.append("The previous attempt got these wrong — fix them, change nothing else: " + "; ".join(previous_issues))
    return "\n\n".join(parts)


async def render_full(layout: dict, keep: list[dict], *, session_id: str, model: str, change: str = "", references: Optional[list[bytes]] = None,
                      story: str = "", other_posters: Optional[list[str]] = None, facts: Optional[list[str]] = None) -> Optional[dict]:
    """The provider draws the whole poster. Normalise → keep-list check by vision (there is no typed
    layer to check mechanically) → if an exact-text item failed, one more attempt that names the
    misses; the attempt with fewer failures is kept. None when the provider fails outright, so the
    caller can fall back to the layered render."""
    from app.core.monitoring import record_image_call
    st = get_settings()
    best = None
    issues: list[str] = []
    for attempt in (1, 2):
        prompt = poster_prompt(layout, keep, change=change, edit=bool(references), previous_issues=issues or None,
                               story=story, other_posters=other_posters, facts=facts)
        started = time.monotonic()
        try:
            raw = await _openai_render(prompt, quality=st.image_quality_openai, references=references or None)
            record_image_call(model=str(_LAST.get("model") or st.image_model_openai), session_id=session_id, label="visual:poster", cost_usd=st.image_cost_openai_full_usd,
                              elapsed_sec=time.monotonic() - started, status="success")
        except Exception as e:  # noqa: BLE001
            record_image_call(model=st.image_model_openai, session_id=session_id, label="visual:poster", cost_usd=0.0,
                              elapsed_sec=time.monotonic() - started, status="error")
            print(f"[visual_gen] full render failed on attempt {attempt}: {type(e).__name__}: {str(e)[:300]}")
            if best:
                break
            return {"error": f"{type(e).__name__}: {str(e)[:300]}"}
        norm = images_mod.normalise(raw, "poster.png")
        check = await check_image(session_id=session_id, data=norm["data"], media_type=norm["media_type"], width=norm["width"], height=norm["height"],
                                  layout=None, keep=keep, model=model, label=str(layout.get("headline") or "poster"))
        failed = [i for i in check["items"] if not i["ok"]]
        cand = {"norm": norm, "check": check, "attempts": attempt, "prompt": prompt, "model": str(_LAST.get("model") or st.image_model_openai), "edit": bool(references) and bool(_LAST.get("edit", True))}
        if best is None or len(failed) < len([i for i in best["check"]["items"] if not i["ok"]]):
            best = cand
        text_misses = [f'"{i["value"]}" ({i["note"]})' for i in failed if i["type"] == "text"]
        if not text_misses:
            break
        issues = [f"the words {m}" for m in text_misses]
    return best


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

# ── from the reactions to the next version (step 4, 2026-10-26) ───────────────

NEXT_BASES = ("most said", "few said, hard-hitting", "from the numbers")

NEXT_SCHEMA = obj({
    "base_image_id": s("The id of the image to build the next version on, copied exactly from THE IMAGES THEY SAW — the one closer to working, or the one the reactions point at"),
    "base_why": s("One sentence: why build on that one"),
    "changes": arr(obj({
        "change": s("The change, in one or two sentences a designer could act on"),
        "basis": enum(list(NEXT_BASES), "'most said' when it answers what the largest group asked for; 'few said, hard-hitting' when few raised it but it is the objection that would sink the piece or the gain that would carry it; 'from the numbers' when it comes from the verdict, strength or feeling split rather than anyone's words"),
        "share": s("How many said it, in plain words — '17 of 24 who named a change', 'three of the people it did not work on', 'said once'"),
        "why": s("One or two sentences: the reaction this answers and why it matters even if few said it"),
        "cites": arr(s("A twin's name, as given"), "Who said it", max_items=6),
    }, required=["change", "basis", "share", "why", "cites"]),
        "The changes for the next version: the headline change first — what most people asked for — then up to three more that are relevant and hard-hitting even when few said them. Never more than four; never two that say the same thing.", max_items=4),
    "keep": arr(s("Something that is working and must stay, in a few words"), "What the audience responded to and the next version must keep", max_items=5),
    "expected": s("One sentence: what should move if these changes work, for whom, and what it risks elsewhere"),
}, required=["base_image_id", "changes", "keep", "expected"])

NEXT_SYSTEM = (
    "You are a creative director reading an audience's reactions to an image (or to several shown together as one piece) "
    "and deciding the next version. Read it all: what put people off and how many, where their eyes went first, the one "
    "thing each would change, the words of those it did not work on, and the verdict split. Then propose the changes for "
    "the next version: FIRST what most people asked for, THEN up to three more that are relevant and hard-hitting even if "
    "only a few said them — the objection that would sink the piece with the audience it is for, the missing thing that "
    "would make it actionable, the gain that would carry it. Weigh who said it, not only how many: a deciding objection from "
    "the people it did not work on outranks a nicety from those it already works on. Each change must be concrete enough "
    "for a designer to act on and must say in plain words how many said it and who. Name what is working and must stay. "
    "Never propose removing anything on a keep-list. When several images were shown, pick the one to build on and say why. "
    "Record the proposal with the tool."
)


def _images_block(images: list[SessionImage], *, together: bool) -> str:
    lines = ["THE IMAGES THEY SAW TOGETHER AS ONE PIECE:" if together else "THE IMAGE THEY SAW:"]
    for k, img in enumerate(images, 1):
        lines.append(f"{k}. \"{img.label or img.filename or 'image'}\" (id {img.id})")
        layout = img.layout or {}
        words = [str(layout.get(f)) for f in ("headline", "subline", "cta") if layout.get(f)] + [str(x) for x in (layout.get("claim_lines") or [])]
        if words:
            lines.append("   words on it: " + " / ".join(words)[:400])
        keep = normalise_keep_list(img.keep_list)
        if keep:
            lines.append("   keep-list: " + "; ".join(f"{item['type']}: {item['value']}" for item in keep))
    return "\n".join(lines)


async def propose_next(*, session_id: str, probe: Probe, images: list[SessionImage], model: str, base_id: Optional[str] = None) -> dict:
    """Read a whole Visuals run and propose the next version: which image to build on, the headline
    change (what most said), the hard-hitting changes few said, what to keep, and what should move.
    Nothing is made here — the proposal goes to /remake as `proposal`."""
    reactions = _reactions_block(probe, full=True)
    if not reactions:
        raise ValueError("That run has no answers to read.")
    if not images:
        raise ValueError("That run's images are gone.")
    ids = [i.id for i in images]
    if base_id and base_id not in ids:
        raise ValueError("That image was not in the run.")
    blocks = [_images_block(images, together=len(images) > 1)]
    q = str((probe.spec or {}).get("question") or "").strip()
    if q:
        blocks.append(f"THE QUESTION THEY WERE ASKED: {q}")
    blocks.append(reactions)
    if base_id:
        blocks.append(f"BUILD ON IMAGE id {base_id} — the analyst has fixed the base; copy that id.")
    elif len(images) == 1:
        blocks.append(f"BUILD ON IMAGE id {ids[0]} — it is the only one; copy that id.")
    blocks.append("Propose the next version with the tool.")
    out = await analyze(NEXT_SCHEMA, NEXT_SYSTEM, "\n\n".join(blocks), session_id=session_id, label="visual:propose", model=model, max_tokens=1600)
    picked = str(out.get("base_image_id") or "").strip()
    base = base_id or (picked if picked in ids else ids[0])
    changes = []
    for c in (out.get("changes") or [])[:4]:
        if not isinstance(c, dict) or not str(c.get("change") or "").strip():
            continue
        changes.append({
            "change": str(c.get("change")).strip(),
            "basis": c.get("basis") if c.get("basis") in NEXT_BASES else "most said",
            "share": str(c.get("share") or "").strip(),
            "why": str(c.get("why") or "").strip(),
            "cites": [str(x).strip() for x in (c.get("cites") or []) if str(x).strip()][:6],
        })
    if not changes:
        raise ValueError("The planner proposed no change.")
    base_img = next(i for i in images if i.id == base)
    cites: list[str] = []
    for c in changes:
        for n in c["cites"]:
            if n not in cites:
                cites.append(n)
    return {
        "probe_id": probe.id,
        "base_image_id": base,
        "base_label": base_img.label or base_img.filename or "image",
        "base_why": str(out.get("base_why") or "").strip(),
        "changes": changes,
        "keep": [str(k).strip() for k in (out.get("keep") or []) if str(k).strip()][:5],
        "expected": str(out.get("expected") or "").strip(),
        # The first change on its own, for anything that still reads the step-3 shape.
        "change": changes[0]["change"],
        "why": changes[0]["why"],
        "cites": cites,
    }


def change_text(proposal: dict, selected: Optional[list[int]] = None, note: str = "") -> str:
    """The change note a remake gets from a proposal: the chosen changes, numbered when there are
    several, plus the analyst's own note."""
    items = [c for c in (proposal.get("changes") or []) if isinstance(c, dict) and str(c.get("change") or "").strip()]
    if selected is not None:
        items = [c for k, c in enumerate(items) if k in selected]
    if not items and not proposal.get("changes") and str(proposal.get("change") or "").strip():
        items = [{"change": proposal["change"]}]                             # the step-3 shape: one change
    lines = [f"{k}) {str(c['change']).strip()}" for k, c in enumerate(items, 1)] if len(items) > 1 else [str(c["change"]).strip() for c in items]
    if (note or "").strip():
        lines.append(f"Also: {note.strip()}")
    return "\n".join(lines)


async def images_for_probe(session_id: str, probe: Probe) -> list[SessionImage]:
    """The image rows a run showed, in the order the spec names them (missing ones skipped)."""
    refs = images_mod.refs_in(probe.spec or {})
    if not refs:
        return []
    async with _db.AsyncSessionLocal() as db:
        rows = (await db.execute(select(SessionImage).where(SessionImage.session_id == session_id, SessionImage.id.in_([r["id"] for r in refs])))).scalars().all()
    by_id = {r.id: r for r in rows}
    return [by_id[r["id"]] for r in refs if r["id"] in by_id]


async def propose_change(*, row: SessionImage, probe: Probe, model: str) -> dict:
    """Step 3's per-image call: the same planner with the base fixed to this image."""
    images = await images_for_probe(row.session_id, probe)
    if not any(i.id == row.id for i in images):
        images = [row] + images
    return await propose_next(session_id=row.session_id, probe=probe, images=images, model=model, base_id=row.id)


async def latest_visual_probe(session_id: str, image_id: str) -> Optional[Probe]:
    """The newest complete Visuals run that showed this image — on its own if there is one, else
    among others (a run that showed two posters as one piece still read this one)."""
    async with _db.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Probe).where(Probe.session_id == session_id, Probe.instrument == "visual", Probe.status == "complete")
            .order_by(Probe.created_at.desc())
        )).scalars().all()
    together = None
    for p in rows:
        refs = images_mod.refs_in(p.spec or {})
        if not (p.aggregates or {}).get("n") or not any(r["id"] == image_id for r in refs):
            continue
        if len(refs) == 1:
            return p
        together = together or p
    return together


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


async def start_remake(session_id: str, parent: SessionImage, *, change: str, keep_list: Any, probe_id: Optional[str], proposal: Optional[dict], mode: str,
                       selected: Optional[list[int]] = None, note: str = "") -> SessionImage:
    keep = normalise_keep_list(keep_list if keep_list is not None else parent.keep_list)
    model = get_settings().agent_model(mode)
    row = SessionImage(
        session_id=session_id, label=f"{parent.label or 'image'} · remake"[:200], filename="", media_type="image/png",
        width=1, height=1, size_bytes=len(PLACEHOLDER_PNG), sha256="", source="remake", status="generating", parent_id=parent.id,
        change_note=(change or "").strip(), keep_list=keep,
        brief={"change": (change or "").strip(), "probe_id": probe_id, "proposal": proposal, "selected": selected, "note": (note or "").strip(), "mode": mode, "model": model}, data=PLACEHOLDER_PNG,
    )
    async with _db.AsyncSessionLocal() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def _finish(row_id: str, *, layout: dict, hero_provider: str, hero_error: Optional[str], rationale_extra: dict, model: str,
                  change: str = "", references: Optional[list[bytes]] = None, story: str = "", other_posters: Optional[list[str]] = None,
                  facts: Optional[list[str]] = None) -> None:
    async with _db.AsyncSessionLocal() as db:
        row = await db.get(SessionImage, row_id)
        if not row:
            return
        session_id, keep, brief = row.session_id, normalise_keep_list(row.keep_list), dict(row.brief or {})
    if render_mode() == "full":
        full = await render_full(layout, keep, session_id=session_id, model=model, change=change, references=references,
                                 story=story, other_posters=other_posters, facts=facts)
        render_error = (full or {}).get("error")
        if full and full.get("norm"):
            norm, check = full["norm"], full["check"]
            brief.update({**rationale_extra, "rationale": layout.get("rationale", ""), "hero_prompt": layout.get("hero_prompt", ""),
                          "hero_provider": "openai", "hero_error": None, "kept": layout.get("kept") or [],
                          "render": "full", "render_attempts": full["attempts"], "reference_used": bool(full.get("edit")), "references_used": len(references or []) if full.get("edit") else 0,
                          "image_model": full.get("model"),
                          "other_posters": list(other_posters or []), "locked_facts": list(facts or []), "poster_prompt": full["prompt"][:4000]})
            await _set(row_id, data=norm["data"], media_type=norm["media_type"], width=norm["width"], height=norm["height"], size_bytes=len(norm["data"]),
                       sha256=norm["sha256"], layout=layout, brief=brief, check_result=check, status="ready", error=None,
                       label=(str(layout.get("headline") or "").strip()[:80] or None) or "Generated")
            return
        print("[visual_gen] full render unavailable, falling back to the layered render")
    else:
        render_error = None
    pal = layout.get("palette") or {}
    accent = _hex(pal.get("accent"), (240, 160, 60))
    hero_bytes, provider, err = await generate_hero(str(layout.get("hero_prompt") or ""), session_id=session_id, size=(1024, 1366), accent=accent) \
        if str(layout.get("hero_placement") or "top") != "none" else (None, "none", None)
    png = compose(layout, hero_bytes)
    norm = images_mod.normalise(png, "generated.png")
    check = await check_image(session_id=session_id, data=norm["data"], media_type=norm["media_type"], width=norm["width"], height=norm["height"],
                              layout=layout, keep=keep, model=model, label=str(layout.get("headline") or "image"))
    brief.update({**rationale_extra, "rationale": layout.get("rationale", ""), "hero_prompt": layout.get("hero_prompt", ""),
                  "hero_provider": provider, "hero_error": err, "kept": layout.get("kept") or [], "render": "layered", "reference_used": False,
                  "render_error": render_error})
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
        story = await story_for_prompt(session_id, None, None, note)
        await _finish(image_id, layout=layout, hero_provider="", hero_error=None, rationale_extra={"from": "session", "context_chars": len(context)}, model=model, story=story)
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
            # The parent's picture anchors the remake unless it was a placeholder drawn in code.
            reference = bytes(parent.data) if (parent.source == "upload" or (parent.brief or {}).get("hero_provider") not in (None, "", "none")) else None
            proposal = brief.get("proposal") if isinstance(brief.get("proposal"), dict) else None
        if not parent_layout:
            async with _db.AsyncSessionLocal() as db:
                parent = await db.get(SessionImage, parent_id)
            parent_layout = await read_image(parent, model=model)
            await _set(parent_id, layout=parent_layout)
        if probe is None:
            probe = await latest_visual_probe(session_id, parent_id)
        # Important information on the previous version survives unless the change names it.
        facts = [f for f in protected_facts(parent_layout) if not change_touches(f, change)]
        if facts:
            keep = normalise_keep_list(keep + [{"type": "text", "value": f} for f in facts])
            await _set(image_id, keep_list=keep)
        # Every poster the audience saw in that run goes to the image model: the base first, the others as reference.
        references: list[bytes] = [reference] if reference else []
        other_posters: list[str] = []
        if probe is not None:
            for other in await images_for_probe(session_id, probe):
                if other.id == parent_id or other.status not in (None, "", "ready"):
                    continue
                if other.source == "upload" or (other.brief or {}).get("hero_provider") not in (None, "", "none"):
                    references.append(bytes(other.data))
                    other_posters.append(other.label or other.filename or "poster")
        if not reference:
            references, other_posters = [], []                                 # no base picture → a generation, not an edit
        story = await story_for_prompt(session_id, probe, proposal, change)
        context = await session_context(session_id)
        layout = await write_layout(session_id=session_id, note="", keep=keep, model=model, context=context,
                                    parent_layout=parent_layout, change=change, reactions=_reactions_block(probe), facts=facts)
        await _finish(image_id, layout=layout, hero_provider="", hero_error=None,
                      rationale_extra={"from": "remake", "parent_id": parent_id, "reactions_probe_id": probe.id if probe else None}, model=model,
                      change=change, references=references, story=story, other_posters=other_posters, facts=facts)
        print(f"[visual_gen] remade {image_id} from {parent_id}: {str(layout.get('headline'))[:60]}")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        await _set(image_id, status="failed", error=f"{type(e).__name__}: {str(e)[:300]}")


async def recheck(row: SessionImage, *, model: str) -> dict:
    keep = normalise_keep_list(row.keep_list)
    return await check_image(session_id=row.session_id, data=row.data, media_type=row.media_type, width=row.width, height=row.height,
                             layout=row.layout, keep=keep, model=model, label=row.label or "image")
