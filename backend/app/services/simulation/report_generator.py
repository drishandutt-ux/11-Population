from dataclasses import dataclass, field
from typing import Any, Optional
from app.core.config import get_settings
from app.core.monitoring import tracked_messages_create
from app.services.knowledge_graph.lightrag_service import get_lightrag, query_rag
from app.services.simulation.thread_manager import get_posts
from app.services.simulation import citations
from app.services.simulation import records as records_mod
from app.services.simulation import structure as structure_mod
from app.services.simulation import figures as figures_mod
from app.models.agent import SpawnedAgent
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import anthropic


@dataclass
class ReportContext:
    """Everything one report call is written from — shared by the report proper and Ask-Report."""
    kg_context: str
    posts: list = field(default_factory=list)
    agents: list = field(default_factory=list)
    handles: Any = None
    thread_text: str = ""
    roster_text: str = ""
    frame_text: str = ""
    frame: Optional[dict] = None
    records: list = field(default_factory=list)
    records_text: str = ""
    record_handles: dict = field(default_factory=dict)
    # L6-03: the source-figure ledger — typed statistics and evidence items, numbered F1… / E1…
    ledger: dict = field(default_factory=dict)
    facts_text: str = ""
    items_text: str = ""
    figure_handles: dict = field(default_factory=dict)
    unsourced: list = field(default_factory=list)


async def _context(session_id: str, question: str, db: AsyncSession, records: Optional[list[dict]]) -> ReportContext:
    if records is None:
        try:
            records = await records_mod.records_for_session(session_id)
        except Exception as e:  # noqa: BLE001
            print(f"[report] records unavailable: {type(e).__name__}: {e}")
            records = []
    records_text, record_handles = records_mod.records_block(records)

    ledger: dict = {}
    try:
        ledger = await figures_mod.load_ledger(session_id)
    except Exception as e:  # noqa: BLE001
        print(f"[report] source-figure ledger unavailable: {type(e).__name__}: {e}")
    facts_text, items_text, figure_handles = figures_mod.ledger_block(ledger)

    # ── 1. Knowledge graph context ──────────────────────────────────────────
    rag = await get_lightrag(session_id)
    kg_context = await query_rag(rag, question, mode="hybrid")

    # ── 2. Full simulation transcript ───────────────────────────────────────
    posts = await get_posts(db, session_id)
    agents_list = (await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == session_id))).scalars().all()
    agents_map = {a.id: a for a in agents_list}

    # ── 3. Roster and transcript, both handled so every claim can be traced back
    #        to the twin (and the line) it came from — brief L3-03.
    handles = citations.build_handles(agents_list, posts)
    thread_text = citations.transcript_block(posts, agents_map, handles)
    roster_text = citations.roster_block(agents_list, handles)

    # ── 3b. The sampling frame the population was matched to (Studio) ──────
    frame_text = "No sampling frame: the population was not matched to published distributions."
    frame: Optional[dict] = None
    try:
        from app.services.population.builder import latest_build
        from app.services.population import frame as frame_mod
        bld = await latest_build(session_id)
        if bld and bld.frame:
            frame = bld.frame
            rep = (bld.frame or {}).get("report")
            frame_text = frame_mod.summary_line(rep)
            lines = []
            for d in (bld.frame.get("dimensions") or []):
                tg = (bld.frame.get("targets") or {}).get(d["key"]) or {}
                lines.append(f"- {d['label']}: {tg.get('status', 'missing')}" + (f" — {tg.get('source')} ({tg.get('geography') or ''} {tg.get('year') or ''})".rstrip() if tg.get("source") else ""))
            if lines:
                frame_text += "\n" + "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        print(f"[report] frame summary unavailable: {type(e).__name__}: {e}")

    return ReportContext(kg_context=kg_context, posts=posts, agents=agents_list, handles=handles, thread_text=thread_text,
                         roster_text=roster_text, frame_text=frame_text, frame=frame, records=records,
                         records_text=records_text, record_handles=record_handles, ledger=ledger,
                         facts_text=facts_text, items_text=items_text, figure_handles=figure_handles)


async def _call(session_id: str, label: str, system: str, prompt: str, ctx: ReportContext) -> str:
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await tracked_messages_create(
            client, session_id=session_id, label=label, model=settings.model_orchestration, max_tokens=4000,
            system=system, messages=[{"role": "user", "content": prompt}],
        )
        answer = response.content[0].text.strip()
        # Record handles first (a dangling [[R9]] is dropped), then twin handles → stable ids,
        # then any name typed anyway becomes a citation: the name a reader sees is always read
        # back from the agent row, never retyped by the model.
        answer = records_mod.resolve_handles(answer, ctx.record_handles)
        answer = figures_mod.resolve_handles(answer, ctx.figure_handles)
        answer = citations.resolve(answer, ctx.handles)
        answer = citations.repair_names(answer, ctx.agents)
        # Last: any number left with no citation in its sentence is the model's own — flagged.
        answer, ctx.unsourced = figures_mod.mark_unsourced(answer)
        return answer
    except Exception as e:
        from app.core.llm_errors import friendly_llm_error
        print(f"[report_generator] LLM call failed for session {session_id}: {type(e).__name__}: {e}")
        return friendly_llm_error(e)


