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
from app.models.measurement import Experiment, Probe, ProbeAnswer
from app.services.measurement import experiment as experiment_svc
from app.services.measurement import instruments, probe as probe_svc

router = APIRouter(tags=["measurement"])

# List prices per million tokens, matched against the model id that will ACTUALLY run.
# Pricing the mode label instead ("fast" = Haiku) silently understates the bill wherever
# MODEL_AGENTS is overridden — in production it is set to Sonnet, so a "Fast" probe was
# quoted at Haiku rates and cost ~12x that.
_PRICE_PER_MTOK = {
    "sonnet-4-6": (3.0, 15.0),
    "haiku": (1.0, 5.0),
    "sonnet": (2.0, 10.0),
    "opus": (5.0, 25.0),
    "fable": (10.0, 50.0),
}
# An unrecognised model is priced at the top tier: an estimate that flatters the bill is
# worse than one that overshoots.
_FALLBACK_PRICE = (5.0, 25.0)

# Measured from production probe runs: one answer carries the persona, the ranked KG /
# brief context and the agent's own history, and returns a short typed answer.
_EST_TOKENS_IN = 2400
_EST_TOKENS_OUT = 260


def estimate_cost_usd(model: str, agents: int) -> float:
    """What this probe will actually cost, from the resolved model id."""
    key = next((k for k in _PRICE_PER_MTOK if k in (model or "")), None)
    price_in, price_out = _PRICE_PER_MTOK.get(key, _FALLBACK_PRICE)
    per_agent = (_EST_TOKENS_IN * price_in + _EST_TOKENS_OUT * price_out) / 1_000_000
    return round(agents * per_agent, 4)


class ProbeRequest(BaseModel):
    instrument: str
    spec: dict[str, Any] = {}
    mode: str = "fast"                       # "fast" = Haiku, "pro" = Sonnet
    seed: Optional[int] = None
    agent_filter: Optional[dict[str, Any]] = None


