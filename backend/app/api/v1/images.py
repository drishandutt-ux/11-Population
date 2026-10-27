"""Session images API — the Visual Lab's store (step 1, 2026-10-26).

Upload, list, rename, fetch the bytes, delete. Images belong to a session and are shown to its
twins by any Lab run whose spec names them (`images: [{id, label}]`). The bytes are served
from `/file` to the signed-in user; the list never carries them.
"""
from typing import Optional

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, get_current_user, get_owned_session
from app.core.config import get_settings
from app.core.database import get_db
from app.models.measurement import Experiment, Probe, SessionImage
from app.services.measurement import images as images_mod
from app.services.measurement import visual_gen

router = APIRouter(prefix="/sessions", tags=["images"])

MAX_IMAGES_PER_SESSION = 200


class RenameRequest(BaseModel):
    label: Optional[str] = None
    keep_list: Optional[list[Any]] = None


class GenerateRequest(BaseModel):
    note: str = ""
    keep_list: list[Any] = []
    mode: str = "fast"


class RemakeRequest(BaseModel):
    change: str = ""
    keep_list: Optional[list[Any]] = None       # None = inherit the parent's
    probe_id: Optional[str] = None              # the Visuals run the change answers (else the latest on the parent)
    proposal: Optional[dict] = None             # what /propose returned, kept on the brief
    selected: Optional[list[int]] = None        # which of the proposal's changes to make (indexes); None = all
    note: str = ""                              # the analyst's own addition to the proposal
    retest: bool = True                         # re-show the new version to the same twins when ready (the proof)
    segment: Optional[dict] = None              # {key, label, value}: a version for one group of the run
    mode: str = "fast"


class ProposeRequest(BaseModel):
    probe_id: Optional[str] = None
    mode: str = "fast"


class ProposeNextRequest(BaseModel):
    probe_id: str
    base_image_id: Optional[str] = None         # fix the image to build on; else the planner picks
    mode: str = "fast"


