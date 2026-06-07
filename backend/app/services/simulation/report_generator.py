from app.core.config import get_settings
from app.services.knowledge_graph.lightrag_service import get_lightrag, query_rag
from app.services.simulation.thread_manager import get_posts, build_thread_context
from app.models.agent import SpawnedAgent
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import anthropic


async def answer_report_query(
    session_id: str,
    original_query: str,
    question: str,
    db: AsyncSession,
) -> tuple[str, str]:
    settings = get_settings()

    # ── 1. Knowledge graph context ──────────────────────────────────────────
    rag = await get_lightrag(session_id)
    kg_context = await query_rag(rag, question, mode="hybrid")

    # ── 2. Full simulation transcript ───────────────────────────────────────
    posts = await get_posts(db, session_id)

    agents_result = await db.execute(
        select(SpawnedAgent).where(SpawnedAgent.session_id == session_id)
    )
    agents_list = agents_result.scalars().all()
    agents_map = {a.id: a for a in agents_list}

    thread_text = build_thread_context(posts, agents_map)

    # ── 3. Agent profile summary ────────────────────────────────────────────
    agent_profiles = "\n".join(
        f"- {a.name} ({a.role}, age {a.age}): stance={a.stance} | {a.background[:300]}"
        for a in agents_list
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    system = (
        "You are a senior analyst who has observed a full multi-agent simulation. "
        "You have access to the complete knowledge graph AND the full verbatim "
        "simulation transcript. Your answers must cite specific agents by name, "
        "quote or paraphrase their actual positions, and reference concrete data "
        "from both the ingested documents and the debate."
    )

    prompt = f"""Original analysis query: {original_query}

== KNOWLEDGE GRAPH CONTEXT ==
{kg_context}

== AGENT PROFILES ({len(agents_list)} agents) ==
{agent_profiles}

== FULL SIMULATION TRANSCRIPT ({len(posts)} posts) ==
{thread_text}

== REPORT REQUEST ==
{question}

Use ALL of the above — the full transcript, every agent's actual statements, and the knowledge graph — to produce your answer. Reference specific agents by name. Do not say "some agents" — name them. Extract every relevant metric or data point that appeared in the discussion."""

    try:
        response = await client.messages.create(
            model=settings.model_orchestration,
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = response.content[0].text.strip()
    except Exception as e:
        from app.core.llm_errors import friendly_llm_error
        print(f"[report_generator] LLM call failed for session {session_id}: {type(e).__name__}: {e}")
        answer = friendly_llm_error(e)

    sources = (
        f"Knowledge graph + {len(posts)} simulation posts "
        f"from {len(agents_list)} agents (session {session_id})"
    )
    return answer, sources
