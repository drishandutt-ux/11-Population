"""Behaviour Lab API — run instruments against a population and read the results back."""
import io
import csv
import random
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, get_current_user, get_owned_session
from app.core.config import get_settings
from app.core.database import get_db
from app.models.agent import SpawnedAgent
from app.models.measurement import Probe, ProbeAnswer
from app.services.measurement import instruments, probe as probe_svc

router = APIRouter(tags=["measurement"])

# Rough per-agent cost of one probe answer, from the Pulse figures for today's runs
# (a probe is shorter than a post: ~700 in / ~110 out). Shown before the run, not billed.
_COST_PER_AGENT = {"fast": 0.0005, "pro": 0.004}


class ProbeRequest(BaseModel):
    instrument: str
    spec: dict[str, Any] = {}
    mode: str = "fast"                       # "fast" = Haiku, "pro" = Sonnet
    seed: Optional[int] = None
    agent_filter: Optional[dict[str, Any]] = None


def _instrument_payload(inst) -> dict:
    return {
        "key": inst.key,
        "label": inst.label,
        "description": inst.description,
        "question": inst.question,
        "chart": inst.chart,
        "stimulus_hint": inst.stimulus_hint,
        "spec_fields": list(inst.spec_fields),
        "schema_id": inst.schema_id(),
        "answer_schema": inst.answer_schema,
    }


def _probe_payload(p: Probe) -> dict:
    return {
        "id": p.id,
        "session_id": p.session_id,
        "instrument": p.instrument,
        "schema_id": p.schema_id,
        "spec": p.spec or {},
        "experiment_id": p.experiment_id,
        "variant_key": p.variant_key,
        "seed": p.seed,
        "model": p.model,
        "prompt_hash": p.prompt_hash,
        "status": p.status,
        "agent_count": p.agent_count,
        "answer_count": p.answer_count,
        "failed_count": p.failed_count,
        "aggregates": p.aggregates,
        "error": p.error,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "completed_at": p.completed_at.isoformat() if p.completed_at else None,
    }


@router.get("/lab/instruments")
async def list_instruments(user: AuthUser = Depends(get_current_user)):
    """The instrument library. The UI builds its picker from this, so a new instrument
    appears in the product the moment its module is registered."""
    return {"instruments": [_instrument_payload(i) for i in instruments.all_instruments()]}


