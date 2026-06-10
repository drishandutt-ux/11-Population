import asyncio
import random
import traceback
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.core.config import get_settings
from app.core.redis_client import publish, session_channel
from app.models.session import AnalysisSession, SessionStatus
from app.models.agent import SpawnedAgent
from app.models.post import PostType
from app.services.agents.agent_runner import generate_post
from app.services.knowledge_graph.lightrag_service import get_lightrag, get_kg_context_string
from app.services.knowledge_graph.graph_updater import update_graph_from_post
from app.services.simulation.thread_manager import (
    build_thread_context,
    create_post,
    add_like,
    get_posts,
)

# Activity ladder — each "intensity" level adds one bundled action PER AGENT.
# L1: every agent posts once. L2: +1 reaction (like). L3: +1 debate. L4: +1 reply.
# Beyond L4 we keep adding substantive turns (alternating debate/reply).
_LADDER = ["comment", "like", "debate", "reply"]


def _build_phases(intensity: int) -> list[str]:
    intensity = max(1, int(intensity))
    phases: list[str] = []
    for k in range(intensity):
        if k < len(_LADDER):
            phases.append(_LADDER[k])
        else:
            phases.append("debate" if (k - len(_LADDER)) % 2 == 0 else "reply")
    return phases


async def _session_status(session_id: str) -> "str | None":
    """Quick DB read — returns current status string, or None if session missing."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AnalysisSession.status).where(AnalysisSession.id == session_id)
        )
        row = result.scalar_one_or_none()
        return row.value if row else None


class _StatusWatcher:
    """Polls session status once a second and exposes an in-memory `stopped` flag, so the
    per-agent tasks (thousands of them at 1000-agent scale) never hit the DB themselves."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.stopped = False
        self._task: "asyncio.Task | None" = None

    async def _loop(self):
        try:
            while not self.stopped:
                status = await _session_status(self.session_id)
                if status in ("paused", "complete") or status is None:
                    self.stopped = True
                    return
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return

    def start(self):
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


async def _kg_update(sem: asyncio.Semaphore, session_id: str, name: str, role: str, content: str):
    async with sem:
        try:
            await update_graph_from_post(session_id, name, role, content)
        except Exception:
            pass


def _agent_event_payload(agent) -> dict:
    return {
        "id": agent.id,
        "name": agent.name,
        "role": agent.role,
        "stance": agent.stance,
        "avatar_color": agent.avatar_color,
        "personality": agent.personality,
        "background": agent.background,
        "age": agent.age,
        "correlation": agent.correlation,
        "debate_style": agent.debate_style,
        "energy": agent.energy,
    }


async def _agent_action(
    agent,
    action: str,
    *,
    session_id: str,
    query: str,
    thread_context: str,
    kg_context: str,
    posts: list,
    round_num: int,
    mode: str,
    watcher: _StatusWatcher,
    kg_sem: asyncio.Semaphore,
    kg_sample: float,
):
    if watcher.stopped:
        return

    # ── Likes are cheap (no LLM): bump a recent post by someone else ──────────
    if action == "like":
        candidates = [p for p in posts if p.content and p.agent_id != agent.id]
        if not candidates:
            return
        target = random.choice(candidates[-30:] if len(candidates) > 30 else candidates)
        async with AsyncSessionLocal() as db:
            updated = await add_like(db, target.id)
        await publish(session_channel(session_id), {
            "type": "like_added",
            "post_id": target.id,
            "agent_id": agent.id,
            "agent_name": agent.name,
            "new_likes": updated.likes if updated else target.likes + 1,
        })
        return

    # ── Comment / debate / reply are LLM posts ───────────────────────────────
    parent_id = None
    reply_to = None
    post_type = PostType.COMMENT
    effective_action = action

    if action in ("reply", "debate"):
        candidates = [p for p in posts if p.content and p.agent_id != agent.id]
        if candidates:
            target_post = random.choice(candidates[-25:] if len(candidates) > 25 else candidates)
            parent_id = target_post.id
            reply_to = target_post.content
            post_type = PostType.DEBATE if action == "debate" else PostType.REPLY
        else:
            effective_action = "comment"  # nothing to engage with yet → top-level

    try:
        content = await generate_post(
            agent=agent,
            query=query,
            thread_context=thread_context,
            kg_context=kg_context,
            post_type=effective_action,
            reply_to_content=reply_to,
            mode=mode,
        )
    except Exception as e:
        print(f"[orchestrator] {agent.name} generate failed: {type(e).__name__}: {e}")
        return

    if watcher.stopped:
        return

    async with AsyncSessionLocal() as db:
        new_post = await create_post(
            db=db,
            session_id=session_id,
            agent_id=agent.id,
            post_type=post_type,
            content=content,
            parent_id=parent_id,
            round_num=round_num,
        )

    # KG enrichment: sampled + concurrency-bounded so it never saturates the API mid-run
    if kg_sample > 0 and random.random() < kg_sample:
        asyncio.create_task(_kg_update(kg_sem, session_id, agent.name, agent.role, content))

    await publish(session_channel(session_id), {
        "type": "post_created",
        "post": {
            "id": new_post.id,
            "agent_id": agent.id,
            "type": post_type.value,
            "content": content,
            "parent_id": parent_id,
            "likes": 0,
            "round_num": round_num,
        },
        "agent": _agent_event_payload(agent),
    })


