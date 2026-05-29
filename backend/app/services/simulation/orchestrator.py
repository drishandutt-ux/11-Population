import asyncio
import random
import traceback
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
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


async def _session_status(session_id: str) -> "str | None":
    """Quick DB read — returns current status string, or None if session missing."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AnalysisSession.status).where(AnalysisSession.id == session_id)
        )
        row = result.scalar_one_or_none()
        return row.value if row else None


async def _agent_post_task(
    agent,
    session_id: str,
    query: str,
    thread_context: str,
    kg_context: str,
    posts: list,
    round_num: int,
    agents_by_id: dict,
) -> bool:
    """
    Generate and publish one agent's contribution for this round.
    Returns True if a post was published, False if skipped (paused/stopped).
    """
    # Pre-generation status check
    status = await _session_status(session_id)
    if status in ("paused", "complete") or status is None:
        return False

    try:
        action = _choose_action(posts, agent)

        reply_to = None
        parent_id = None
        post_type = PostType.COMMENT

        if action == "like" and posts:
            content_posts = [p for p in posts if p.content]
            if content_posts:
                target = random.choice(content_posts[-20:] if len(content_posts) > 20 else content_posts)
                async with AsyncSessionLocal() as db:
                    updated = await add_like(db, target.id)
                await publish(session_channel(session_id), {
                    "type": "like_added",
                    "post_id": target.id,
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "new_likes": updated.likes if updated else target.likes + 1,
                })
            return True

        if action in ("reply", "debate") and posts:
            content_posts = [p for p in posts if p.content and p.agent_id != agent.id]
            if content_posts:
                target_post = random.choice(content_posts[-15:] if len(content_posts) > 15 else content_posts)
                parent_id = target_post.id
                reply_to = target_post.content
                post_type = PostType.DEBATE if action == "debate" else PostType.REPLY

        content = await generate_post(
            agent=agent,
            query=query,
            thread_context=thread_context,
            kg_context=kg_context,
            post_type=action,
            reply_to_content=reply_to,
        )

        # Post-generation status check — discard if paused mid-call
        status = await _session_status(session_id)
        if status in ("paused", "complete") or status is None:
            print(f"[orchestrator] Discarding post from {agent.name} — status={status}")
            return False

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

        # Graph update runs in background — never blocks posting
        asyncio.create_task(
            update_graph_from_post(session_id, agent.name, agent.role, content)
        )

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
            "agent": {
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
            },
        })
        print(f"[orchestrator] Round {round_num}: {agent.name} posted ({post_type.value})")
        return True

    except Exception as e:
        print(f"[orchestrator] Agent {agent.name} failed: {e}")
        traceback.print_exc()
        return False


async def run_simulation(session_id: str, max_rounds: int):
    print(f"[orchestrator] Starting simulation for {session_id}, {max_rounds} rounds")
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
        print(f"[orchestrator] {len(db_agents)} agents loaded")

        await publish(session_channel(session_id), {
            "type": "simulation_started",
            "agent_count": len(db_agents),
        })

        # Pre-load KG (fast — just reads JSON cache)
        await get_lightrag(session_id)

        for round_num in range(max_rounds):
            # ── Round-boundary status check ──────────────────────────────────
            status = await _session_status(session_id)
            if status in ("paused", "complete") or status is None:
                print(f"[orchestrator] Stopping at round {round_num}: status={status}")
                break

            async with AsyncSessionLocal() as db:
                posts = await get_posts(db, session_id)

            # ── KG context: instant string from cache, no Claude call ─────────
            kg_context = get_kg_context_string(session_id, max_entities=60, max_relations=40)
            if not kg_context.strip() or "none" in kg_context.lower():
                kg_context = f"Topic under discussion: {query}"

            thread_context = build_thread_context(posts, agents_by_id)

            # ── Choose agents for this round (weighted by energy) ────────────
            energies = [a.energy for a in db_agents]
            total = sum(energies)
            weights = [e / total for e in energies]
            # Larger batch — more posts per round, all run in parallel
            batch_size = min(max(3, len(db_agents) // 2), len(db_agents))
            agents_this_round = random.choices(db_agents, weights=weights, k=batch_size)

            # ── Run all agents in this round CONCURRENTLY ────────────────────
            tasks = [
                _agent_post_task(
                    agent=agent,
                    session_id=session_id,
                    query=query,
                    thread_context=thread_context,
                    kg_context=kg_context,
                    posts=posts,
                    round_num=round_num,
                    agents_by_id=agents_by_id,
                )
                for agent in agents_this_round
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # If any task came back False (paused/stopped), end the round loop
            stopped = any(r is False for r in results if not isinstance(r, Exception))
            if stopped:
                break

            await asyncio.sleep(0.3)

        # Only mark complete if still in simulating state
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
                "message": f"Simulation complete after {max_rounds} rounds.",
            })
            print(f"[orchestrator] Simulation {session_id} complete")
        else:
            print(f"[orchestrator] Simulation {session_id} ended with status={final_status}")

    except Exception as e:
        print(f"[orchestrator] FATAL ERROR: {e}")
        traceback.print_exc()


def _choose_action(posts, agent) -> str:
    if not posts:
        return "comment"
    r = random.random()
    if r < 0.12 * agent.energy:
        return "debate"
    elif r < 0.38:
        return "reply"
    elif r < 0.52:
        return "like"
    else:
        return "comment"
