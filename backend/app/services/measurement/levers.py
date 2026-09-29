"""Lever simulation — counterfactual runs (brief L7-04), gated on calibration rules (brief L4-02).

A candidate gap says how many people are stuck at a step and what stands in their way. The
question a partnership actually asks is *if we pulled this lever, how many would move?* This
module answers it the only way the brief allows: with a written, reviewed CALIBRATION RULE
saying what evidence shows the lever does to behaviour — and it refuses to produce a number
where no such rule exists, rather than guess.

  * A **calibration rule** (`calibration_mappings`, the minimum of L4-02) names a lever, who
    it applies to (everyone, or a segment such as a deprivation band, a stance, an age band),
    which behaviour dials it moves and by how many points on the 0–10 scale (bounded), the
    evidence it rests on, who wrote it, and whether it has been reviewed. Rules are stored,
    listed, exported in the run record, and never hidden constants.
  * A **lever run** is a within-subjects experiment on the Journey instrument: the same twins,
    the same seed, the same steps, twice — once as they are and once with the rule's dial
    shifts applied to the twins it covers and the change described to them. The **shift** is
    counted from the two arms: the conversion at the candidate's step then → now with a paired
    interval, the share reaching the end of the journey, how many twins moved up, down or not
    at all (the dispersion), the same by deprivation band, and — where headcounts exist — the
    people moved.
  * Where the lever has no reviewed rule in this session, `find_rule` returns nothing and the
    API refuses with the missing rule named. There is no fallback that asks the twins to
    imagine the change: that would be the guess the brief forbids.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select

from app.services.measurement import stats

DIAL_MIN, DIAL_MAX = 0, 10
DEFAULT_BOUND = 4          # a rule may move a dial by at most this many points unless it says otherwise
MAX_BOUND = 6
STATUS_DRAFT, STATUS_REVIEWED = "draft", "reviewed"


# ── rules ────────────────────────────────────────────────────────────────────

def dial_keys() -> dict[str, list[str]]:
    from app.services.agents.agent_factory import DIALS_SCHEMA
    return {g: list(v.keys()) for g, v in json.loads(DIALS_SCHEMA).items()}


def norm_lever(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def validate_rule(data: dict) -> list[str]:
    """Human-readable problems with a rule as submitted; empty when it can be saved."""
    problems: list[str] = []
    if not str(data.get("lever") or "").strip():
        problems.append("A rule needs the lever it describes.")
    deltas = data.get("deltas") if isinstance(data.get("deltas"), dict) else {}
    if not deltas:
        problems.append("A rule needs at least one dial change (e.g. friction.time_cost: -3).")
    keys = dial_keys()
    bound = int(data.get("bound") or DEFAULT_BOUND)
    if not (1 <= bound <= MAX_BOUND):
        problems.append(f"The bound must be between 1 and {MAX_BOUND} points.")
    for k, v in deltas.items():
        if "." not in str(k) or str(k).split(".", 1)[0] not in keys or str(k).split(".", 1)[1] not in keys[str(k).split(".", 1)[0]]:
            problems.append(f"'{k}' is not a dial (use group.dial, e.g. friction.money_pain).")
            continue
        try:
            d = int(v)
        except (TypeError, ValueError):
            problems.append(f"The change for {k} must be a whole number of points.")
            continue
        if d == 0:
            problems.append(f"The change for {k} is zero.")
        elif abs(d) > bound:
            problems.append(f"The change for {k} ({d:+d}) is outside the rule's bound of ±{bound}.")
    ev = data.get("evidence") if isinstance(data.get("evidence"), list) else []
    if not any(str((e or {}).get("ref") if isinstance(e, dict) else e or "").strip() for e in ev):
        problems.append("A rule needs at least one piece of evidence it rests on.")
    if not str(data.get("basis") or "").strip():
        problems.append("Say in a line how the evidence sets these values (the basis).")
    return problems


def applies(rule: dict, segments: dict) -> bool:
    """Whether a rule covers a twin, from the twin's segment map (`probe.segments_for`).
    An empty `applies_to` covers everyone; otherwise every listed key must match one of its values."""
    cond = rule.get("applies_to") if isinstance(rule.get("applies_to"), dict) else {}
    for key, values in cond.items():
        wanted = [str(v) for v in (values if isinstance(values, list) else [values]) if str(v).strip()]
        if not wanted:
            continue
        if str(segments.get(key, "")) not in wanted:
            return False
    return True


def adjusted_dials(dials: Optional[dict], rule: dict) -> dict:
    """The twin's dials with the rule's changes applied, each clamped to the 0–10 scale and to
    the rule's bound. The original object is never touched."""
    out = json.loads(json.dumps(dials or {}))
    bound = int(rule.get("bound") or DEFAULT_BOUND)
    for k, v in (rule.get("deltas") or {}).items():
        try:
            group, dial = str(k).split(".", 1)
            d = max(-bound, min(bound, int(v)))
        except (TypeError, ValueError):
            continue
        g = out.setdefault(group, {})
        if not isinstance(g, dict):
            continue
        cur = g.get(dial)
        try:
            cur = float(cur) if cur is not None else 5.0
        except (TypeError, ValueError):
            cur = 5.0
        g[dial] = int(round(max(DIAL_MIN, min(DIAL_MAX, cur + d))))
    return out