async def run_simulation(session_id: str, intensity: int = 1, mode: str = "fast"):
    settings = get_settings()
    phases = _build_phases(intensity)
    concurrency = max(1, settings.sim_concurrency(mode))
    kg_sem = asyncio.Semaphore(max(1, settings.kg_sim_concurrency))
    print(f"[orchestrator] start {session_id}: mode={mode} intensity={intensity} "
          f"phases={phases} concurrency={concurrency}")

    watcher = _StatusWatcher(session_id)
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
            session = result.scalar_one_or_none()
            if not session:
                print(f"[orchestrator] Session {session_id} not found")
                return
            query = session.query

            result2 = await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == session_id))
            db_agents = list(result2.scalars().all())

        if not db_agents:
            print(f"[orchestrator] No agents for session {session_id}")
            return

        agents_by_id = {a.id: a for a in db_agents}
        # Adaptive KG enrichment: small/Pro runs feed EVERY post back into the graph;
        # only large populations throttle (so 1000 agents don't fire 1000 extractions/phase).
        kg_sample = min(1.0, settings.kg_sim_max_updates / max(1, len(db_agents)))
        print(f"[orchestrator] {len(db_agents)} agents loaded (kg_sample={kg_sample:.2f})")

        await publish(session_channel(session_id), {
            "type": "simulation_started",
            "agent_count": len(db_agents),
        })

        await get_lightrag(session_id)  # warm the KG cache
        watcher.start()

        for round_num, action in enumerate(phases):
            if watcher.stopped:
                print(f"[orchestrator] stopping before phase {round_num} ({action})")
                break

            # Snapshot thread + KG once per phase (every agent in the phase shares it)
            async with AsyncSessionLocal() as db:
                posts = await get_posts(db, session_id)
            kg_context = get_kg_context_string(session_id, max_entities=60, max_relations=40)
            if not kg_context.strip() or "none" in kg_context.lower():
                kg_context = f"Topic under discussion: {query}"
            thread_context = build_thread_context(posts, agents_by_id)

            sem = asyncio.Semaphore(concurrency)

            async def run_one(agent):
                if watcher.stopped:
                    return
                async with sem:
                    try:
                        await _agent_action(
                            agent, action,
                            session_id=session_id, query=query,
                            thread_context=thread_context, kg_context=kg_context,
                            posts=posts, round_num=round_num, mode=mode,
                            watcher=watcher, kg_sem=kg_sem, kg_sample=kg_sample,
                        )
                    except Exception as e:
                        print(f"[orchestrator] {agent.name} action failed: {e}")

            # Every agent acts once this phase → guaranteed coverage
            await asyncio.gather(*[run_one(a) for a in db_agents], return_exceptions=True)
            print(f"[orchestrator] phase {round_num} ({action}) done for {len(db_agents)} agents")

        final_status = await _session_status(session_id)
        if final_status == "simulating":
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
                session = result.scalar_one_or_none()
                if session:
                    session.status = SessionStatus.COMPLETE
                    await db.commit()
            await publish(session_channel(session_id), {
                "type": "simulation_complete",
                "message": f"Simulation complete — {len(phases)} activity level(s) across {len(db_agents)} agents.",
            })
            print(f"[orchestrator] Simulation {session_id} complete")
        else:
            print(f"[orchestrator] Simulation {session_id} ended with status={final_status}")

    except Exception as e:
        print(f"[orchestrator] FATAL ERROR: {e}")
        traceback.print_exc()
    finally:
        await watcher.stop()
