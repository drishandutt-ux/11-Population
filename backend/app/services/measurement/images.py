"""Session images — the Visual Lab's store, and the one place images are turned into prompt content.

Step 1 (2026-10-26): an analyst uploads images into a session; any probe whose spec carries
`images: [{id, label}]` shows them to every twin it asks, as real image blocks the model looks
at, not as a description. The probe runner knows only two things about images: how to load the
ones a spec names (`for_prompt`) and how to lay them out in a message (`vision_content`). Every
instrument that wants to show pictures reuses exactly that.

Images are normalised at upload: decoded with Pillow, flattened, the long edge brought down to
`MAX_EDGE` (the size Claude reads best; anything larger is downscaled by the API anyway and
costs the same), and re-encoded. A poster that arrived as a 9 MB PNG is stored as a few hundred
kilobytes and travels as such on every one of the hundreds of calls a probe makes.
"""
from __future__ import annotations

import base64
import hashlib
import io
import math
from typing import Any, Optional

from sqlalchemy import select

from app.core import database as _db
from app.models.measurement import SessionImage

MAX_UPLOAD_BYTES = 20 * 1024 * 1024    # what we accept over the wire
MAX_EDGE = 1568                        # the long edge Claude's vision reads at full fidelity
JPEG_QUALITY = 88
IMAGES_KEY = "images"                  # the spec key every image-showing instrument uses
MAX_IMAGES_PER_SPEC = 6
# Claude bills an image at roughly width × height / 750 tokens once it is within MAX_EDGE.
TOKENS_PER_PIXEL = 1 / 750


class ImageError(ValueError):
    """A file that is not an image we can show, or is over the limit."""


# ── normalising an upload ─────────────────────────────────────────────────────