def _sources(ctx: ReportContext, answer: str, session_id: str) -> str:
    cited = citations.cited_ids(answer)
    cited_records = records_mod.cited_record_ids(answer)
    facts, items = figures_mod.cited_ids(answer)
    return (
        f"Knowledge graph + {len(ctx.posts)} simulation posts from {len(ctx.agents)} agents"
        + (f", {len(cited)} cited by name" if cited else "")
        + (f", {len(cited_records)} outcome record(s) cited" if cited_records else "")
        + (f", {len(facts) + len(items)} source figure(s) cited" if facts or items else "")
        + (f", {len(ctx.unsourced)} unsourced figure(s) flagged" if ctx.unsourced else "")
        + f" (session {session_id})"
    )


_BASE_SYSTEM = (
    "You are a senior analyst who has observed a full multi-agent simulation. "
    "You have access to the complete knowledge graph AND the full verbatim "
    "simulation transcript. Your answers must attribute every position to the "
    "specific twin who held it, quote or paraphrase their actual words, and "
    "reference concrete data from both the ingested documents and the debate.\n\n"
    + citations.CITATION_RULES
    + "\n\n" + records_mod.FIGURE_RULES
    + "\n\n" + figures_mod.SOURCE_FIGURE_RULES
)


def _prompt(original_query: str, ctx: ReportContext, extra_blocks: str, request: str) -> str:
    return f"""Original analysis query: {original_query}

== KNOWLEDGE GRAPH CONTEXT ==
{ctx.kg_context}

== POPULATION FRAME (how representative the panel is — state this under SOURCE MATERIALS, including any model-estimated distribution) ==
{ctx.frame_text}

== OUTCOME RECORDS ({len(ctx.records)} computed from the twins' answers — the ONLY figures about this population you may state; cite as [[R1]]) ==
{ctx.records_text}

== SOURCE FIGURES ({len(ctx.ledger.get('facts') or [])} typed statistics read from the material — cite as [[F1]]) ==
{ctx.facts_text}

== SOURCE DOCUMENTS ({len(ctx.ledger.get('items') or [])} evidence items with their provenance class — cite as [[E1]] for a figure or claim read in one) ==
{ctx.items_text}
{extra_blocks}
== POPULATION ROSTER ({len(ctx.agents)} twins — cite by the handle in brackets, never by name) ==
{ctx.roster_text}

== FULL SIMULATION TRANSCRIPT ({len(ctx.posts)} posts — each line starts [post handle · twin handle name | role]) ==
{ctx.thread_text}

== REPORT REQUEST ==
{request}

Use ALL of the above — the full transcript, every twin's actual statements, and the knowledge graph — to produce your answer. Attribute every position with a handle citation ([[A7]], or [[A7#P12]] for a specific statement) so a reader can click back to the twin and the line. Extract every relevant metric or data point that appeared in the discussion."""


async def answer_report_query(
    session_id: str,
    original_query: str,
    question: str,
    db: AsyncSession,
    records: Optional[list[dict]] = None,
) -> tuple[str, str]:
    """Ask-Report: a free question answered from the same context as the report. `records`
    (brief L6-01): the session's outcome records, numbered R1 … Rn; None = load them (without
    running the verdict probe)."""
    ctx = await _context(session_id, question, db, records)
    answer = await _call(session_id, "report", _BASE_SYSTEM, _prompt(original_query, ctx, "", question), ctx)
    return answer, _sources(ctx, answer, session_id)


async def generate_report(
    session_id: str,
    original_query: str,
    db: AsyncSession,
    records: list[dict],
    headline: Optional[dict],
    request: Optional[str] = None,
) -> tuple[str, str, dict]:
    """The report proper (brief L6-02): the five-section briefing, with every part that can be
    computed handed to the model as data and stored as `structure` beside the prose — the
    headline record's confidence band, the evidence by class, the verdict probe's positions
    and named dissent, and the cited records' caveats."""
    request = (request or "").strip() or structure_mod.REPORT_PROMPT
    ctx = await _context(session_id, original_query, db, records)

    positions: list[dict] = []
    evidence: list[dict] = []
    try:
        positions = await structure_mod.load_positions((headline or {}).get("id"))
    except Exception as e:  # noqa: BLE001
        print(f"[report] positions unavailable: {type(e).__name__}: {e}")
    try:
        evidence = await structure_mod.load_evidence(session_id)
    except Exception as e:  # noqa: BLE001
        print(f"[report] evidence summary unavailable: {type(e).__name__}: {e}")

    names = {a.id: a.name for a in ctx.agents}
    extra = (
        f"\n== EVIDENCE BY CLASS (what grounds this population — SOURCE MATERIALS follows this order) ==\n"
        f"{structure_mod.evidence_block(evidence)}\n\n"
        f"== POSITIONS (every twin's verdict on the question, from the headline record — the named dissent under DISCUSSION comes from here) ==\n"
        f"{structure_mod.positions_block(positions, ctx.handles.handle_of_agent, names)}\n"
    )
    system = _BASE_SYSTEM + "\n\n" + structure_mod.STRUCTURE_RULES
    answer = await _call(session_id, "report", system, _prompt(original_query, ctx, extra, request), ctx)
    answer, claimed = structure_mod.strip_confidence_line(answer)

    from app.services.population import frame as frame_mod
    frame_summary = structure_mod.frame_summary(ctx.frame, frame_mod.summary_line((ctx.frame or {}).get("report")))
    facts_cited, items_cited = figures_mod.cited_ids(answer)
    structure = structure_mod.build_structure(
        session_query=original_query, records=records, headline=headline, positions=positions, evidence=evidence,
        frame=frame_summary, cited_record_ids=records_mod.cited_record_ids(answer), claimed_band=claimed,
        figures={"facts_cited": facts_cited, "items_cited": items_cited, "unsourced": list(ctx.unsourced)},
    )
    return answer, _sources(ctx, answer, session_id), structure