def _instrument_payload(inst) -> dict:
    """The single source of truth both sides read. The UI builds its input panel from
    `inputs` and its headline strip from `kpis`, so a new instrument reaches the product
    without the Lab shell being touched."""
    return {
        "key": inst.key,
        "label": inst.label,
        "description": inst.description,
        "question": inst.question,
        "inputs": [i.as_dict() for i in inst.inputs],
        "kpis": [k.as_dict() for k in inst.kpis],
        "page": inst.page,
        "schema_id": inst.schema_id(),
        "answer_schema": inst.answer_schema,
        # What an A/B test of this tool compares; empty means it cannot be run as one.
        "metrics": [m.as_dict() for m in inst.metrics],
        "supports_experiments": inst.supports_experiments(),
        "decision_key": inst.decision_key,
        "stimulus_key": inst.stimulus_key,
        "question_from": inst.question_from,
        "hidden": inst.hidden,
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
    model = get_settings().agent_model(mode)
    return {
        "agent_count": len(chosen),
        "mode": mode,
        "model": model,
        "estimated_cost_usd": estimate_cost_usd(model, len(chosen)),
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
    # Required inputs are whatever the instrument says they are — the API has no opinion
    # about stimuli, prices or attribute levels.
    missing = [k for k in inst.required_inputs() if not str(spec.get(k) or "").strip()]
    if missing:
        labels = {i.key: i.label for i in inst.inputs}
        raise HTTPException(400, f"Missing required input(s): {', '.join(labels.get(k, k) for k in missing)}")
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
    answer_keys = list((inst.schema_for(p.spec or {}).get("properties") or {}).keys()) if inst else []
    if inst and inst.driver_key and inst.driver_key not in answer_keys:
        answer_keys.append(inst.driver_key)          # coded theme, written after the run
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


# ── experiments (A/B/n) ───────────────────────────────────────────────────────

class VariantRequest(BaseModel):
    key: str
    label: str = ""
    spec: dict[str, Any] = {}


class ExperimentRequest(BaseModel):
    instrument: str
    variants: list[VariantRequest]
    design: str = "within"                   # "within" (paired) | "between" (seeded split) | "choice" (all at once, pick one)
    name: str = ""
    question: str = ""                       # choice design: the ask; defaults to the base tool's question
    spec: dict[str, Any] = {}                # shared across arms: context policy
    mode: str = "fast"
    seed: Optional[int] = None
    agent_filter: Optional[dict[str, Any]] = None


def _experiment_payload(e: Experiment, probes: Optional[list[Probe]] = None) -> dict:
    out = {
        "id": e.id,
        "session_id": e.session_id,
        "name": e.name,
        "design": e.design,
        "instrument": e.instrument,
        "variants": e.variants or [],
        "spec": e.spec or {},
        "seed": e.seed,
        "model": e.model,
        "status": e.status,
        "agent_count": e.agent_count,
        "results": e.results,
        "error": e.error,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "completed_at": e.completed_at.isoformat() if e.completed_at else None,
    }
    if probes is not None:
        out["probes"] = [_probe_payload(p) for p in probes]
    return out


def _validate_experiment(body: ExperimentRequest):
    inst = instruments.get(body.instrument)
    if not inst or inst.hidden:
        raise HTTPException(404, f"Unknown instrument '{body.instrument}'")
    if body.design not in experiment_svc.DESIGNS:
        raise HTTPException(400, f"design must be one of {', '.join(experiment_svc.DESIGNS)}")
    if body.design != "choice" and not inst.supports_experiments():
        raise HTTPException(400, f"{inst.label} cannot be run as an A/B test: it declares no metrics to compare.")
    if not (experiment_svc.MIN_VARIANTS <= len(body.variants) <= experiment_svc.MAX_VARIANTS):
        raise HTTPException(400, f"An experiment needs {experiment_svc.MIN_VARIANTS} to {experiment_svc.MAX_VARIANTS} variants.")
    keys = [v.key.strip() for v in body.variants]
    if len(set(keys)) != len(keys) or any(not k for k in keys):
        raise HTTPException(400, "Variant keys must be unique and non-empty.")
    labels = {i.key: i.label for i in inst.inputs}
    for v in body.variants:
        missing = [k for k in inst.required_inputs() if not str((v.spec or {}).get(k) or "").strip()]
        if missing:
            raise HTTPException(400, f"Variant {v.label or v.key}: missing {', '.join(labels.get(k, k) for k in missing)}")
    return inst


async def _owned_experiment(session_id: str, experiment_id: str, db: AsyncSession) -> Experiment:
    e = await db.get(Experiment, experiment_id)
    if not e or e.session_id != session_id:
        raise HTTPException(404, "Experiment not found")
    return e


@router.post("/sessions/{session_id}/experiments/estimate")
async def estimate_experiment(
    session_id: str,
    body: ExperimentRequest,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Within-subjects asks every chosen agent once per variant; between-subjects asks each
    agent once, so it costs the same as a single probe."""
    await get_owned_session(session_id, user, db)
    _validate_experiment(body)
    agents = (await db.execute(
        select(SpawnedAgent).where(SpawnedAgent.session_id == session_id)
    )).scalars().all()
    shared = dict(body.spec or {})
    if body.agent_filter:
        shared["agent_filter"] = body.agent_filter
    chosen = probe_svc._select_agents(list(agents), shared, body.seed or 0)
    mode = "pro" if body.mode == "pro" else "fast"
    model = get_settings().agent_model(mode)
    calls = len(chosen) * len(body.variants) if body.design == "within" else len(chosen)
    return {
        "agent_count": len(chosen),
        "variants": len(body.variants),
        "calls": calls,
        "mode": mode,
        "model": model,
        "estimated_cost_usd": estimate_cost_usd(model, calls),
    }


@router.post("/sessions/{session_id}/experiments")
async def create_experiment(
    session_id: str,
    body: ExperimentRequest,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run an A/B/n test: one probe per variant, then the paired (or split) comparison. Arms
    stream as ordinary `probe_*` events; `experiment_complete` carries the verdict."""
    await get_owned_session(session_id, user, db)
    inst = _validate_experiment(body)

    agent_total = (await db.execute(
        select(func.count(SpawnedAgent.id)).where(SpawnedAgent.session_id == session_id)
    )).scalar_one()
    if not agent_total:
        raise HTTPException(400, "This session has no population yet — spawn agents first.")

    seed = body.seed if body.seed is not None else random.randint(1, 2**31 - 1)
    mode = "pro" if body.mode == "pro" else "fast"
    model = get_settings().agent_model(mode)
    shared = dict(body.spec or {})
    if body.agent_filter:
        shared["agent_filter"] = body.agent_filter
    variants = [{"key": v.key.strip(), "label": (v.label or v.key).strip(), "spec": dict(v.spec or {})} for v in body.variants]

    e = Experiment(
        session_id=session_id, name=body.name.strip(), design=body.design, instrument=inst.key,
        variants=variants, spec=shared, seed=seed, model=model, status="queued",
    )
    db.add(e)
    await db.flush()

    probes = []
    if body.design == "choice":
        # One probe for the whole comparison: every agent sees all the options at once.
        choice = instruments.get("choice")
        question = body.question.strip() or (
            str((variants[0]["spec"] or {}).get(inst.question_from) or "").strip() if inst.question_from else ""
        ) or inst.question
        spec = experiment_svc.compose_choice_spec(inst, variants, shared, question, seed)
        p = Probe(
            session_id=session_id, instrument=choice.key, schema_id=choice.schema_id(), spec=spec,
            experiment_id=e.id, variant_key=experiment_svc.CHOICE_ARM, seed=seed, model=model,
            prompt_hash=probe_svc.prompt_hash(choice, spec), status="queued",
        )
        db.add(p)
        probes.append(p)
    else:
        for v in variants:
            # Every arm is a full probe: same instrument, same shared filter and context, the same
            # seed (so a within-subjects sample is the SAME agents in every arm), its own stimulus.
            spec = {**shared, **v["spec"], "seed": seed}
            p = Probe(
                session_id=session_id, instrument=inst.key, schema_id=inst.schema_id(), spec=spec,
                experiment_id=e.id, variant_key=v["key"], seed=seed, model=model,
                prompt_hash=probe_svc.prompt_hash(inst, spec), status="queued",
            )
            db.add(p)
            probes.append(p)
    await db.commit()

    background_tasks.add_task(experiment_svc.run_experiment, e.id)
    return _experiment_payload(e, probes)


@router.get("/sessions/{session_id}/experiments")
async def list_experiments(
    session_id: str,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_session(session_id, user, db)
    rows = (await db.execute(
        select(Experiment).where(Experiment.session_id == session_id).order_by(Experiment.created_at.desc())
    )).scalars().all()
    return {"experiments": [_experiment_payload(e) for e in rows]}


@router.get("/sessions/{session_id}/experiments/{experiment_id}")
async def get_experiment(
    session_id: str,
    experiment_id: str,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_session(session_id, user, db)
    e = await _owned_experiment(session_id, experiment_id, db)
    probes = (await db.execute(
        select(Probe).where(Probe.experiment_id == experiment_id).order_by(Probe.created_at)
    )).scalars().all()
    return _experiment_payload(e, probes)


@router.post("/sessions/{session_id}/experiments/{experiment_id}/stop")
async def stop_experiment(
    session_id: str,
    experiment_id: str,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stop every running arm. Answers already collected still pair and compare."""
    await get_owned_session(session_id, user, db)
    e = await _owned_experiment(session_id, experiment_id, db)
    if e.status in ("queued", "running"):
        probes = (await db.execute(
            select(Probe).where(Probe.experiment_id == experiment_id)
        )).scalars().all()
        for p in probes:
            if p.status in ("queued", "running"):
                p.status = "stopped"
        await db.commit()
    return {"status": e.status}


@router.get("/sessions/{session_id}/experiments/{experiment_id}/export.csv")
async def export_experiment_csv(
    session_id: str,
    experiment_id: str,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One row per agent, every arm's answer side by side, plus whether they flipped."""
    await get_owned_session(session_id, user, db)
    e = await _owned_experiment(session_id, experiment_id, db)
    inst = instruments.get("choice") if e.design == "choice" else instruments.get(e.instrument)
    answer_keys = list((inst.answer_schema.get("properties") or {}).keys()) if inst else []
    if inst and inst.driver_key and inst.driver_key not in answer_keys:
        answer_keys.append(inst.driver_key)          # coded theme, written after the run
    segment_keys = ["stance", "age_band", "humanity_band", "purchase_intent_prior", "price_pain_prior"]
    variants = [{"key": experiment_svc.CHOICE_ARM, "label": "all"}] if e.design == "choice" else list(e.variants or [])

    probes = (await db.execute(select(Probe).where(Probe.experiment_id == experiment_id))).scalars().all()
    probe_by_key = {p.variant_key: p for p in probes}
    rows = (await db.execute(
        select(ProbeAnswer, SpawnedAgent)
        .join(SpawnedAgent, SpawnedAgent.id == ProbeAnswer.agent_id, isouter=True)
        .where(ProbeAnswer.probe_id.in_([p.id for p in probes]))
    )).all()

    by_agent: dict[str, dict] = {}
    for a, ag in rows:
        entry = by_agent.setdefault(a.agent_id, {"agent": ag, "answers": {}})
        entry["answers"][a.probe_id] = a.answer or {}

    buf = io.StringIO()
    w = csv.writer(buf)
    header = ["agent_id", "name", "role", *segment_keys]
    for v in variants:
        header += [f"{v['key']}_{k}" for k in answer_keys]
    if inst and inst.decision_key:
        header.append("flipped")
    w.writerow(header)
    for agent_id, entry in sorted(by_agent.items()):
        ag = entry["agent"]
        segs = probe_svc.segments_for(ag) if ag else {}
        line = [agent_id, getattr(ag, "name", ""), getattr(ag, "role", ""), *[segs.get(k, "") for k in segment_keys]]
        decisions = []
        for v in variants:
            p = probe_by_key.get(v["key"])
            ans = entry["answers"].get(p.id, {}) if p else {}
            line += [ans.get(k, "") for k in answer_keys]
            if inst and inst.decision_key and ans:
                decisions.append(ans.get(inst.decision_key))
        if inst and inst.decision_key:
            line.append("yes" if len(decisions) == len(variants) and len(set(decisions)) > 1 else "no")
        w.writerow(line)
    buf.seek(0)
    filename = f"experiment_{e.instrument}_{experiment_id[:8]}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