def normalise(raw: bytes, filename: str = "") -> dict:
    """Decode, flatten, downscale and re-encode an uploaded image.

    Returns {data, media_type, width, height, sha256}. Transparency is kept as PNG; everything
    else becomes JPEG — the model does not care, and JPEG keeps the per-call payload small."""
    if not raw:
        raise ImageError("The file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageError(f"The file is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    try:
        from PIL import Image, ImageOps
    except ImportError as e:  # pragma: no cover — Pillow is in requirements
        raise ImageError("Image support is not installed on the server.") from e
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as e:  # noqa: BLE001
        raise ImageError(f"'{filename or 'the file'}' is not an image we can read.") from e
    # Honour the camera's orientation tag, then drop EXIF with the re-encode.
    try:
        img = ImageOps.exif_transpose(img) or img
    except Exception:  # noqa: BLE001
        pass
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    w, h = img.size
    scale = min(1.0, MAX_EDGE / float(max(w, h)))
    if scale < 1.0:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    out = io.BytesIO()
    if has_alpha:
        img = img.convert("RGBA")
        img.save(out, format="PNG", optimize=True)
        media_type = "image/png"
    else:
        img = img.convert("RGB")
        img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        media_type = "image/jpeg"
    data = out.getvalue()
    return {
        "data": data, "media_type": media_type, "width": img.size[0], "height": img.size[1],
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def tokens_for(width: int, height: int) -> int:
    """What one showing of this image costs in input tokens, roughly."""
    if not width or not height:
        return 1600
    return int(math.ceil(width * height * TOKENS_PER_PIXEL))


# ── reading a spec ────────────────────────────────────────────────────────────

def refs_in(spec: dict) -> list[dict]:
    """The image references a spec carries: [{id, label, option?}]. Tolerates bare ids."""
    raw = (spec or {}).get(IMAGES_KEY)
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append({"id": item.strip(), "label": ""})
        elif isinstance(item, dict) and str(item.get("id") or "").strip():
            ref = {"id": str(item["id"]).strip(), "label": str(item.get("label") or "").strip()[:200]}
            if item.get("option"):
                ref["option"] = str(item["option"])
            out.append(ref)
    return out[:MAX_IMAGES_PER_SPEC]


def validate_refs(spec: dict, *, required: bool = True) -> list[str]:
    """Human-readable problems with a spec's images (used by instruments' `validate`)."""
    raw = (spec or {}).get(IMAGES_KEY)
    refs = refs_in(spec)
    if required and not refs:
        return ["Add at least one image for them to look at."]
    if isinstance(raw, list) and len(raw) > MAX_IMAGES_PER_SPEC:
        return [f"At most {MAX_IMAGES_PER_SPEC} images in one run."]
    return []


def payload(img: SessionImage) -> dict:
    """What the API returns for an image — never the bytes; those come from /file."""
    return {
        "id": img.id, "session_id": img.session_id, "label": img.label, "filename": img.filename,
        "media_type": img.media_type, "width": img.width, "height": img.height, "size_bytes": img.size_bytes,
        "source": img.source, "parent_id": img.parent_id, "keep_list": img.keep_list or [],
        "tokens_per_showing": tokens_for(img.width, img.height),
        "created_at": img.created_at.isoformat() if img.created_at else None,
    }


# ── loading for a prompt ──────────────────────────────────────────────────────

async def for_prompt(session_id: str, spec: dict) -> tuple[list[dict], list[str]]:
    """Load the images a spec names, once per probe run.

    Returns (images, missing): each image is {id, label, option, media_type, data_b64, width,
    height} in the spec's order; `missing` lists ids the session no longer holds. The caller
    decides whether a missing image fails the run (it should — a twin asked about a poster it
    cannot see would answer from the label)."""
    refs = refs_in(spec)
    if not refs:
        return [], []
    ids = [r["id"] for r in refs]
    async with _db.AsyncSessionLocal() as db:   # read at call time so tests can swap the engine
        rows = (await db.execute(
            select(SessionImage).where(SessionImage.session_id == session_id, SessionImage.id.in_(ids))
        )).scalars().all()
    by_id = {r.id: r for r in rows}
    images, missing = [], []
    for ref in refs:
        row = by_id.get(ref["id"])
        if not row:
            missing.append(ref["id"])
            continue
        images.append({
            "id": row.id,
            "label": ref.get("label") or row.label or row.filename or "image",
            "option": ref.get("option") or "",
            "media_type": row.media_type,
            "data_b64": base64.b64encode(row.data).decode("ascii"),
            "width": row.width, "height": row.height,
        })
    return images, missing


def caption_for(img: dict, index: int, total: int) -> str:
    """The line above each image in the message: which option it belongs to, what it is called."""
    if img.get("option"):
        return f"OPTION {img['option']} — {img.get('label') or 'image'}"
    if total > 1:
        return f"IMAGE {index + 1} of {total} — {img.get('label') or 'image'}"
    return f"THE IMAGE — {img.get('label') or 'image'}"


def vision_content(images: list[dict], text: str) -> list[dict]:
    """Lay the images out as message content: a caption, the image, … then the written message.

    Captions carry the option key for a choose-between run so the twin can name what it picked;
    the text block comes last so the question is the freshest thing the model read."""
    blocks: list[dict] = []
    total = len(images)
    for k, img in enumerate(images):
        blocks.append({"type": "text", "text": caption_for(img, k, total)})
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": img["media_type"], "data": img["data_b64"]}})
    blocks.append({"type": "text", "text": text})
    return blocks


def looking_at_block(images: list[dict], spec: dict) -> str:
    """The user-message paragraph that tells the twin what the attached images are and how to
    look at them. `setting` (where they would come across it) is optional."""
    n = len(images)
    options = sorted({i["option"] for i in images if i.get("option")})
    where = str((spec or {}).get("setting") or "").strip()
    head = "WHAT YOU ARE LOOKING AT: "
    if options:
        head += f"{n} image{'s' if n != 1 else ''} attached above, labelled by option ({', '.join(options)})."
    elif n == 1:
        head += "the image attached above."
    else:
        head += f"{n} images attached above, shown together as one piece."
    if where:
        head += f" You come across it like this: {where}."
    head += (
        " Look at it the way you would in real life, not like an analyst: what you notice first is "
        "what you notice first, and if a line is too small to read or means nothing to you, say so. "
        "React to what is actually in the picture — do not invent text or details that are not there."
    )
    return head


def tokens_in(images: list[dict]) -> int:
    return sum(tokens_for(int(i.get("width") or 0), int(i.get("height") or 0)) for i in images)


async def session_image_tokens(session_id: str, spec: dict) -> int:
    """For the cost estimate: the image tokens one showing of this spec adds to a call."""
    refs = refs_in(spec)
    if not refs:
        return 0
    async with _db.AsyncSessionLocal() as db:   # read at call time so tests can swap the engine
        rows = (await db.execute(
            select(SessionImage.width, SessionImage.height)
            .where(SessionImage.session_id == session_id, SessionImage.id.in_([r["id"] for r in refs]))
        )).all()
    return sum(tokens_for(w, h) for w, h in rows)


def referenced_by(spec: Any, image_id: str) -> bool:
    """Whether a stored probe/experiment spec (or a variant list) names this image."""
    if isinstance(spec, dict):
        if any(r["id"] == image_id for r in refs_in(spec)):
            return True
        return any(referenced_by(v, image_id) for v in spec.values() if isinstance(v, (dict, list)))
    if isinstance(spec, list):
        return any(referenced_by(v, image_id) for v in spec if isinstance(v, (dict, list)))
    return False
