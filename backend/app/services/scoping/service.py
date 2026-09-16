"""Scoped retrieval as the rest of the app uses it.

  is_scoped(session)                  — has the session been tagged?
  context_for_agent(session, agent,…) — the knowledge block for one twin, with routes, logged
  state(session)                      — what the Scoping view shows
  preview(session, agent)             — what one twin sees and what is hidden from it, and why
  set_policy(session, rules)          — a new policy version

One in-process bundle per session (units + ontology + active rules) and one retrieval per
distinct (profile, query) — a thousand twins with a dozen profiles cost a dozen retrievals.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select, func

from .engine import knowledge_block, retrieve
from .profiles import profile_for, profile_hash
from .registry import DIMENSIONS, validate_rules

_bundles: dict[str, dict] = {}


def forget(session_id: str) -> None:
    _bundles.pop(session_id, None)


def _unit_dict(u) -> dict:
    facets = dict(u.facets or {})
    facets.setdefault("project", u.session_id)
    return {"id": u.id, "text": u.text, "source_ref": u.source_ref, "provenance_class": u.provenance_class,
            "trust_tier": u.trust_tier, "facets": facets, "snapshot_id": u.snapshot_id}


async def _load_bundle(session_id: str) -> Optional[dict]:
    if session_id in _bundles:
        return _bundles[session_id]
    from app.core.database import AsyncSessionLocal
    from app.models.scoping import KnowledgeUnit, ScopePolicy
    from app.services.knowledge_graph import ontology as onto_svc

    try:
        async with AsyncSessionLocal() as db:
            units = (await db.execute(select(KnowledgeUnit).where(KnowledgeUnit.session_id == session_id).order_by(KnowledgeUnit.created_at))).scalars().all()
            if not units:
                return None
            pol = (await db.execute(select(ScopePolicy).where(ScopePolicy.session_id == session_id, ScopePolicy.layer == "session")
                                    .order_by(ScopePolicy.version.desc()))).scalars().first()
        onto = await onto_svc.load(session_id)
    except Exception as e:  # noqa: BLE001 — a missing table or a DB hiccup means "not scoped", never a failed turn
        print(f"[scoping] bundle unavailable for {session_id}: {type(e).__name__}: {e}")
        return None
    bundle = {
        "units": [_unit_dict(u) for u in units],
        "snapshot_id": units[0].snapshot_id,
        "onto": onto,
        "rules": list(pol.rules or []) if pol else [],
        "policy_version": pol.version if pol else 0,
        "cache": {},
    }
    _bundles[session_id] = bundle
    return bundle


async def is_scoped(session_id: str) -> bool:
    return (await _load_bundle(session_id)) is not None


async def _log(session_id: str, agent_id: str, purpose: str, snapshot_id: str, version: int, results: list[dict]) -> None:
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.scoping import Retrieval
        async with AsyncSessionLocal() as db:
            db.add(Retrieval(session_id=session_id, agent_id=agent_id, purpose=purpose, snapshot_id=snapshot_id, policy_version=version,
                             unit_ids=[r["unit"]["id"] for r in results], routes=[r["route"] for r in results]))
            await db.commit()
    except Exception as e:  # noqa: BLE001 — logging never blocks a turn
        print(f"[scoping] retrieval log failed: {type(e).__name__}: {e}")


async def context_for_agent(session_id: str, agent: Any, query: str, *, purpose: str = "post", limit: int = 14, log: bool = True) -> Optional[str]:
    """The twin's knowledge block, or None when the session is not scoped (caller falls back)."""
    bundle = await _load_bundle(session_id)
    if bundle is None:
        return None
    profile = profile_for(agent, bundle["onto"])
    key = (profile_hash(profile), query, limit)
    res = bundle["cache"].get(key)
    if res is None:
        res = retrieve(bundle["units"], bundle["onto"], profile, bundle["rules"], query, limit=limit)
        bundle["cache"][key] = res
    if log:
        asyncio.create_task(_log(session_id, getattr(agent, "id", ""), purpose, bundle["snapshot_id"], bundle["policy_version"], res["visible"]))
    if not res["visible"]:
        return f"Topic under discussion: {query}\n(You have not come across specifics on this yourself.)"
    return knowledge_block(res["visible"])


