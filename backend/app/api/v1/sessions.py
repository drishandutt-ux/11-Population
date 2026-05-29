import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.session import AnalysisSession, SessionStatus
from app.models.agent import SpawnedAgent
from app.models.post import SimulationPost

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: str
    query: str


class SessionResponse(BaseModel):
    id: str
    title: str
    query: str
    status: str
    agent_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.post("", response_model=SessionResponse)
async def create_session(body: CreateSessionRequest, db: AsyncSession = Depends(get_db)):
    session = AnalysisSession(
        id=str(uuid.uuid4()),
        title=body.title,
        query=body.query,
        status=SessionStatus.CREATED,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("", response_model=list[SessionResponse])
async def list_sessions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AnalysisSession).order_by(AnalysisSession.created_at.desc()).limit(50)
    )
    return result.scalars().all()


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/{session_id}/kg")
async def get_kg(session_id: str):
    from app.services.knowledge_graph.lightrag_service import get_kg_data
    return get_kg_data(session_id)


@router.get("/{session_id}/kg/entity/{entity_name}")
async def get_kg_entity(session_id: str, entity_name: str):
    from app.services.knowledge_graph.lightrag_service import get_entity_details
    return get_entity_details(session_id, entity_name)


@router.get("/{session_id}/posts")
async def get_session_posts(session_id: str, db: AsyncSession = Depends(get_db)):
    from app.services.simulation.thread_manager import get_posts
    posts = await get_posts(db, session_id)
    return [
        {
            "id": p.id,
            "agent_id": p.agent_id,
            "type": p.type.value,
            "content": p.content,
            "parent_id": p.parent_id,
            "likes": p.likes,
            "round_num": p.round_num,
        }
        for p in posts
    ]


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.delete(session)
    await db.commit()
