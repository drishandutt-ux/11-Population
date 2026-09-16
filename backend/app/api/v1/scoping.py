"""Scoped retrieval: tag the session's knowledge, read the state, preview what one twin sees,
and version the session policy. All owner-scoped."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, get_current_user, get_owned_session
from app.core.database import get_db
from app.models.agent import SpawnedAgent
from app.services.evidence.llm import LlmError
from app.services.scoping import service, tagger

router = APIRouter(prefix="/sessions", tags=["scoping"])


class PolicyBody(BaseModel):
    rules: list
    note: Optional[str] = ""


class ExposureBody(BaseModel):
    exposure: Optional[dict] = None


@router.get("/{session_id}/scoping")
async def get_scoping(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    return await service.state(session_id)


@router.post("/{session_id}/scoping/tag")
async def tag_scoping(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await get_owned_session(session_id, user, db)
    try:
        return await tagger.tag_session(session_id, session.query)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LlmError as e:
        raise HTTPException(status_code=502, detail=f"The model could not tag the knowledge: {e}")


@router.get("/{session_id}/scoping/preview")
async def preview_scoping(session_id: str, agent_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await get_owned_session(session_id, user, db)
    agent = (await db.execute(select(SpawnedAgent).where(SpawnedAgent.id == agent_id, SpawnedAgent.session_id == session_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found in this session")
    return await service.preview(session_id, agent, session.query)


@router.put("/{session_id}/scoping/policy")
async def put_policy(session_id: str, body: PolicyBody, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    try:
        return await service.set_policy(session_id, body.rules, body.note or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{session_id}/scoping/agents/{agent_id}/exposure")
async def put_exposure(session_id: str, agent_id: str, body: ExposureBody, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Override a twin's exposure profile (any subset of dimensions); null clears it."""
    await get_owned_session(session_id, user, db)
    agent = (await db.execute(select(SpawnedAgent).where(SpawnedAgent.id == agent_id, SpawnedAgent.session_id == session_id))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found in this session")
    agent.exposure = body.exposure
    await db.commit()
    service.forget(session_id)
    return {"agent_id": agent_id, "exposure": agent.exposure}


@router.get("/{session_id}/scoping/retrievals")
async def get_retrievals(session_id: str, agent_id: Optional[str] = None, limit: int = 50, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    return {"retrievals": await service.retrieval_log(session_id, agent_id, min(max(limit, 1), 500))}
