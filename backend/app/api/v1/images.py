"""Session images API — the Visual Lab's store (step 1, 2026-10-26).

Upload, list, rename, fetch the bytes, delete. Images belong to a session and are shown to its
twins by any Lab run whose spec names them (`images: [{id, label}]`). The bytes are served
from `/file` to the signed-in user; the list never carries them.
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, get_current_user, get_owned_session
from app.core.database import get_db
from app.models.measurement import Experiment, Probe, SessionImage
from app.services.measurement import images as images_mod

router = APIRouter(prefix="/sessions", tags=["images"])

MAX_IMAGES_PER_SESSION = 200


class RenameRequest(BaseModel):
    label: str = ""


async def _owned_image(session_id: str, image_id: str, db: AsyncSession) -> SessionImage:
    img = await db.get(SessionImage, image_id)
    if not img or img.session_id != session_id:
        raise HTTPException(404, "Image not found")
    return img


@router.get("/{session_id}/images")
async def list_images(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Every image this session holds, newest first — metadata only."""
    await get_owned_session(session_id, user, db)
    rows = (await db.execute(
        select(SessionImage).where(SessionImage.session_id == session_id).order_by(SessionImage.created_at.desc())
    )).scalars().all()
    return {"images": [images_mod.payload(r) for r in rows]}


@router.post("/{session_id}/images")
async def upload_image(
    session_id: str,
    file: UploadFile = File(...),
    label: str = Form(default=""),
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add an image to the session. It is decoded, downscaled to the size the vision model reads
    best and re-encoded, so what is stored is what every twin will be shown."""
    await get_owned_session(session_id, user, db)
    count = len((await db.execute(select(SessionImage.id).where(SessionImage.session_id == session_id))).all())
    if count >= MAX_IMAGES_PER_SESSION:
        raise HTTPException(400, f"This session already holds {MAX_IMAGES_PER_SESSION} images. Delete some first.")
    raw = await file.read()
    filename = (file.filename or "").strip()[:300]
    try:
        norm = images_mod.normalise(raw, filename)
    except images_mod.ImageError as e:
        raise HTTPException(400, str(e))
    img = SessionImage(
        session_id=session_id,
        label=(label or "").strip()[:200] or (filename.rsplit(".", 1)[0] if filename else "")[:200],
        filename=filename, media_type=norm["media_type"], width=norm["width"], height=norm["height"],
        size_bytes=len(norm["data"]), sha256=norm["sha256"], source="upload", data=norm["data"],
    )
    db.add(img)
    await db.commit()
    await db.refresh(img)
    return images_mod.payload(img)


@router.get("/{session_id}/images/{image_id}")
async def get_image(session_id: str, image_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    return images_mod.payload(await _owned_image(session_id, image_id, db))


@router.get("/{session_id}/images/{image_id}/file")
async def get_image_file(session_id: str, image_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The bytes, as stored (already normalised). Immutable, so the browser may cache it."""
    await get_owned_session(session_id, user, db)
    img = await _owned_image(session_id, image_id, db)
    return Response(content=img.data, media_type=img.media_type,
                    headers={"Cache-Control": "private, max-age=86400", "ETag": img.sha256[:32]})


@router.patch("/{session_id}/images/{image_id}")
async def rename_image(session_id: str, image_id: str, body: RenameRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    img = await _owned_image(session_id, image_id, db)
    img.label = (body.label or "").strip()[:200]
    await db.commit()
    await db.refresh(img)
    return images_mod.payload(img)


@router.delete("/{session_id}/images/{image_id}")
async def delete_image(session_id: str, image_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Remove an image. Refused (409) while a run in this session names it: a stored result must
    keep the picture it was measured on."""
    await get_owned_session(session_id, user, db)
    img = await _owned_image(session_id, image_id, db)
    probes = (await db.execute(select(Probe.spec).where(Probe.session_id == session_id))).scalars().all()
    experiments = (await db.execute(select(Experiment.variants).where(Experiment.session_id == session_id))).scalars().all()
    used = sum(1 for sp in probes if images_mod.referenced_by(sp or {}, image_id)) \
        + sum(1 for vs in experiments if images_mod.referenced_by(vs or [], image_id))
    if used:
        raise HTTPException(409, f"This image is part of {used} run{'s' if used != 1 else ''} in this session. Delete those runs first.")
    await db.delete(img)
    await db.commit()
    return {"deleted": image_id}
