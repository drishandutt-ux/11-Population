"""Forms API (2026-10-06): the Lab brief and the three ways to a questionnaire — import,
write-for-me and the brainstorm chat. The result of every path is a Survey spec; running it
is the ordinary `POST /sessions/{id}/probes` with `instrument: "survey"`."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, get_current_user, get_owned_session
from app.core.database import get_db
from app.services.measurement import forms as forms_svc
from app.services.measurement import lab_brief

router = APIRouter(tags=["forms"])


class BriefBuildRequest(BaseModel):
    mode: str = "pro"
    force: bool = False


class ImportTextRequest(BaseModel):
    text: str
    mode: str = "pro"


class GenerateRequest(BaseModel):
    goal: Optional[str] = ""
    length: str = "standard"            # short | standard | deep
    existing: Optional[dict[str, Any]] = None
    mode: str = "pro"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = []
    form: Optional[dict[str, Any]] = None
    mode: str = "pro"


@router.get("/sessions/{session_id}/lab/brief")
async def get_brief(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The stored Lab brief with `stale` (the session has moved on since it was written)."""
    await get_owned_session(session_id, user, db)
    return await lab_brief.get(session_id)


@router.post("/sessions/{session_id}/lab/brief")
async def build_brief(session_id: str, body: BriefBuildRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """(Re)write the brief from everything on file. A brief that is still current is returned
    as it is unless `force`."""
    await get_owned_session(session_id, user, db)
    current = await lab_brief.get(session_id)
    if current.get("brief") and not current.get("stale") and not body.force and current.get("status") == "ready":
        return current
    try:
        return await lab_brief.build(session_id, mode=body.mode)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not write the brief: {type(e).__name__}: {str(e)[:160]}")


@router.post("/sessions/{session_id}/forms/import")
async def import_text(session_id: str, body: ImportTextRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Pasted questionnaire text → typed questions."""
    await get_owned_session(session_id, user, db)
    if not (body.text or "").strip():
        raise HTTPException(400, "Paste the questionnaire first.")
    return await forms_svc.import_form(session_id, body.text, mode=body.mode)


@router.post("/sessions/{session_id}/forms/import/file")
async def import_file(session_id: str, file: UploadFile = File(...), user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """An uploaded questionnaire (.pdf, .docx, .txt, .md, .csv …) → typed questions."""
    await get_owned_session(session_id, user, db)
    from app.services.ingestion.document_parser import parse_document
    content = await file.read()
    try:
        text = parse_document(content, file.filename or "")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not read {file.filename or 'the file'}: {type(e).__name__}")
    if not (text or "").strip():
        raise HTTPException(400, f"Nothing readable in {file.filename or 'the file'}.")
    out = await forms_svc.import_form(session_id, text, mode="pro")
    out["filename"] = file.filename or ""
    return out


@router.post("/sessions/{session_id}/forms/generate")
async def generate(session_id: str, body: GenerateRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Write the form from the brief and a one-line goal."""
    await get_owned_session(session_id, user, db)
    try:
        return await forms_svc.generate_form(session_id, goal=body.goal or "", length=body.length, existing=body.existing, mode=body.mode)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not write the form: {type(e).__name__}: {str(e)[:160]}")


@router.post("/sessions/{session_id}/forms/chat")
async def chat(session_id: str, body: ChatRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """One turn of the brainstorm. Stateless: the client sends the history and the form on
    screen; the reply may carry a changed form."""
    await get_owned_session(session_id, user, db)
    try:
        return await forms_svc.chat(session_id, [m.model_dump() for m in body.messages], body.form, mode=body.mode)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"The chat failed: {type(e).__name__}: {str(e)[:160]}")