def rule_payload(m: Any) -> dict:
    return {
        "id": m.id, "session_id": m.session_id, "lever": m.lever, "description": m.description or "",
        "applies_to": m.applies_to or {}, "deltas": m.deltas or {}, "bound": int(m.bound or DEFAULT_BOUND),
        "evidence": m.evidence or [], "basis": m.basis or "", "author": m.author or "",
        "status": m.status or STATUS_DRAFT, "reviewed_by": m.reviewed_by or "", "reviewed_at": m.reviewed_at.isoformat() if m.reviewed_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None, "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


async def rules_for_session(session_id: str) -> list[dict]:
    from app.core.database import AsyncSessionLocal
    from app.models.measurement import CalibrationMapping
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(CalibrationMapping).where(CalibrationMapping.session_id == session_id).order_by(CalibrationMapping.created_at))).scalars().all()
        return [rule_payload(m) for m in rows]


async def find_rule(session_id: str, lever: str, *, rule_id: Optional[str] = None) -> tuple[Optional[dict], list[dict]]:
    """The reviewed rule for a lever (by id when given, else by name), and every rule that
    names the lever whatever its status — so a refusal can say 'there is a draft'."""
    rules = await rules_for_session(session_id)
    want = norm_lever(lever)
    named = [r for r in rules if (rule_id and r["id"] == rule_id) or (not rule_id and want and (norm_lever(r["lever"]) == want or want in norm_lever(r["lever"]) or norm_lever(r["lever"]) in want))]
    reviewed = [r for r in named if r["status"] == STATUS_REVIEWED]
    return (reviewed[0] if reviewed else None), named


def refusal(lever: str, named: list[dict]) -> dict:
    """What the API says when no reviewed rule exists: the missing rule, named."""
    drafts = [r for r in named if r["status"] != STATUS_REVIEWED]
    if drafts:
        msg = (f"There is a rule for '{lever}' but it has not been reviewed. Nothing is simulated until a reviewer signs it off — "
               "a number from an unreviewed rule would be a guess.")
    else:
        msg = (f"No calibration rule for '{lever}' in this session, so nothing can be simulated: the tool will not guess what this lever does "
               "to behaviour. Write a rule — who it applies to, which dials it moves and by how much, the evidence it rests on — and have it reviewed.")
    return {"refused": True, "lever": lever, "reason": msg, "drafts": [r["id"] for r in drafts], "missing": not drafts}


# ── the run ──────────────────────────────────────────────────────────────────

def lever_spec(rule: dict, candidate: dict) -> dict:
    """What the lever arm carries: the rule (frozen into the run record) and the change as the
    twins are told it."""
    return {
        "rule_id": rule["id"], "lever": rule["lever"], "description": rule.get("description") or "",
        "applies_to": rule.get("applies_to") or {}, "deltas": rule.get("deltas") or {}, "bound": int(rule.get("bound") or DEFAULT_BOUND),
        "candidate_id": candidate.get("id"), "step": candidate.get("step"),
        "from": (candidate.get("from") or {}).get("label"), "to": (candidate.get("to") or {}).get("label"),
        "reviewed_by": rule.get("reviewed_by") or "", "reviewed_at": rule.get("reviewed_at"),
    }


