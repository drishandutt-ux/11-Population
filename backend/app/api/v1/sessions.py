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
from app.core.auth import AuthUser, get_current_user, get_owned_session, owns

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: str
    query: str
    auto_research: bool = True                 # start web + Reddit research immediately
    research_sources: Optional[list[str]] = None   # default ["web", "reddit"]


class SessionResponse(BaseModel):
    id: str
    title: str
    query: str
    status: str
    agent_count: int
    created_at: datetime
    updated_at: datetime
    owner_email: Optional[str] = None   # only populated for admins listing ?scope=all
    is_mine: Optional[bool] = None

    class Config:
        from_attributes = True


@router.post("", response_model=SessionResponse)
async def create_session(body: CreateSessionRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = AnalysisSession(
        id=str(uuid.uuid4()),
        user_id=None if user.is_dev else user.id,
        title=body.title,
        query=body.query,
        status=SessionStatus.CREATED,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    if body.auto_research:
        from app.services.evidence.loop import start_research
        try:
            await start_research(session.id, session.query, body.research_sources)
        except Exception as e:  # noqa: BLE001 — research must never block session creation
            print(f"[sessions] auto-research failed to start for {session.id}: {type(e).__name__}: {e}")
    return session


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    scope: str = "mine",
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The caller's sessions. Admins may pass `?scope=all` to see every user's, with owner_email."""
    q = select(AnalysisSession).order_by(AnalysisSession.created_at.desc()).limit(200)
    everyone = scope == "all" and user.is_admin
    if not user.is_dev and not everyone:
        q = q.where(AnalysisSession.user_id == user.id)
    rows = (await db.execute(q)).scalars().all()
    if not everyone:
        return rows
    from app.models.profile import Profile
    owners = {str(p.id).replace("-", ""): p.email for p in (await db.execute(select(Profile))).scalars().all()}
    return [
        {
            "id": r.id, "title": r.title, "query": r.query, "status": r.status, "agent_count": r.agent_count,
            "created_at": r.created_at, "updated_at": r.updated_at,
            "owner_email": owners.get(str(r.user_id).replace("-", ""), None) if r.user_id else None,
            "is_mine": str(r.user_id).replace("-", "") == str(user.id).replace("-", "") if r.user_id else False,
        }
        for r in rows
    ]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await get_owned_session(session_id, user, db)
    return session


@router.get("/{session_id}/kg")
async def get_kg(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.knowledge_graph.lightrag_service import get_kg_data, get_lightrag
    await get_owned_session(session_id, user, db)
    await get_lightrag(session_id)  # DB-backed: warm the cache before the sync read
    return get_kg_data(session_id)


@router.get("/{session_id}/kg/entity/{entity_name}")
async def get_kg_entity(session_id: str, entity_name: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.knowledge_graph.lightrag_service import get_entity_details, get_lightrag
    await get_owned_session(session_id, user, db)
    await get_lightrag(session_id)
    return get_entity_details(session_id, entity_name)


@router.get("/{session_id}/posts")
async def get_session_posts(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.simulation.thread_manager import get_posts
    await get_owned_session(session_id, user, db)
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
async def get_session_dials(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Population-level aggregation of the 112 dials across this session's agents.

    Powers the psychographic dashboard: per-dial distributions, group means,
    a market-research scorecard, and a stance x dial heatmap.
    """
    from app.services.agents.dial_analytics import aggregate_dials

    session = await get_owned_session(session_id, user, db)

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
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a crisp one-liner verdict per agent (batched Claude calls; persisted on the agent).

    Always HTTP 200. Response: {"opinions": {agent_id: verdict}, "generated": n, "total": m, "error": str|null}.
    `opinions` also carries previously persisted verdicts, so the sidebar never regresses.
    """
    from app.services.simulation.opinions import generate_opinions

    session = await get_owned_session(session_id, user, db)

    return await generate_opinions(db, session_id, session.query, body.agent_ids if body else None)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await get_owned_session(session_id, user, db)
    await db.delete(session)
    await db.commit()
    from app.services.knowledge_graph.lightrag_service import forget
    forget(session_id)


class ApplyPresetRequest(BaseModel):
    preset_id: str


@router.post("/{session_id}/apply-preset")
async def apply_preset(
    session_id: str,
    body: ApplyPresetRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.preset import AgentPreset

    session = await get_owned_session(session_id, user, db)

    preset_result = await db.execute(select(AgentPreset).where(AgentPreset.id == body.preset_id))
    preset = preset_result.scalar_one_or_none()
    if not preset or not owns(preset, user):
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
