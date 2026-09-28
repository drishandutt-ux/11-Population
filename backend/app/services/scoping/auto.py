"""Scoping as a pipeline step, not a side view (brief L1-04, wired end to end).

Until now the knowledge was tagged only when someone pressed *Tag* on the Graph tab, so a
population was written, a debate run and a probe answered against one shared block unless the
analyst happened to visit that view first. This module makes scoping automatic and puts it in
the path of everything that creates or consults a twin:

  * `ensure_tagged`  — tag the session's knowledge if it never was, or if the graph has grown
                       since (stale); single-flight per session; announces itself over the
                       websocket (`scoping_started` / `scoping_complete` / `scoping_error`).
                       Called when ingestion or research finishes (`schedule`, detached), and
                       awaited before a Studio build writes personas, before a debate starts and
                       before a probe runs — so no path is left that runs unscoped.
  * `context_for_segment` — what a twin of THIS plan segment could plausibly know: an exposure
                       profile derived from the segment (place, role, register) and the scoped
                       retrieval for it, so the persona writer grounds a twin in what it can
                       reach rather than in a summary of the whole graph.
  * `annotate_agents` — after a spawn, a build, a preset load or a (re)tag: every twin records
                       what it was written from and can see now (`spawned_agents.knowledge`:
                       snapshot, visible / total units, routes, profile basis), so the Agents tab
                       can show "sees 14 of 38" without leaving the tab.
  * `coverage`       — that record for the whole roster, for the Agents tab.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Optional

from app.core import database as dbm

# Locks and tasks are kept per event loop: a lock made under one loop cannot be awaited under
# another (tests and one-off scripts spin up fresh loops), and the server has exactly one.
_locks: dict[tuple[int, str], asyncio.Lock] = {}
_tasks: dict[tuple[int, str], asyncio.Task] = {}


def _key(session_id: str) -> tuple[int, str]:
    try:
        return id(asyncio.get_running_loop()), session_id
    except RuntimeError:
        return 0, session_id


def _lock(session_id: str) -> asyncio.Lock:
    k = _key(session_id)
    if k not in _locks:
        _locks[k] = asyncio.Lock()
    return _locks[k]


async def _emit(session_id: str, event: dict) -> None:
    try:
        from app.core.redis_client import publish, session_channel
        await publish(session_channel(session_id), event)
    except Exception as e:  # noqa: BLE001 — a missed event never blocks the pipeline
        print(f"[scoping.auto] emit failed: {type(e).__name__}: {e}")


_NOTHING = {"tagged": False, "stale": False, "chunk_count": 0, "unit_count": 0, "snapshot_id": None}


async def needs_tagging(session_id: str, *, warm: bool = True) -> tuple[bool, dict]:
    """(should tag, state): tag when never tagged, or when the graph has more chunks than units.
    The chunk count is read from the process cache; `warm` loads the graph from the database
    first (ingestion, research, a build and a debate warm it; a probe's own context builder
    already has, so it asks with warm=False and never opens a second database path)."""
    from . import service
    from app.services.knowledge_graph.lightrag_service import _kg_cache, get_lightrag
    if warm:
        await get_lightrag(session_id)
    kg = _kg_cache.get(session_id)
    if not kg or not [c for c in kg.get("chunks", []) if isinstance(c, str) and c.strip()]:
        return False, dict(_NOTHING)
    st = await service.state(session_id)
    if not st.get("chunk_count"):
        return False, st
    return (not st.get("tagged")) or bool(st.get("stale")), st


async def ensure_tagged(session_id: str, query: str, *, reason: str = "", force: bool = False, model: Optional[str] = None, warm: bool = True) -> dict:
    """Tag the session's knowledge when it is untagged or stale. Returns the scoping state (the
    current one when nothing had to be done). Never raises: a failed tag is reported over the
    websocket and the caller carries on unscoped, exactly as before."""
    from . import service, tagger
    async with _lock(session_id):
        should, st = await needs_tagging(session_id, warm=warm)
        if not should and not force:
            return st
        if not st.get("chunk_count"):
            return st
        await _emit(session_id, {"type": "scoping_started", "reason": reason, "chunks": st.get("chunk_count", 0), "stale": bool(st.get("stale"))})
        try:
            new_state = await tagger.tag_session(session_id, query, model=model)
        except Exception as e:  # noqa: BLE001
            print(f"[scoping.auto] tagging failed ({reason}): {type(e).__name__}: {e}")
            await _emit(session_id, {"type": "scoping_error", "reason": reason, "error": str(e)[:200]})
            return st
        await _emit(session_id, {"type": "scoping_complete", "reason": reason, "unit_count": new_state.get("unit_count", 0),
                                 "snapshot_id": new_state.get("snapshot_id"), "counts": new_state.get("counts", {})})
        # The knowledge changed, so what every twin can see changed with it.
        asyncio.create_task(annotate_agents(session_id, query, reason=f"retag:{reason}"))
        return new_state


def schedule(session_id: str, query: str, *, reason: str = "") -> None:
    """Fire-and-forget `ensure_tagged`; a second trigger while one runs is dropped (the lock
    inside would only queue it, and the running one already sees the latest chunks)."""
    k = _key(session_id)
    t = _tasks.get(k)
    if t and not t.done():
        return
    _tasks[k] = asyncio.create_task(ensure_tagged(session_id, query, reason=reason))


# ── what a twin of a segment could know ──────────────────────────────────────

def segment_seed(seg: dict, *, role: str = "", region: str = "") -> Any:
    """A stand-in twin for a plan segment, shaped the way `profiles.profile_for` reads an agent:
    role, background, region, humanity band and segment name."""
    d = seg.get("demographics") or {}
    regions = [r for r in (d.get("regions") or []) if r]
    occs = [o for o in (d.get("occupations") or []) if o]
    band = seg.get("register") or seg.get("humanity_band") or ""
    humanity = seg.get("humanity") if isinstance(seg.get("humanity"), int) else {"expert": 10, "tempered": 40, "reactive": 80}.get(str(band), 50)
    return SimpleNamespace(
        id="", role=role or (occs[0] if occs else seg.get("role") or seg.get("name") or ""),
        background=str(seg.get("description") or seg.get("summary") or "")[:400],
        demographics={"region": region or (regions[0] if regions else "")},
        humanity=humanity, segment=seg.get("name") or "",
    )


async def context_for_segment(session_id: str, seg: dict, query: str, *, role: str = "", region: str = "", limit: int = 14) -> Optional[str]:
    """The scoped knowledge block for a twin of this segment (and place / job when given), or
    None when the session is not scoped — the caller keeps the shared summary."""
    from . import service
    seed = segment_seed(seg, role=role, region=region)
    block = await service.context_for_agent(session_id, seed, query, purpose="write", limit=limit, log=False)
    if not block:
        return None
    return ("WHAT PEOPLE LIKE THIS WOULD ACTUALLY KNOW (scoped to their place, role and register — where they know each thing from is in brackets; "
            "write them so they know this and not more):\n" + block)


# ── what each twin was written from / can see ────────────────────────────────

async def knowledge_for_agent(session_id: str, agent: Any, query: str, *, written_from: str = "") -> Optional[dict]:
    """The scoping record stored on a twin: snapshot, visible / total, routes, the profile's
    basis. None when the session is not scoped."""
    from . import service
    res = await service.retrieval_for_agent(session_id, agent, query, purpose="annotate", log=False)
    if res is None:
        return None
    profile, out, snapshot_id, version = res
    visible = out.get("visible") or []
    return {
        "snapshot_id": snapshot_id, "policy_version": version,
        "visible": int(out.get("visible_total") or len(visible)), "total": int(out.get("visible_total") or len(visible)) + len(out.get("hidden") or []),
        "unit_ids": [r["unit"]["id"] for r in visible][:40], "routes": sorted({r["route"] for r in visible})[:12],
        "provenance": _prov_mix(visible), "profile": {k: v for k, v in (profile.get("values") or {}).items() if v}, "basis": profile.get("basis") or {},
        "written_from": written_from or "scoped", "at": datetime.utcnow().isoformat(),
    }


def _prov_mix(visible: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in visible:
        k = str((r.get("unit") or {}).get("provenance_class") or "")
        if k:
            out[k] = out.get(k, 0) + 1
    return out


async def session_query(session_id: str) -> str:
    from app.models.session import AnalysisSession
    async with dbm.AsyncSessionLocal() as db:
        sess = await db.get(AnalysisSession, session_id)
    return (sess.query if sess else "") or ""


async def annotate_agents(session_id: str, query: Optional[str] = None, *, reason: str = "", agent_ids: Optional[list[str]] = None) -> int:
    """Store the scoping record on every twin (or the given ones). Returns how many were
    written. Quiet when the session is not scoped."""
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified
    from app.models.agent import SpawnedAgent
    from . import service
    if not await service.is_scoped(session_id):
        return 0
    if query is None:
        query = await session_query(session_id)
    try:
        async with dbm.AsyncSessionLocal() as db:
            q = select(SpawnedAgent).where(SpawnedAgent.session_id == session_id)
            if agent_ids:
                q = q.where(SpawnedAgent.id.in_(agent_ids))
            agents = (await db.execute(q)).scalars().all()
            n = 0
            for a in agents:
                prior = a.knowledge if isinstance(getattr(a, "knowledge", None), dict) else {}
                rec = await knowledge_for_agent(session_id, a, query, written_from=prior.get("written_from") or ("scoped" if prior else "shared"))
                if rec is None:
                    continue
                a.knowledge = rec
                flag_modified(a, "knowledge")
                n += 1
            await db.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[scoping.auto] annotate failed ({reason}): {type(e).__name__}: {e}")
        return 0
    await _emit(session_id, {"type": "scoping_annotated", "reason": reason, "count": n})
    return n


async def coverage(session_id: str) -> dict:
    """The roster's scoping records, for the Agents tab."""
    from sqlalchemy import select
    from app.models.agent import SpawnedAgent
    from . import service
    st = await service.state(session_id)
    async with dbm.AsyncSessionLocal() as db:
        agents = (await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == session_id))).scalars().all()
    per = {}
    for a in agents:
        k = getattr(a, "knowledge", None)
        if isinstance(k, dict):
            per[a.id] = {"visible": k.get("visible", 0), "total": k.get("total", 0), "snapshot_id": k.get("snapshot_id"),
                         "written_from": k.get("written_from"), "routes": k.get("routes") or [], "provenance": k.get("provenance") or {}}
    return {"tagged": bool(st.get("tagged")), "stale": bool(st.get("stale")), "unit_count": st.get("unit_count", 0), "chunk_count": st.get("chunk_count", 0),
            "snapshot_id": st.get("snapshot_id"), "agents": per, "annotated": len(per), "total": len(agents)}