def counterfactual_block(lever: dict) -> str:
    """The change in place, as the twin reads it. Describes the world, not the answer."""
    what = str(lever.get("description") or lever.get("lever") or "").strip()
    step = f" It bears on the step from '{lever.get('from')}' to '{lever.get('to')}'." if lever.get("from") and lever.get("to") else ""
    return ("A CHANGE NOW IN PLACE (this run is a what-if; everything else about your life is as it was):\n"
            f"{what}.{step}\nAnswer as you would if this were really there for you — no more helpful than it would actually be.")


async def start(session_id: str, *, journey_probe_id: str, candidate_id: str, lever: str, rule_id: Optional[str], mode: str) -> dict:
    """Create the lever run (an experiment with a baseline arm and a lever arm) or refuse.
    Returns `{experiment_id, ...}` or `{refused: True, ...}`. The caller schedules `run`."""
    from app.core.config import get_settings
    from app.core.database import AsyncSessionLocal
    from app.models.measurement import Experiment, Probe
    from app.services.measurement import instruments, probe as probe_svc

    async with AsyncSessionLocal() as db:
        base = await db.get(Probe, journey_probe_id)
        if not base or base.session_id != session_id or base.instrument != "journey" or base.status != "complete":
            return {"error": "The journey run was not found or is not complete."}
        agg = base.aggregates or {}
        candidate = next((c for c in (agg.get("candidates") or []) if c.get("id") == candidate_id or f"{base.id}:{c.get('id')}" == candidate_id), None)
        if not candidate:
            return {"error": "That candidate is not on this journey run."}
        base_spec = {k: v for k, v in (base.spec or {}).items() if k not in ("seed", "lever")}
        base_seed = int(base.seed or 0)

    rule, named = await find_rule(session_id, lever, rule_id=rule_id)
    if not rule:
        return refusal(lever, named)

    inst = instruments.get("journey")
    lever_arm = lever_spec(rule, candidate)
    model = get_settings().agent_model("pro" if mode == "pro" else "fast")
    async with AsyncSessionLocal() as db:
        e = Experiment(
            id=str(uuid.uuid4()), session_id=session_id, name=f"Lever: {rule['lever']} at {lever_arm.get('from')} → {lever_arm.get('to')}",
            design="within", instrument="journey",
            variants=[{"key": "baseline", "label": "As things are", "spec": {}}, {"key": "lever", "label": rule["lever"], "spec": {"lever": lever_arm}}],
            spec={**base_spec, "lever_run": {"journey_probe_id": journey_probe_id, "candidate_id": candidate.get("id"), "rule_id": rule["id"], "lever": rule["lever"]}},
            seed=base_seed, model=model, status="queued",
        )
        db.add(e)
        for v in e.variants:
            spec = {**base_spec, **v["spec"], "seed": base_seed}
            db.add(Probe(id=str(uuid.uuid4()), session_id=session_id, instrument="journey", schema_id=inst.schema_id(), spec=spec, experiment_id=e.id,
                         variant_key=v["key"], seed=base_seed, model=model, prompt_hash=probe_svc.prompt_hash(inst, spec), status="queued"))
        await db.commit()
        return {"experiment_id": e.id, "rule": rule, "candidate_id": candidate.get("id")}


async def run(experiment_id: str) -> None:
    """Run both arms, then count the shift and store it on the experiment."""
    from app.services.measurement.experiment import run_experiment
    await run_experiment(experiment_id)
    try:
        await attach_shift(experiment_id)
    except Exception as e:  # noqa: BLE001
        print(f"[levers] shift failed for {experiment_id}: {type(e).__name__}: {e}")


def _through_flags(rows: dict[str, dict], stages: list[dict], k: int) -> dict[str, float]:
    from app.services.measurement.instruments.journey import _index, _through
    idx = _index(stages)
    out = {}
    for aid, r in rows.items():
        a = r.get("answer") or {}
        if a.get("reached") in idx and idx[a["reached"]] >= k:
            out[aid] = 1.0 if _through(a, k, idx) else 0.0
    return out