@router.post("/sessions/{session_id}/probes/estimate")
async def estimate_probe(
    session_id: str,
    body: ProbeRequest,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """What this run will cost, before you run it."""
    await get_owned_session(session_id, user, db)
    inst = instruments.get(body.instrument)
    if not inst:
        raise HTTPException(404, f"Unknown instrument '{body.instrument}'")
    agents = (await db.execute(
        select(SpawnedAgent).where(SpawnedAgent.session_id == session_id)
    )).scalars().all()
    spec = dict(body.spec or {})
    if body.agent_filter:
        spec["agent_filter"] = body.agent_filter
    chosen = probe_svc._select_agents(list(agents), spec, body.seed or 0)
    mode = "pro" if body.mode == "pro" else "fast"
    return {
        "agent_count": len(chosen),
        "mode": mode,
        "model": get_settings().agent_model(mode),
        "estimated_cost_usd": round(len(chosen) * _COST_PER_AGENT[mode], 4),
    }


@router.post("/sessions/{session_id}/probes")
async def create_probe(
    session_id: str,
    body: ProbeRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run an instrument against this session's population. Answers stream over the session
    websocket as `probe_answer` events; the aggregates land on the probe row when it finishes."""
    await get_owned_session(session_id, user, db)

    inst = instruments.get(body.instrument)
    if not inst:
        raise HTTPException(404, f"Unknown instrument '{body.instrument}'")

    agent_total = (await db.execute(
        select(func.count(SpawnedAgent.id)).where(SpawnedAgent.session_id == session_id)
    )).scalar_one()
    if not agent_total:
        raise HTTPException(400, "This session has no population yet — spawn agents first.")

    spec = dict(body.spec or {})
    if body.agent_filter:
        spec["agent_filter"] = body.agent_filter
    seed = body.seed if body.seed is not None else random.randint(1, 2**31 - 1)
    spec["seed"] = seed
    mode = "pro" if body.mode == "pro" else "fast"

    p = Probe(
        session_id=session_id,
        instrument=inst.key,
        schema_id=inst.schema_id(),
        spec=spec,
        seed=seed,
        model=get_settings().agent_model(mode),
        prompt_hash=probe_svc.prompt_hash(inst, spec),
        status="queued",
    )
    db.add(p)
    await db.commit()

    background_tasks.add_task(probe_svc.run_probe, p.id)
    return _probe_payload(p)


@router.get("/sessions/{session_id}/probes")
async def list_probes(
    session_id: str,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_session(session_id, user, db)
    rows = (await db.execute(
        select(Probe).where(Probe.session_id == session_id).order_by(Probe.created_at.desc())
    )).scalars().all()
    return {"probes": [_probe_payload(p) for p in rows]}


@router.get("/sessions/{session_id}/probes/{probe_id}")
async def get_probe(
    session_id: str,
    probe_id: str,
    include_answers: bool = True,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_session(session_id, user, db)
    p = await db.get(Probe, probe_id)
    if not p or p.session_id != session_id:
        raise HTTPException(404, "Probe not found")

    payload = _probe_payload(p)
    if include_answers:
        rows = (await db.execute(
            select(ProbeAnswer, SpawnedAgent)
            .join(SpawnedAgent, SpawnedAgent.id == ProbeAnswer.agent_id, isouter=True)
            .where(ProbeAnswer.probe_id == probe_id)
            .order_by(ProbeAnswer.created_at)
        )).all()
        payload["answers"] = [
            {
                "agent_id": a.agent_id,
                "name": getattr(ag, "name", ""),
                "role": getattr(ag, "role", ""),
                "avatar_color": getattr(ag, "avatar_color", "#6366f1"),
                "answer": a.answer or {},
                "reasoning": a.reasoning,
                "segments": probe_svc.segments_for(ag) if ag else {},
                "latency_ms": a.latency_ms,
            }
            for a, ag in rows
        ]
    return payload


@router.post("/sessions/{session_id}/probes/{probe_id}/stop")
async def stop_probe(
    session_id: str,
    probe_id: str,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stop a running probe. Answers already collected are kept and still aggregate."""
    await get_owned_session(session_id, user, db)
    p = await db.get(Probe, probe_id)
    if not p or p.session_id != session_id:
        raise HTTPException(404, "Probe not found")
    if p.status in ("queued", "running"):
        p.status = "stopped"
        await db.commit()
    return {"status": p.status}


@router.get("/sessions/{session_id}/probes/{probe_id}/export.csv")
async def export_probe_csv(
    session_id: str,
    probe_id: str,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Flat file for the client's own analyst: one row per agent, answer fields as columns."""
    await get_owned_session(session_id, user, db)
    p = await db.get(Probe, probe_id)
    if not p or p.session_id != session_id:
        raise HTTPException(404, "Probe not found")

    rows = (await db.execute(
        select(ProbeAnswer, SpawnedAgent)
        .join(SpawnedAgent, SpawnedAgent.id == ProbeAnswer.agent_id, isouter=True)
        .where(ProbeAnswer.probe_id == probe_id)
        .order_by(ProbeAnswer.created_at)
    )).all()

    inst = instruments.get(p.instrument)
    answer_keys = list((inst.answer_schema.get("properties") or {}).keys()) if inst else []
    segment_keys = ["stance", "age_band", "humanity_band", "purchase_intent_prior", "price_pain_prior"]

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["agent_id", "name", "role", *segment_keys, *answer_keys])
    for a, ag in rows:
        segs = probe_svc.segments_for(ag) if ag else {}
        w.writerow([
            a.agent_id, getattr(ag, "name", ""), getattr(ag, "role", ""),
            *[segs.get(k, "") for k in segment_keys],
            *[(a.answer or {}).get(k, "") for k in answer_keys],
        ])
    buf.seek(0)
    filename = f"{p.instrument}_{probe_id[:8]}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