class ModeRequest(BaseModel):
    mode: str = "fast"


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
async def update_image(session_id: str, image_id: str, body: RenameRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Rename, or set the keep-list (what every remake of this image must honour)."""
    await get_owned_session(session_id, user, db)
    img = await _owned_image(session_id, image_id, db)
    if body.label is not None:
        img.label = body.label.strip()[:200]
    if body.keep_list is not None:
        img.keep_list = visual_gen.normalise_keep_list(body.keep_list)
    await db.commit()
    await db.refresh(img)
    return images_mod.payload(img)


@router.post("/{session_id}/images/generate")
async def generate_image(session_id: str, body: GenerateRequest, background_tasks: BackgroundTasks, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Make an image from what the session knows plus the analyst's note (the Visual Lab, step 3).
    Returns the row at once with status `generating`; the page polls the list until it is ready."""
    await get_owned_session(session_id, user, db)
    mode = "pro" if body.mode == "pro" else "fast"
    row = await visual_gen.start_generate(session_id, note=body.note, keep_list=body.keep_list, mode=mode)
    background_tasks.add_task(visual_gen.run_generate, row.id)
    return images_mod.payload(row)


@router.post("/{session_id}/images/{image_id}/remake")
async def remake_image(session_id: str, image_id: str, body: RemakeRequest, background_tasks: BackgroundTasks, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """A new version of this image with one change, honouring the keep-list; the parent is kept and
    the child points at it (step 2). An uploaded parent is first read into a layout."""
    await get_owned_session(session_id, user, db)
    parent = await _owned_image(session_id, image_id, db)
    if (parent.status or "ready") != "ready":
        raise HTTPException(409, "This image is not ready yet.")
    if not (body.change or "").strip() and not body.proposal:
        raise HTTPException(400, "Say what to change.")
    mode = "pro" if body.mode == "pro" else "fast"
    change = (body.change or "").strip() or visual_gen.change_text(body.proposal or {}, body.selected, body.note)
    if not change.strip():
        raise HTTPException(400, "Pick at least one change to make.")
    row = await visual_gen.start_remake(session_id, parent, change=change, keep_list=body.keep_list, probe_id=body.probe_id,
                                        proposal=body.proposal, mode=mode, selected=body.selected, note=body.note,
                                        retest=body.retest, segment=body.segment)
    background_tasks.add_task(visual_gen.run_remake, row.id)
    return images_mod.payload(row)


@router.post("/{session_id}/images/{image_id}/retest")
async def retest_image(session_id: str, image_id: str, background_tasks: BackgroundTasks, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Re-show a ready remake to the same twins who judged its parent and count the paired shift
    (the proof, 2026-10-27). Runs automatically after a remake unless it was switched off; this
    starts it by hand, or again."""
    await get_owned_session(session_id, user, db)
    img = await _owned_image(session_id, image_id, db)
    if (img.status or "ready") != "ready":
        raise HTTPException(409, "This image is not ready yet.")
    if ((img.brief or {}).get("retest") or {}).get("status") == "running":
        raise HTTPException(409, "A re-test is already running on this image.")
    from app.services.measurement import visual_proof
    pid = await visual_proof.start_retest(image_id)
    if not pid:
        raise HTTPException(409, "Nothing to pair with: this image was not remade from a run the population answered.")
    background_tasks.add_task(visual_proof.run_retest, image_id, pid)
    await db.refresh(img)
    return images_mod.payload(img)


@router.post("/{session_id}/images/propose")
async def propose_next(session_id: str, body: ProposeNextRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """From a finished Visuals run to the next version (step 4): the agent reads the whole run — what
    most said, what few said that still matters, the verdict split — and proposes which image to
    build on, the changes (headline first, then the hard-hitting ones) with who said each and how
    many, what to keep, and what should move. Nothing is made until /{image_id}/remake is called
    with the proposal."""
    await get_owned_session(session_id, user, db)
    probe = await db.get(Probe, body.probe_id)
    if not probe or probe.session_id != session_id:
        raise HTTPException(404, "Run not found")
    if probe.status != "complete" or not (probe.aggregates or {}).get("n"):
        raise HTTPException(409, "That run has not finished — there is nothing to read yet.")
    images = await visual_gen.images_for_probe(session_id, probe)
    if not images:
        raise HTTPException(409, "That run did not show any image that is still in the session.")
    mode = "pro" if body.mode == "pro" else "fast"
    try:
        return await visual_gen.propose_next(session_id=session_id, probe=probe, images=images, model=get_settings().agent_model(mode), base_id=body.base_image_id)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/{session_id}/images/{image_id}/propose")
async def propose_change(session_id: str, image_id: str, body: ProposeRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The agent reads a Visuals run on this image and proposes the next version built on it (step 3,
    now the step-4 planner with the base fixed): the changes, what to keep, why, and the twins whose
    words drove them. A run that showed this image among others counts. Nothing is made until /remake."""
    await get_owned_session(session_id, user, db)
    img = await _owned_image(session_id, image_id, db)
    probe = None
    if body.probe_id:
        probe = await db.get(Probe, body.probe_id)
        if not probe or probe.session_id != session_id:
            raise HTTPException(404, "Run not found")
    else:
        probe = await visual_gen.latest_visual_probe(session_id, image_id)
    if not probe:
        raise HTTPException(409, "Show this image to the population first — there is no Visuals run on it to read.")
    mode = "pro" if body.mode == "pro" else "fast"
    try:
        return await visual_gen.propose_change(row=img, probe=probe, model=get_settings().agent_model(mode))
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/{session_id}/images/{image_id}/read")
async def read_image(session_id: str, image_id: str, body: ModeRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """What the system sees on an uploaded image: its words, exactly, and the picture — stored as the
    image's layout so a remake starts from what is actually there."""
    await get_owned_session(session_id, user, db)
    img = await _owned_image(session_id, image_id, db)
    layout = await visual_gen.read_image(img, model=get_settings().agent_model("pro" if body.mode == "pro" else "fast"))
    img.layout = layout
    await db.commit()
    return {"layout": layout}


@router.post("/{session_id}/images/{image_id}/check")
async def check_image(session_id: str, image_id: str, body: ModeRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Run (or re-run) the keep-list check on this image and store the result."""
    await get_owned_session(session_id, user, db)
    img = await _owned_image(session_id, image_id, db)
    if (img.status or "ready") != "ready":
        raise HTTPException(409, "This image is not ready yet.")
    result = await visual_gen.recheck(img, model=get_settings().agent_model("pro" if body.mode == "pro" else "fast"))
    img.check_result = result
    await db.commit()
    return result


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
    children = (await db.execute(select(SessionImage.id).where(SessionImage.parent_id == image_id))).scalars().all()
    if children:
        raise HTTPException(409, f"{len(children)} remake{'s' if len(children) != 1 else ''} came from this image. Delete those first.")
    await db.delete(img)
    await db.commit()
    return {"deleted": image_id}