def _reached_index(rows: dict[str, dict], stages: list[dict]) -> dict[str, int]:
    from app.services.measurement.instruments.journey import _index
    idx = _index(stages)
    return {aid: idx[(r.get("answer") or {}).get("reached")] for aid, r in rows.items() if (r.get("answer") or {}).get("reached") in idx}


def shift(*, control_agg: dict, lever_agg: dict, control_rows: dict[str, dict], lever_rows: dict[str, dict], candidate_id: str, seed: int = 0) -> dict:
    """The modelled shift, counted from the two arms on the same twins."""
    from app.services.measurement.instruments.journey import stages_of, _index
    stages = control_agg.get("stages") or []
    idx = _index(stages)
    c0 = next((c for c in control_agg.get("candidates") or control_agg.get("transitions") or [] if c.get("id") == candidate_id), None)
    c1 = next((c for c in lever_agg.get("transitions") or [] if c.get("id") == candidate_id), None)
    if not c0 or not c1 or not stages:
        return {"available": False, "reason": "The candidate's step was not found in both arms."}
    k = int(c0.get("step") or 1) - 1
    a, b = _through_flags(control_rows, stages, k), _through_flags(lever_rows, stages, k)
    paired = [(a[x], b[x]) for x in a if x in b]
    lift = stats.paired_lift(paired, seed=seed) if paired else {"mean": 0.0, "low": 0.0, "high": 0.0, "n": 0, "significant": False}
    # movement at the step: up (stuck → through), down (through → stuck), unchanged
    up = sum(1 for x, y in paired if y > x)
    down = sum(1 for x, y in paired if y < x)
    # the end of the journey
    last = len(stages) - 1
    r0, r1 = _reached_index(control_rows, stages), _reached_index(lever_rows, stages)
    end_pairs = [(1.0 if r0[x] >= last else 0.0, 1.0 if r1[x] >= last else 0.0) for x in r0 if x in r1]
    end_lift = stats.paired_lift(end_pairs, seed=seed) if end_pairs else {"mean": 0.0, "low": 0.0, "high": 0.0, "n": 0, "significant": False}
    # by deprivation band (and every other split the rows carry), paired inside the band
    by_segment: dict[str, list[dict]] = {}
    keys = sorted({sk for r in control_rows.values() for sk in (r.get("segments") or {})})
    for sk in keys:
        buckets: dict[str, list[tuple[float, float]]] = {}
        for x in a:
            if x in b:
                val = (control_rows[x].get("segments") or {}).get(sk)
                if val:
                    buckets.setdefault(str(val), []).append((a[x], b[x]))
        rows_out = []
        for val, pairs in buckets.items():
            lf = stats.paired_lift(pairs, seed=seed)
            rows_out.append({"value": val, "n": len(pairs), "thin": len(pairs) < 3, "then": round(sum(p[0] for p in pairs) / len(pairs), 4),
                             "now": round(sum(p[1] for p in pairs) / len(pairs), 4), "lift": lf["mean"], "low": lf["low"], "high": lf["high"]})
        if len(rows_out) >= 2:
            by_segment[sk] = sorted(rows_out, key=lambda r: (-r["n"], r["value"]))
    out = {
        "available": True, "candidate_id": candidate_id, "step": c0.get("step"), "from": c0.get("from"), "to": c0.get("to"),
        "conversion": {"then": c0.get("conversion"), "now": c1.get("conversion"), "lift": lift["mean"], "low": lift["low"], "high": lift["high"],
                       "n": lift.get("n", len(paired)), "significant": bool(lift.get("significant"))},
        "stuck": {"then": c0.get("stuck"), "now": c1.get("stuck")},
        "movement": {"up": up, "down": down, "unchanged": len(paired) - up - down, "n": len(paired)},
        "end": {"label": stages[last].get("label"), "then": (control_agg.get("headline") or {}).get("share"), "now": (lever_agg.get("headline") or {}).get("share"),
                "lift": end_lift["mean"], "low": end_lift["low"], "high": end_lift["high"], "n": end_lift.get("n", len(end_pairs)), "significant": bool(end_lift.get("significant"))},
        "segments": by_segment,
    }
    # people moved, where the baseline had headcounts: the at-risk headcount × the lift
    if c0.get("at_risk_people") is not None:
        n = float(c0["at_risk_people"])
        out["people"] = {"moved": int(round(n * lift["mean"])), "low": int(round(n * lift["low"])), "high": int(round(n * lift["high"])),
                         "stuck_then": c0.get("stuck_people"), "stuck_now": int(round(n * (1 - float(c1.get("conversion") or 0)))), "basis": c0.get("basis") or ""}
    out["sentence"] = _sentence(out)
    return out


