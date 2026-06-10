import asyncio
import traceback
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.session import AnalysisSession, SessionStatus
from app.models.agent import SpawnedAgent

router = APIRouter(prefix="/sessions", tags=["simulation"])


class SpawnAgentsRequest(BaseModel):
    count: int = 15
    mode: str = "fast"          # "fast" = sample the pre-built bank (instant); "pro" = LLM-curated (Sonnet)
    profile_query: str = ""
    direct_pct: int = 33
    indirect_pct: int = 33
    neutral_pct: int = 34
    doc_context: str = ""
    humanity: int = 0           # 0 = expert/analytical, 100 = fully human/emotional
    humanity_coverage: int = 0  # % of the population the humanity setting applies to


class SimulateRequest(BaseModel):
    intensity: int = 1          # activity level: 1 = one post/agent; each step adds like/debate/reply
    mode: str = "fast"          # "fast" = Haiku posts; "pro" = Sonnet posts


_MAX_AGENTS = 1000


@router.post("/{session_id}/spawn-agents")
async def spawn_agents(
    session_id: str,
    body: SpawnAgentsRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Clear any existing agents for this session
    result2 = await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == session_id))
    for a in result2.scalars().all():
        await db.delete(a)
    await db.commit()

    session.status = SessionStatus.READY
    session.agent_count = 0
    await db.commit()

    count = max(1, min(_MAX_AGENTS, body.count))
    mode = "pro" if body.mode == "pro" else "fast"
    background_tasks.add_task(
        _spawn_agents_task,
        session_id, count, mode,
        body.profile_query, body.direct_pct, body.indirect_pct, body.neutral_pct, body.doc_context,
        body.humanity, body.humanity_coverage,
    )
    return {"status": "spawning", "count": count, "mode": mode}


def _agent_payload(p) -> dict:
    return {
        "id": p.id, "name": p.name, "age": p.age, "role": p.role,
        "background": p.background, "stance": p.stance, "correlation": p.correlation,
        "personality": p.personality, "debate_style": p.debate_style,
        "energy": p.energy, "avatar_color": p.avatar_color,
        "dials": p.dials or {}, "humanity": getattr(p, "humanity", 0) or 0,
    }


async def _spawn_agents_task(
    session_id: str,
    count: int,
    mode: str = "fast",
    profile_query: str = "",
    direct_pct: int = 33,
    indirect_pct: int = 33,
    neutral_pct: int = 34,
    doc_context: str = "",
    humanity: int = 0,
    humanity_coverage: int = 0,
):
    from app.core.database import AsyncSessionLocal
    from app.core.redis_client import publish, session_channel
    from app.models.agent import SpawnedAgent

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
            session = result.scalar_one_or_none()
            if not session:
                return
            query = session.query

        # ── Build the population ────────────────────────────────────────────
        if mode == "pro":
            from app.services.agents.agent_factory import generate_agents
            profiles = await generate_agents(
                session_id, query, count,
                profile_query=profile_query,
                direct_pct=direct_pct, indirect_pct=indirect_pct, neutral_pct=neutral_pct,
                doc_context=doc_context,
                humanity=humanity, humanity_coverage=humanity_coverage,
                mode="pro",
            )
        else:
            # FAST: sample the pre-built bank — instant, no LLM call
            from app.services.agents.seed_bank import sample_bank
            profiles = sample_bank(
                session_id, count,
                direct_pct=direct_pct, indirect_pct=indirect_pct, neutral_pct=neutral_pct,
                humanity=humanity, humanity_coverage=humanity_coverage,
            )

        if not profiles:
            raise RuntimeError("No agents were produced.")

        # ── Bulk insert (single transaction) ────────────────────────────────
        async with AsyncSessionLocal() as db:
            db.add_all([
                SpawnedAgent(
                    id=p.id, session_id=session_id, name=p.name, age=p.age, role=p.role,
                    background=p.background, stance=p.stance, correlation=p.correlation,
                    personality=p.personality, debate_style=p.debate_style, energy=p.energy,
                    avatar_color=p.avatar_color, dials=p.dials or {},
                    humanity=getattr(p, "humanity", 0) or 0,
                )
                for p in profiles
            ])
            result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
            session = result.scalar_one_or_none()
            if session:
                session.agent_count = len(profiles)
            await db.commit()

        # ── Stream to the UI in batches (one event per ~40 agents, not per agent) ──
        total = len(profiles)
        BATCH = 40
        for i in range(0, total, BATCH):
            chunk = profiles[i:i + BATCH]
            await publish(session_channel(session_id), {
                "type": "agents_spawned_batch",
                "agents": [_agent_payload(p) for p in chunk],
                "spawned": min(i + BATCH, total),
                "total": total,
            })
            await asyncio.sleep(0.02)

        await publish(session_channel(session_id), {"type": "agents_ready", "count": total})

    except Exception as e:
        print(f"[spawn_agents_task] ERROR: {e}")
        traceback.print_exc()
        from app.core.redis_client import publish, session_channel
        await publish(session_channel(session_id), {
            "type": "spawn_error",
            "error": str(e),
        })


@router.post("/{session_id}/simulate/start")
async def start_simulation(
    session_id: str,
    body: SimulateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Block if ingestion is still running
    if session.status == SessionStatus.INGESTING:
        raise HTTPException(status_code=409, detail="ingesting")

    # Check agents exist
    result2 = await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == session_id))
    agents = result2.scalars().all()
    if not agents:
        raise HTTPException(status_code=400, detail="No agents spawned yet. Spawn agents first.")

    session.status = SessionStatus.SIMULATING
    await db.commit()

    intensity = max(1, min(20, body.intensity))
    mode = "pro" if body.mode == "pro" else "fast"
    from app.services.simulation.orchestrator import run_simulation
    background_tasks.add_task(run_simulation, session_id, intensity, mode)
    return {"status": "simulating", "session_id": session_id, "intensity": intensity, "mode": mode}


@router.post("/{session_id}/simulate/pause")
async def pause_simulation(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.status = SessionStatus.PAUSED
    await db.commit()
    return {"status": "paused"}


@router.post("/{session_id}/simulate/stop")
async def stop_simulation(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.status = SessionStatus.COMPLETE
    await db.commit()
    return {"status": "complete"}
