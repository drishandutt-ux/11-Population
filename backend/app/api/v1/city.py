"""11 Minds City API (2026-11-05): the brainstorm chat that drafts the city plan. Building the
city is the ordinary `POST /sessions/{id}/probes` with `instrument: "city"` and the plan as the
spec; the 3D town runs in the browser from the answers."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, get_current_user, get_owned_session
from app.core.database import get_db
from app.services.measurement import city as city_svc

router = APIRouter(tags=["city"])


class ChatMessage(BaseModel):
    role: str
    content: str


class CityChatRequest(BaseModel):
    messages: list[ChatMessage] = []
    plan: Optional[dict[str, Any]] = None
    mode: str = "pro"


@router.post("/sessions/{session_id}/city/chat")
async def city_chat(session_id: str, body: CityChatRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """One turn of the city brainstorm. Stateless: the client sends the history and the plan
    so far; the reply carries the plan as it now stands, `ready` and `missing`."""
    await get_owned_session(session_id, user, db)
    try:
        return await city_svc.chat(session_id, [m.model_dump() for m in body.messages], body.plan, mode=body.mode)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"The chat failed: {type(e).__name__}: {str(e)[:160]}")


@router.get("/city/vocabulary")
async def city_vocabulary(user: AuthUser = Depends(get_current_user)):
    """The building and lever kinds the city knows how to draw and run."""
    return {"buildings": list(city_svc.BUILDING_KINDS), "levers": list(city_svc.LEVER_KINDS),
            "characters": list(city_svc.CITY_CHARACTERS), "sizes": list(city_svc.CITY_SIZES)}