def _sentence(s: dict) -> str:
    conv = s["conversion"]
    pts = round(float(conv["lift"]) * 100)
    lo, hi = round(float(conv["low"]) * 100), round(float(conv["high"]) * 100)
    text = (f"With the lever in place, {round(float(conv['now'] or 0) * 100)}% of those at '{(s.get('from') or {}).get('label')}' reach "
            f"'{(s.get('to') or {}).get('label')}' against {round(float(conv['then'] or 0) * 100)}% without it: a shift of {pts:+d} points "
            f"(95% CI {lo:+d} to {hi:+d}, n={conv['n']}{', real' if conv['significant'] else ', not distinguishable from zero'})")
    mv = s["movement"]
    text += f"; {mv['up']} twin{'s' if mv['up'] != 1 else ''} moved through, {mv['down']} fell back, {mv['unchanged']} unchanged"
    if s.get("people"):
        p = s["people"]
        text += f"; ≈{p['moved']:,} people moved ({p['low']:,}–{p['high']:,})"
    end = s["end"]
    text += f". At the end of the journey ('{end['label']}'): {round(float(end['then'] or 0) * 100)}% → {round(float(end['now'] or 0) * 100)}% ({round(float(end['lift']) * 100):+d} points)."
    return text


async def attach_shift(experiment_id: str) -> None:
    from sqlalchemy.orm.attributes import flag_modified
    from app.core.database import AsyncSessionLocal
    from app.models.measurement import Experiment, Probe, ProbeAnswer

    async with AsyncSessionLocal() as db:
        e = await db.get(Experiment, experiment_id)
        if not e or not (e.spec or {}).get("lever_run"):
            return
        probes = {p.variant_key: p for p in (await db.execute(select(Probe).where(Probe.experiment_id == experiment_id))).scalars().all()}
        base, lev = probes.get("baseline"), probes.get("lever")
        if not base or not lev or not (base.aggregates or {}).get("transitions") or not (lev.aggregates or {}).get("transitions"):
            return
        rows = {}
        for key, p in (("baseline", base), ("lever", lev)):
            answers = (await db.execute(select(ProbeAnswer).where(ProbeAnswer.probe_id == p.id))).scalars().all()
            rows[key] = {x.agent_id: {"answer": x.answer or {}, "segments": {}} for x in answers}
        # segments from the baseline answers' agents
        from app.models.agent import SpawnedAgent
        from app.services.measurement.probe import segments_for
        ids = list(rows["baseline"].keys())
        agents = (await db.execute(select(SpawnedAgent).where(SpawnedAgent.id.in_(ids)))).scalars().all() if ids else []
        for ag in agents:
            if ag.id in rows["baseline"]:
                rows["baseline"][ag.id]["segments"] = segments_for(ag)
        run_info = e.spec["lever_run"]
        s = shift(control_agg=base.aggregates, lever_agg=lev.aggregates, control_rows=rows["baseline"], lever_rows=rows["lever"],
                  candidate_id=run_info.get("candidate_id"), seed=int(e.seed or 0))
        lever_arm = next((v.get("spec", {}).get("lever") for v in (e.variants or []) if v.get("key") == "lever"), {}) or {}
        s["rule"] = {k: lever_arm.get(k) for k in ("rule_id", "lever", "description", "applies_to", "deltas", "bound", "reviewed_by", "reviewed_at")}
        s["covered"] = sum(1 for r in rows["baseline"].values() if applies(lever_arm, r.get("segments") or {}))
        s["journey_probe_id"] = run_info.get("journey_probe_id")
        results = dict(e.results or {})
        results["lever"] = s
        e.results = results
        flag_modified(e, "results")
        await db.commit()