def _facet_counts(units: list[dict]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for u in units:
        for k, v in (u.get("facets") or {}).items():
            vals = v if isinstance(v, list) else [v]
            for x in vals:
                counts.setdefault(k, {})[str(x)] = counts.setdefault(k, {}).get(str(x), 0) + 1
        counts.setdefault("provenance", {})[u["provenance_class"]] = counts.setdefault("provenance", {}).get(u["provenance_class"], 0) + 1
    return counts


async def state(session_id: str) -> dict:
    from app.services.knowledge_graph.lightrag_service import get_lightrag, _load_kg
    await get_lightrag(session_id)
    kg = _load_kg(session_id)
    chunk_count = len([c for c in kg.get("chunks", []) if isinstance(c, str) and c.strip()])
    bundle = await _load_bundle(session_id)
    base = {"dimensions": DIMENSIONS, "chunk_count": chunk_count, "tagged": bundle is not None}
    if bundle is None:
        return {**base, "units": [], "unit_count": 0, "counts": {}, "policy": None, "snapshot_id": None, "stale": False}
    units = bundle["units"]
    return {
        **base,
        "units": units[:300],
        "unit_count": len(units),
        "counts": _facet_counts(units),
        "policy": {"version": bundle["policy_version"], "rules": bundle["rules"]},
        "snapshot_id": bundle["snapshot_id"],
        "stale": len(units) != chunk_count,
    }


async def preview(session_id: str, agent: Any, query: str, *, limit: int = 14) -> dict:
    bundle = await _load_bundle(session_id)
    if bundle is None:
        return {"tagged": False, "profile": None, "visible": [], "hidden": [], "block": ""}
    profile = profile_for(agent, bundle["onto"])
    res = retrieve(bundle["units"], bundle["onto"], profile, bundle["rules"], query, limit=limit)
    return {
        "tagged": True,
        "profile": profile,
        "visible": [{"unit": r["unit"], "score": round(r["score"], 2), "route": r["route"], "applied": r["applied"]} for r in res["visible"]],
        "visible_total": res["visible_total"],
        "hidden": [{"unit": h["unit"], "failed": h["failed"]} for h in res["hidden"][:60]],
        "hidden_total": len(res["hidden"]),
        "block": knowledge_block(res["visible"]),
        "policy_version": bundle["policy_version"],
        "snapshot_id": bundle["snapshot_id"],
    }


async def set_policy(session_id: str, rules: list, note: str = "") -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.scoping import ScopePolicy
    clean = validate_rules(rules)
    async with AsyncSessionLocal() as db:
        current = (await db.execute(select(func.max(ScopePolicy.version)).where(ScopePolicy.session_id == session_id, ScopePolicy.layer == "session"))).scalar() or 0
        db.add(ScopePolicy(session_id=session_id, layer="session", version=current + 1, rules=clean, note=note[:200], created_at=datetime.utcnow()))
        await db.commit()
    forget(session_id)
    return {"version": current + 1, "rules": clean}


async def retrieval_log(session_id: str, agent_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    from app.core.database import AsyncSessionLocal
    from app.models.scoping import Retrieval
    async with AsyncSessionLocal() as db:
        q = select(Retrieval).where(Retrieval.session_id == session_id)
        if agent_id:
            q = q.where(Retrieval.agent_id == agent_id)
        rows = (await db.execute(q.order_by(Retrieval.created_at.desc()).limit(limit))).scalars().all()
    return [{"id": r.id, "agent_id": r.agent_id, "purpose": r.purpose, "snapshot_id": r.snapshot_id, "policy_version": r.policy_version,
             "unit_ids": r.unit_ids, "routes": r.routes, "created_at": r.created_at.isoformat()} for r in rows]
