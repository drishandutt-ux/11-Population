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
_inflight: dict[str, "asyncio.Future"] = {}


def normalise(tier: Optional[str]) -> str:
    return tier if tier in TIERS else "fast"


def clamp(model: Optional[str]) -> str:
    """No session tier to apply: keep Haiku or Sonnet, anything else becomes Sonnet."""
    m = (model or "").lower()
    if not m or any(f in m for f in _FORBIDDEN) or not ("haiku" in m or "sonnet" in m):
        return SONNET
    return model


def enforce(model: Optional[str], tier: Optional[str]) -> str:
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
    task = _inflight.get(session_id)
    if task is None:
        task = asyncio.ensure_future(asyncio.wait_for(_read_tier(session_id), timeout=8))
        _inflight[session_id] = task
        task.add_done_callback(lambda _t: _inflight.pop(session_id, None))
    try:
        tier = await asyncio.shield(task)
    except Exception as e:  # noqa: BLE001 — a failed lookup must not fail the call; last known tier, else Fast
        print(f"[model_policy] tier lookup failed for {session_id}: {type(e).__name__}: {e}")
        return hit[0] if hit else "fast"
    if tier is None:
        return None
    remember(session_id, tier)
    return normalise(tier)


def sync_model(requested: Optional[str] = None) -> str:
    """For the synchronous Vision calls: the current session's tier model when known, else the
    requested model clamped (Haiku when none is named)."""
    from app.core.monitoring import current_session_id
    tier = cached_tier(current_session_id.get())
    return enforce(requested or HAIKU, tier)
