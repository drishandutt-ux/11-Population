"""Which Claude model a call may use (2026-10-23).

Each session carries a model tier, chosen on the main page:

  fast → Haiku for EVERY LLM call made for that session
  pro  → Sonnet for every call

Callers across the codebase still name a model (and many pass a per-button "pro"); none of that
decides anything any more. `tracked_messages_create` and the two synchronous Vision paths pass
the requested model through `enforce()`, which swaps it for the session's tier model. A call
with no session (shared kits, playbooks, admin tools) keeps its requested model, clamped:

Opus (and any model above Sonnet) is never allowed — not by a caller, not by an env override.
The tier models are fixed here rather than read from MODEL_* env vars, because an env override
is exactly how Opus reached production.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"

TIERS = ("fast", "pro")
TIER_MODEL = {"fast": HAIKU, "pro": SONNET}

_FORBIDDEN = ("opus", "fable", "mythos")
_TTL = 30.0
_cache: dict[str, tuple[str, float]] = {}
_inflight: dict[tuple[int, str], "asyncio.Future"] = {}   # keyed by (event loop, session)


def normalise(tier: Optional[str]) -> str:
    return tier if tier in TIERS else "fast"


def clamp(model: Optional[str]) -> str:
    """No session tier to apply: keep Haiku or Sonnet, anything else becomes Sonnet."""
    m = (model or "").lower()
    if not m or any(f in m for f in _FORBIDDEN) or not ("haiku" in m or "sonnet" in m):
        return SONNET
    return model


#: Mechanical work — runs on Haiku even in a Pro (Advanced) session, because the larger model
#: does not change what the analyst sees (2026-10-23). Matched on the call's label (exact, or
#: the part before ":retry" / ":repair"). Kept OFF this list on purpose — the tier decides them:
#: twin voices and answers (spawn:*, post, chat, probe:<instrument>, validation_answers,
#: agent_builder), the plan of segments (population_plan, population_segment, playbook_fit),
#: and analyst-facing writing (report, lab_brief, lever_why, rule_draft, journey_stages,
#: forms_generate, forms_chat, llm_paper).
ALWAYS_HAIKU = frozenset({
    # research: searching, reading and judging pages
    "search", "research_plan", "research_frame", "research_pdf", "research_judge_page",
    "research_judge_web", "research_judge_social", "research_brief", "research_recommend",
    "llm_classify",
    # knowledge graph, ontology and scoping: extraction and tagging
    "kg_extract", "kg_query", "ontology_classify", "ontology_relate", "scoping_tag",
    "scope_check", "lay_layer",
    # sampling frame and statistics: finding and reading published figures
    "population_detect", "population_triage", "population_facts", "population_facets",
    "population_questions", "population_targets", "population_dials", "population_refine",
    "population_frame_dims", "population_frame_search", "population_frame_target",
    "population_frame_estimate", "population_frame_sizing", "population_workout",
    "population_workout_plan", "dynamic_dials", "playbook_parse",
    # coding and classifying answers the twins already gave
    "probe:themes", "journey:movability", "opinions", "validation_items", "validation_judge",
    # setup chat and parsing pasted forms
    "lab_configure", "forms_import",
    # describing images and video frames for ingestion
    "doc_vision", "youtube_vision",
})


def _base_label(label: Optional[str]) -> str:
    return (label or "").split(":retry")[0].split(":repair")[0]


def enforce(model: Optional[str], tier: Optional[str], label: Optional[str] = None) -> str:
    if _base_label(label) in ALWAYS_HAIKU:
        return HAIKU
    return TIER_MODEL[tier] if tier in TIERS else clamp(model)


def remember(session_id: str, tier: str) -> None:
    _cache[session_id] = (normalise(tier), time.monotonic())


def cached_tier(session_id: Optional[str]) -> Optional[str]:
    """The tier if it was read in the last 30 s — for synchronous callers that cannot await."""
    if not session_id:
        return None
    hit = _cache.get(session_id)
    return hit[0] if hit else None


async def _read_tier(session_id: str) -> Optional[str]:
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.session import AnalysisSession
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(AnalysisSession.model_tier).where(AnalysisSession.id == session_id))).scalar_one_or_none()


async def session_tier(session_id: Optional[str]) -> Optional[str]:
    """The session's tier (cached 30 s), or None when there is no session or it cannot be read.

    One lookup per session at a time: a phase of 48 parallel twin calls shares a single read
    rather than each taking a pool connection while its caller may already hold one."""
    if not session_id:
        return None
    hit = _cache.get(session_id)
    if hit and time.monotonic() - hit[1] < _TTL:
        return hit[0]
    # A pending read is shared only within its own event loop: a future from another (or a closed)
    # loop can never be awaited here and would hang the caller.
    key = (id(asyncio.get_running_loop()), session_id)
    task = _inflight.get(key)
    if task is None or task.get_loop() is not asyncio.get_running_loop():
        task = asyncio.ensure_future(asyncio.wait_for(_read_tier(session_id), timeout=8))
        _inflight[key] = task
        task.add_done_callback(lambda _t: _inflight.pop(key, None))
    try:
        tier = await asyncio.shield(task)
    except Exception as e:  # noqa: BLE001 — a failed lookup must not fail the call; last known tier, else Fast
        print(f"[model_policy] tier lookup failed for {session_id}: {type(e).__name__}: {e}")
        return hit[0] if hit else "fast"
    if tier is None:
        return None
    remember(session_id, tier)
    return normalise(tier)


def sync_model(requested: Optional[str] = None, label: Optional[str] = None) -> str:
    """For the synchronous Vision calls: the current session's tier model when known, else the
    requested model clamped (Haiku when none is named)."""
    from app.core.monitoring import current_session_id
    tier = cached_tier(current_session_id.get())
    return enforce(requested or HAIKU, tier, label)
