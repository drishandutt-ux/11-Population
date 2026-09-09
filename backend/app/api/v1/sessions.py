import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.session import AnalysisSession, SessionStatus
from app.models.agent import SpawnedAgent, AgentStance
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


@router.get("/{session_id}/dials")
async def get_session_dials(session_id: str, db: AsyncSession = Depends(get_db)):
    """Population-level aggregation of the 112 dials across this session's agents.

    Powers the psychographic dashboard: per-dial distributions, group means,
    a market-research scorecard, and a stance x dial heatmap.
    """
    from app.services.agents.dial_analytics import aggregate_dials

    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    agents_result = await db.execute(
        select(SpawnedAgent).where(SpawnedAgent.session_id == session_id)
    )
    agents = agents_result.scalars().all()

    agg = aggregate_dials(agents)
    agg["session_id"] = session_id
    agg["query"] = session.query
    return agg


class OpinionsRequest(BaseModel):
    agent_ids: Optional[list[str]] = None   # regenerate only these agents (default: everyone who has posted)


@router.post("/{session_id}/opinions")
async def generate_agent_opinions(
    session_id: str,
    body: Optional[OpinionsRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """Generate a crisp one-liner verdict per agent (batched Claude calls; persisted on the agent).

    Always HTTP 200. Response: {"opinions": {agent_id: verdict}, "generated": n, "total": m, "error": str|null}.
    `opinions` also carries previously persisted verdicts, so the sidebar never regresses.
    """
    from app.services.simulation.opinions import generate_opinions

    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return await generate_opinions(db, session_id, session.query, body.agent_ids if body else None)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.delete(session)
    await db.commit()


class ApplyPresetRequest(BaseModel):
    preset_id: str


@router.post("/{session_id}/apply-preset")
async def apply_preset(
    session_id: str,
    body: ApplyPresetRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    from app.models.preset import AgentPreset

    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    preset_result = await db.execute(select(AgentPreset).where(AgentPreset.id == body.preset_id))
    preset = preset_result.scalar_one_or_none()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    # Clear existing agents for this session
    agents_result = await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == session_id))
    for a in agents_result.scalars().all():
        await db.delete(a)

    session.status = SessionStatus.READY
    session.agent_count = 0
    await db.commit()

    background_tasks.add_task(_apply_preset_task, session_id, list(preset.agents))
    return {"status": "loading", "agent_count": len(preset.agents)}


async def _apply_preset_task(session_id: str, agent_profiles: list[dict]):
    import asyncio
    from app.core.database import AsyncSessionLocal
    from app.core.redis_client import publish, session_channel

    try:
        async with AsyncSessionLocal() as db:
            total = len(agent_profiles)
            for i, p in enumerate(agent_profiles):
                agent_id = str(uuid.uuid4())
                agent_row = SpawnedAgent(
                    id=agent_id,
                    session_id=session_id,
                    name=p["name"],
                    age=p["age"],
                    role=p["role"],
                    background=p["background"],
                    stance=AgentStance(p["stance"]),
                    correlation=p["correlation"],
                    personality=p["personality"],
                    debate_style=p["debate_style"],
                    energy=p["energy"],
                    avatar_color=p["avatar_color"],
                    dials=p.get("dials") or {},
                )
                db.add(agent_row)
                await db.commit()

                await publish(session_channel(session_id), {
                    "type": "agent_spawned",
                    "agent": {
                        "id": agent_id,
                        "name": p["name"],
                        "age": p["age"],
                        "role": p["role"],
                        "background": p["background"],
                        "stance": p["stance"],
                        "correlation": p["correlation"],
                        "personality": p["personality"],
                        "debate_style": p["debate_style"],
                        "energy": p["energy"],
                        "avatar_color": p["avatar_color"],
                        "dials": p.get("dials") or {},
                    },
                    "index": i,
                    "total": total,
                })
                await asyncio.sleep(0.08)

            result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
            session = result.scalar_one_or_none()
            if session:
                session.agent_count = total
                await db.commit()

        await publish(session_channel(session_id), {"type": "agents_ready", "count": total})

    except Exception as e:
        import traceback
        print(f"[apply_preset_task] ERROR: {e}")
        traceback.print_exc()
        from app.core.redis_client import publish, session_channel
        await publish(session_channel(session_id), {"type": "spawn_error", "error": str(e)})
