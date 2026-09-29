"""Behaviour Lab API — run instruments against a population and read the results back."""
import io
import csv
import random
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select
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
        "form": inst.form,
        "templates": getattr(inst, "templates", None) or _templates_for(inst.key),
    }


def _templates_for(key: str) -> list:
    if key == "survey":
        from app.services.measurement.instruments.survey import TEMPLATES
        return TEMPLATES
    return []


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


class JourneySuggestRequest(BaseModel):
    question: Optional[str] = None
    mode: str = "pro"


@router.post("/sessions/{session_id}/journey/suggest")
async def suggest_journey(
    session_id: str,
    body: JourneySuggestRequest,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Propose the journey for the Journey tool (brief L7-01): the ordered steps to the outcome
    in the question, drawn from the evidence brief, the sampling frame and the knowledge graph.
    The analyst edits the result before running; nothing is stored here."""
    session = await get_owned_session(session_id, user, db)
    from app.services.measurement.instruments import journey as journey_mod
    question = (body.question or "").strip() or session.query
    try:
        return await journey_mod.suggest_stages(session_id, question, mode="pro" if body.mode == "pro" else "fast")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not propose the journey: {type(e).__name__}: {str(e)[:160]}")


# ── Calibration rules (brief L4-02, the minimum of it) and lever runs (brief L7-04) ────────

class RuleRequest(BaseModel):
    lever: str
    description: str = ""
    applies_to: dict[str, Any] = {}
    deltas: dict[str, Any] = {}
    bound: int = 4
    evidence: list[Any] = []
    basis: str = ""
    author: str = ""


class DraftRuleRequest(BaseModel):
    lever: str
    journey_probe_id: Optional[str] = None
    candidate_id: Optional[str] = None
    mode: str = "pro"


class TargetingRunRequest(BaseModel):
    journey_probe_id: str
    candidate_id: str
    behaviours: Optional[list[str]] = None
    points: Optional[int] = None
    mode: str = "fast"


class ReviewRequest(BaseModel):
    reviewed_by: str
    approve: bool = True


class LeverRunRequest(BaseModel):
    journey_probe_id: str
    candidate_id: str
    lever: str
    rule_id: Optional[str] = None
    mode: str = "fast"


def _rule_fields(body: RuleRequest) -> dict:
    ev = []
    for e in body.evidence or []:
        if isinstance(e, dict):
            if str(e.get("ref") or "").strip():
                ev.append({"ref": str(e.get("ref"))[:300], "note": str(e.get("note") or "")[:300]})
        elif str(e or "").strip():
            ev.append({"ref": str(e)[:300], "note": ""})
    return {"lever": body.lever.strip()[:160], "description": body.description.strip()[:1000], "applies_to": {k: v for k, v in (body.applies_to or {}).items() if v},
            "deltas": {str(k): int(v) for k, v in (body.deltas or {}).items() if str(v).strip() not in ("", "0")}, "bound": int(body.bound or 4),
            "evidence": ev, "basis": body.basis.strip()[:1000], "author": body.author.strip()[:120]}


@router.get("/sessions/{session_id}/rules")
async def list_rules(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The session's calibration rules, with the dial vocabulary a rule may move."""
    await get_owned_session(session_id, user, db)
    from app.services.measurement import levers
    return {"rules": await levers.rules_for_session(session_id), "dials": levers.dial_keys(), "bound_max": levers.MAX_BOUND, "bound_default": levers.DEFAULT_BOUND}


@router.post("/sessions/{session_id}/rules")
async def create_rule(session_id: str, body: RuleRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    from app.models.measurement import CalibrationMapping
    from app.services.measurement import levers
    fields = _rule_fields(body)
    problems = levers.validate_rule(fields)
    if problems:
        raise HTTPException(400, "; ".join(problems))
    m = CalibrationMapping(session_id=session_id, status=levers.STATUS_DRAFT, **fields)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return levers.rule_payload(m)


@router.post("/sessions/{session_id}/rules/draft")
async def draft_rule(session_id: str, body: DraftRuleRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The system drafts a rule for a lever from the candidate's barriers, what the twins said would
    remove them, the facts on file and the documents the twins cited; saved as a draft for a human
    to read, correct and sign. Evidence is chosen only from that material — empty when nothing
    speaks to the lever, and the rule is then labelled an assumption."""
    await get_owned_session(session_id, user, db)
    from app.services.measurement import levers
    res = await levers.draft_rule(session_id, body.lever, journey_probe_id=body.journey_probe_id, candidate_id=body.candidate_id, mode=body.mode)
    if res.get("error"):
        raise HTTPException(422, res["error"])
    return res


@router.put("/sessions/{session_id}/rules/{rule_id}")
async def update_rule(session_id: str, rule_id: str, body: RuleRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Editing a rule sends it back to draft: a change must be reviewed again."""
    await get_owned_session(session_id, user, db)
    from app.models.measurement import CalibrationMapping
    from app.services.measurement import levers
    m = await db.get(CalibrationMapping, rule_id)
    if not m or m.session_id != session_id:
        raise HTTPException(404, "Rule not found")
    fields = _rule_fields(body)
    problems = levers.validate_rule(fields)
    if problems:
        raise HTTPException(400, "; ".join(problems))
    for k, v in fields.items():
        setattr(m, k, v)
    m.status, m.reviewed_by, m.reviewed_at = levers.STATUS_DRAFT, "", None
    await db.commit()
    await db.refresh(m)
    return levers.rule_payload(m)


@router.post("/sessions/{session_id}/rules/{rule_id}/review")
async def review_rule(session_id: str, rule_id: str, body: ReviewRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Sign a rule off (or withdraw the sign-off). Only a reviewed rule can be simulated."""
    await get_owned_session(session_id, user, db)
    from datetime import datetime as _dt
    from app.models.measurement import CalibrationMapping
    from app.services.measurement import levers
    m = await db.get(CalibrationMapping, rule_id)
    if not m or m.session_id != session_id:
        raise HTTPException(404, "Rule not found")
    if body.approve:
        if not body.reviewed_by.strip():
            raise HTTPException(400, "A review needs the reviewer's name.")
        m.status, m.reviewed_by, m.reviewed_at = levers.STATUS_REVIEWED, body.reviewed_by.strip()[:120], _dt.utcnow()
    else:
        m.status, m.reviewed_by, m.reviewed_at = levers.STATUS_DRAFT, "", None
    await db.commit()
    await db.refresh(m)
    return levers.rule_payload(m)


@router.delete("/sessions/{session_id}/rules/{rule_id}")
async def delete_rule(session_id: str, rule_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    from app.models.measurement import CalibrationMapping
    m = await db.get(CalibrationMapping, rule_id)
    if not m or m.session_id != session_id:
        raise HTTPException(404, "Rule not found")
    await db.delete(m)
    await db.commit()
    return {"deleted": rule_id}


@router.post("/sessions/{session_id}/levers/run")
async def run_lever(session_id: str, body: LeverRunRequest, background_tasks: BackgroundTasks, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Simulate a lever on a candidate (brief L7-04): the same twins answer the journey again with
    a reviewed rule's dial shifts applied. Refuses — 409 with the missing rule named — where no
    reviewed rule exists for the lever; it never guesses."""
    await get_owned_session(session_id, user, db)
    from app.services.measurement import levers
    res = await levers.start(session_id, journey_probe_id=body.journey_probe_id, candidate_id=body.candidate_id, lever=body.lever,
                             rule_id=body.rule_id, mode=body.mode)
    if res.get("error"):
        raise HTTPException(400, res["error"])
    if res.get("refused"):
        raise HTTPException(409, detail=res)
    background_tasks.add_task(levers.run, res["experiment_id"])
    e = await db.get(Experiment, res["experiment_id"])
    return {**_experiment_payload(e), "rule": res["rule"]}


@router.get("/sessions/{session_id}/levers")
async def list_lever_runs(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Every lever run in the session, newest first, with its shift when complete."""
    await get_owned_session(session_id, user, db)
    rows = (await db.execute(select(Experiment).where(Experiment.session_id == session_id).order_by(Experiment.created_at.desc()))).scalars().all()
    return {"runs": [_experiment_payload(e) for e in rows if (e.spec or {}).get("lever_run")]}


@router.get("/sessions/{session_id}/targeting/behaviours")
async def targeting_behaviours(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """What a behaviour-targeting run can rank (brief L7-05): the session's question-specific dials
    (ticked by default) and the fixed dial vocabulary, with the nudge size limits."""
    await get_owned_session(session_id, user, db)
    from app.services.measurement import targeting
    return await targeting.behaviours_for(session_id)


@router.post("/sessions/{session_id}/targeting/run")
async def run_targeting(session_id: str, body: TargetingRunRequest, background_tasks: BackgroundTasks, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Rank behaviours by modelled movement per point at a candidate's step (brief L7-05): the twins
    at risk at that step answer the journey again once per behaviour with that one dial nudged by
    the same few points; the shift per point is counted and ranked, backfire flagged."""
    await get_owned_session(session_id, user, db)
    from app.services.measurement import targeting
    res = await targeting.start(session_id, journey_probe_id=body.journey_probe_id, candidate_id=body.candidate_id, behaviours=body.behaviours, points=body.points, mode=body.mode)
    if res.get("error"):
        raise HTTPException(400, res["error"])
    background_tasks.add_task(targeting.run, res["experiment_id"])
    e = await db.get(Experiment, res["experiment_id"])
    return {**_experiment_payload(e), "behaviours": res["behaviours"], "points": res["points"], "at_risk": res["at_risk"]}


@router.get("/sessions/{session_id}/targeting")
async def list_targeting_runs(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Every behaviour-targeting run in the session, newest first, with `results.targeting` when counted."""
    await get_owned_session(session_id, user, db)
    rows = (await db.execute(select(Experiment).where(Experiment.session_id == session_id).order_by(Experiment.created_at.desc()))).scalars().all()
    return {"runs": [_experiment_payload(e) for e in rows if (e.spec or {}).get("targeting")]}


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
    problems = inst.validate(spec)
    if problems:
        raise HTTPException(400, "; ".join(problems))
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


@router.delete("/sessions/{session_id}/probes/{probe_id}", status_code=204)
async def delete_probe(
    session_id: str,
    probe_id: str,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a standalone probe and every answer under it.

    An arm of an A/B test is deleted with its experiment, never on its own — the comparison
    would be left pointing at a missing probe. A run still in flight must be stopped first:
    the runner keeps writing answers under the probe id until it notices the stop."""
    await get_owned_session(session_id, user, db)
    p = await db.get(Probe, probe_id)
    if not p or p.session_id != session_id:
        raise HTTPException(404, "Probe not found")
    if p.experiment_id:
        raise HTTPException(409, "This run is one arm of an A/B test. Delete the test instead.")
    if p.status in ("queued", "running"):
        raise HTTPException(409, "Stop the run before deleting it.")
    await db.execute(delete(ProbeAnswer).where(ProbeAnswer.probe_id == probe_id))
    await db.delete(p)
    await db.commit()


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
    # A hidden tool may still be an A/B base if it declares metrics (Ask, superseded in the
    # picker by the survey, stays the base for text-material tests); the choice instrument
    # itself never is.
    if not inst or (inst.hidden and not inst.supports_experiments()):
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
        problems = inst.validate(v.spec or {})
        if problems:
            raise HTTPException(400, f"Variant {v.label or v.key}: " + "; ".join(problems))
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


@router.delete("/sessions/{session_id}/experiments/{experiment_id}", status_code=204)
async def delete_experiment(
    session_id: str,
    experiment_id: str,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an A/B test, its arm probes and every answer under them. Stop it first if it is
    still running."""
    await get_owned_session(session_id, user, db)
    e = await _owned_experiment(session_id, experiment_id, db)
    if e.status in ("queued", "running"):
        raise HTTPException(409, "Stop the test before deleting it.")
    arm_ids = select(Probe.id).where(Probe.experiment_id == experiment_id)
    await db.execute(delete(ProbeAnswer).where(ProbeAnswer.probe_id.in_(arm_ids)))
    await db.execute(delete(Probe).where(Probe.experiment_id == experiment_id))
    await db.delete(e)
    await db.commit()


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
