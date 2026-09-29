"""Behaviour targeting (brief L7-05): which behaviour to change, answered with a ranking.

A candidate gap says who is stuck at a step and what stands in their way. The decision a
partnership then faces is *which behaviour do we try to change first?* This module answers
it by measurement rather than assertion:

  * The **behaviours** are the dials every twin already carries — first the question-specific
    dials the Studio chose for this session (`dynamic.<key>`: liner cost, space at home,
    formulary pressure …), plus any fixed dial the analyst adds (`friction.money_pain`).
  * A **targeting run** is a within-subjects experiment on the Journey instrument over the
    twins at risk at the candidate's step: a baseline arm, and one arm per behaviour in which
    that single dial is nudged by the same small number of points (`points`, default 2) for
    every twin, with nothing else changed and nothing described to the twin — the nudge is a
    disposition, not an event in the world.
  * The **ranking** is counted from the arms: for each behaviour the paired shift in conversion
    at the step (`levers.shift`), divided by the nudge → **movement per point**, with its
    interval. The sign says which way to push (a nudge up that lowers conversion means the
    behaviour should be pushed down). Behaviours whose interval excludes zero rank first, then
    by size of movement. **Backfire gets equal billing**: a behaviour that lowers conversion, or
    helps one deprivation band while hurting another, is flagged on the row and in the sentence,
    never buried.
  * What it is and is not: a **sensitivity of the modelled population** to each behaviour. It
    says which behaviour the twins respond to most per point, not that a real intervention moves
    that behaviour by that much — that is the calibration rule's job (L4-02 / L7-04). Every
    record carries that caveat and the report model is bound to quote the ranking as such.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select

from app.services.measurement import levers, stats

POINTS_DEFAULT, POINTS_MAX = 2, 3
MAX_BEHAVIOURS = 12
MIN_BAND = 3          # a deprivation band counts toward a backfire flag only with this many paired twins


# ── the menu ─────────────────────────────────────────────────────────────────

async def behaviours_for(session_id: str) -> dict:
    """What can be ranked: the session's question-specific dials (ticked by default) and the
    fixed dial vocabulary the analyst may add from."""
    from app.services.agents import dynamic_dials as dyn_mod
    dyn = await dyn_mod.for_session(session_id)
    return {
        "behaviours": [{"key": f"{dyn_mod.GROUP}.{d['key']}", "label": d.get("label") or d["key"], "group": dyn_mod.GROUP, "why": d.get("why") or "",
                        "low": d.get("low") or "", "high": d.get("high") or "", "question_specific": True} for d in dyn],
        "fixed": levers.dial_keys(),
        "points_default": POINTS_DEFAULT, "points_max": POINTS_MAX, "max_behaviours": MAX_BEHAVIOURS,
    }


def _label_for(key: str, menu: dict) -> tuple[str, str, bool]:
    """(label, group, question_specific) for a behaviour key."""
    for b in menu.get("behaviours") or []:
        if b["key"] == key:
            return b["label"], b["group"], True
    group, _, dial = key.partition(".")
    return dial.replace("_", " "), group, False


def valid_keys(keys: list[str], menu: dict) -> list[str]:
    """The behaviour keys that exist: question-specific ones from the menu, fixed ones from the dial schema."""
    fixed = menu.get("fixed") or {}
    ok = {b["key"] for b in menu.get("behaviours") or []}
    out: list[str] = []
    for k in keys:
        k = str(k or "").strip()
        if not k or k in out:
            continue
        group, _, dial = k.partition(".")
        if k in ok or (group in fixed and dial in fixed[group]):
            out.append(k)
    return out[:MAX_BEHAVIOURS]


def nudge_spec(key: str, points: int, menu: dict) -> dict:
    label, group, qs = _label_for(key, menu)
    return {"dial": key, "points": int(points), "label": label, "group": group, "question_specific": qs}


# ── the run ──────────────────────────────────────────────────────────────────

def at_risk_ids(rows: list[dict], stages: list[dict], step: int) -> list[str]:
    """The twins who reached the candidate's 'from' step (1-based `step`) or further in the
    baseline run — the only ones a nudge at that step can move."""
    from app.services.measurement.instruments.journey import _index
    idx = _index(stages)
    k = int(step) - 1
    return sorted(r["agent_id"] for r in rows if idx.get((r.get("answer") or {}).get("reached"), -1) >= k)


async def start(session_id: str, *, journey_probe_id: str, candidate_id: str, behaviours: Optional[list[str]], points: Optional[int], mode: str) -> dict:
    """Create the targeting run: a baseline arm plus one arm per behaviour, over the twins at
    risk at the candidate's step. Returns `{experiment_id, behaviours, points}` or `{error}`."""
    from app.core.config import get_settings
    from app.core.database import AsyncSessionLocal
    from app.models.measurement import Experiment, Probe, ProbeAnswer
    from app.services.measurement import instruments, probe as probe_svc
    from app.services.measurement.instruments.journey import stages_of

    menu = await behaviours_for(session_id)
    keys = valid_keys(behaviours if behaviours else [b["key"] for b in menu["behaviours"]], menu)
    if not keys:
        return {"error": "Nothing to rank: this session has no question-specific dials and no fixed dial was named."}
    pts = max(1, min(POINTS_MAX, int(points or POINTS_DEFAULT)))

    async with AsyncSessionLocal() as db:
        base = await db.get(Probe, journey_probe_id)
        if not base or base.session_id != session_id or base.instrument != "journey" or base.status != "complete":
            return {"error": "The journey run was not found or is not complete."}
        agg = base.aggregates or {}
        candidate = next((c for c in (agg.get("candidates") or []) if c.get("id") == candidate_id or f"{base.id}:{c.get('id')}" == candidate_id), None)
        if not candidate:
            return {"error": "That candidate is not on this journey run."}
        answers = (await db.execute(select(ProbeAnswer).where(ProbeAnswer.probe_id == base.id))).scalars().all()
        rows = [{"agent_id": a.agent_id, "answer": a.answer or {}} for a in answers]
        base_spec = {k: v for k, v in (base.spec or {}).items() if k not in ("seed", "lever", "nudge")}
        base_seed = int(base.seed or 0)
    stages = stages_of(base_spec)
    ids = at_risk_ids(rows, stages, int(candidate.get("step") or 1))
    if len(ids) < 2:
        return {"error": "Fewer than two twins are at risk at this step; nothing can be ranked."}
    flt = dict(base_spec.get("agent_filter") or {})
    flt["agent_ids"] = ids
    shared = {**base_spec, "agent_filter": flt}

    inst = instruments.get("journey")
    model = get_settings().agent_model("pro" if mode == "pro" else "fast")
    # Arm keys are short (`n1`, `n2` …): `probes.variant_key` is VARCHAR(48) in Postgres and a
    # behaviour key such as `dynamic.deprivation_support_access` would not fit. The behaviour
    # itself travels in the arm's `spec.nudge.dial`.
    variants = [{"key": "baseline", "label": "As things are", "spec": {"targeting_baseline": True}}]
    for j, k in enumerate(keys, 1):
        n = nudge_spec(k, pts, menu)
        variants.append({"key": f"n{j}", "label": f"{n['label']} {pts:+d}", "spec": {"nudge": n}})
    async with AsyncSessionLocal() as db:
        e = Experiment(
            id=str(uuid.uuid4()), session_id=session_id,
            name=f"Behaviours ranked at {(candidate.get('from') or {}).get('label')} → {(candidate.get('to') or {}).get('label')}"[:160],
            design="within", instrument="journey", variants=variants,
            spec={**shared, "targeting": {"journey_probe_id": journey_probe_id, "candidate_id": candidate.get("id"), "points": pts, "behaviours": keys, "at_risk": len(ids)}},
            seed=base_seed, model=model, status="queued",
        )
        db.add(e)
        for v in variants:
            spec = {**shared, **v["spec"], "seed": base_seed}
            db.add(Probe(id=str(uuid.uuid4()), session_id=session_id, instrument="journey", schema_id=inst.schema_id(), spec=spec, experiment_id=e.id,
                         variant_key=v["key"], seed=base_seed, model=model, prompt_hash=probe_svc.prompt_hash(inst, spec), status="queued"))
        await db.commit()
    return {"experiment_id": e.id, "behaviours": keys, "points": pts, "at_risk": len(ids)}


async def run(experiment_id: str) -> None:
    from app.services.measurement.experiment import run_experiment
    await run_experiment(experiment_id)
    try:
        await attach_ranking(experiment_id)
    except Exception as e:  # noqa: BLE001
        print(f"[targeting] ranking failed for {experiment_id}: {type(e).__name__}: {e}")


# ── the ranking ──────────────────────────────────────────────────────────────

def _sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def rank(*, control_agg: dict, control_rows: dict[str, dict], arms: dict[str, tuple[dict, dict[str, dict]]], candidate_id: str, points: int,
         menu: Optional[dict] = None, seed: int = 0) -> dict:
    """The behaviours ranked by movement per point, counted from the arms. `arms` maps a
    behaviour key to `(arm_aggregates, arm_rows)`."""
    menu = menu or {}
    out_rows: list[dict] = []
    for key, (arm_agg, arm_rows) in arms.items():
        sh = levers.shift(control_agg=control_agg, lever_agg=arm_agg, control_rows=control_rows, lever_rows=arm_rows, candidate_id=candidate_id, seed=seed)
        label, group, qs = _label_for(key, menu)
        if not sh.get("available"):
            out_rows.append({"key": key, "label": label, "group": group, "question_specific": qs, "available": False, "reason": sh.get("reason")})
            continue
        conv = sh["conversion"]
        lift, low, high = float(conv["lift"]), float(conv["low"]), float(conv["high"])
        per = lift / points
        direction = "up" if lift > 0 else "down" if lift < 0 else "none"
        # backfire by band: a band whose interval sits on the other side of zero from the overall direction
        bands = (sh.get("segments") or {}).get("deprivation") or []
        backfire = []
        for b in bands:
            if int(b.get("n") or 0) < MIN_BAND:
                continue
            bl, bh = float(b.get("low") or 0), float(b.get("high") or 0)
            if direction == "up" and bh < 0 or direction == "down" and bl > 0:
                backfire.append({"value": b["value"], "n": b["n"], "lift": float(b["lift"]), "per_point": round(float(b["lift"]) / points, 4)})
        row = {
            "key": key, "label": label, "group": group, "question_specific": qs, "available": True,
            "points": points, "lift": round(lift, 4), "low": round(low, 4), "high": round(high, 4), "n": int(conv.get("n") or 0),
            "significant": bool(conv.get("significant")),
            "per_point": round(per, 4), "per_point_low": round(low / points, 4), "per_point_high": round(high / points, 4),
            "direction": direction,      # which way the nudge moved conversion; the way to PUSH the behaviour to help
            "then": conv.get("then"), "now": conv.get("now"),
            "movement": sh.get("movement"), "end": sh.get("end"),
            "bands": bands, "backfire": backfire,
            "hurts": bool(lift < 0 and conv.get("significant")),   # pushed up, it lowered conversion (so: push it down, or leave it)
        }
        if sh.get("people"):
            p = sh["people"]
            row["people"] = {"per_point": int(round(float(p["moved"]) / points)), "at_points": int(p["moved"]), "low": int(p["low"]), "high": int(p["high"]), "basis": p.get("basis") or ""}
        out_rows.append(row)
    ranked = sorted([r for r in out_rows if r.get("available")], key=lambda r: (0 if r["significant"] else 1, -abs(r["per_point"]), -r["n"]))
    for k, r in enumerate(ranked, 1):
        r["rank"] = k
    unavailable = [r for r in out_rows if not r.get("available")]
    c0 = next((c for c in control_agg.get("candidates") or control_agg.get("transitions") or [] if c.get("id") == candidate_id), {}) or {}
    stages = control_agg.get("stages") or []
    n_at_risk = ranked[0]["n"] if ranked else 0
    out = {
        "available": bool(ranked), "candidate_id": candidate_id, "step": c0.get("step"), "from": c0.get("from"), "to": c0.get("to"),
        "points": points, "n": n_at_risk, "behaviours": ranked + unavailable,
        "any_significant": any(r["significant"] for r in ranked),
        "backfires": [{"key": r["key"], "label": r["label"], "direction": r["direction"], "bands": r["backfire"], "hurts": r["hurts"]} for r in ranked if r["backfire"] or r["hurts"]],
        "end_label": stages[-1].get("label") if stages else None,
    }
    out["sentence"] = sentence(out)
    return out


def _push(r: dict) -> str:
    return {"up": "push up", "down": "push down"}.get(r.get("direction"), "no direction")


def sentence(t: dict) -> str:
    if not t.get("available"):
        return "No behaviour could be ranked at this step."
    frm, to = (t.get("from") or {}).get("label"), (t.get("to") or {}).get("label")
    parts = []
    for r in [x for x in t["behaviours"] if x.get("available")][:6]:
        pp = round(float(r["per_point"]) * 100, 1)
        lo, hi = round(float(r["per_point_low"]) * 100, 1), round(float(r["per_point_high"]) * 100, 1)
        parts.append(f"{r['rank']}. {_push(r)} '{r['label']}': {pp:+.1f} points of conversion per dial point (95% CI {lo:+.1f} to {hi:+.1f}"
                     f"{', real' if r['significant'] else ', not distinguishable from zero'})")
    text = (f"Behaviours ranked by movement per point at '{frm}' → '{to}' ({t.get('n')} twins at risk, each behaviour nudged by {t.get('points')} point"
            f"{'s' if t.get('points') != 1 else ''}): " + "; ".join(parts) + ".")
    bf = t.get("backfires") or []
    if bf:
        bits = []
        for b in bf:
            if b.get("hurts"):
                bits.append(f"raising '{b['label']}' lowers conversion overall")
            for band in b.get("bands") or []:
                bits.append(f"pushing '{b['label']}' {b['direction']} lowers conversion for {band['value']} ({round(float(band['per_point']) * 100, 1):+.1f} per point)")
        text += " BACKFIRE: " + "; ".join(bits) + "."
    else:
        text += " No behaviour backfired overall or in any deprivation band of 3+ twins."
    if not t.get("any_significant"):
        text += " No behaviour's movement is distinguishable from zero at this sample size."
    text += " This is the modelled population's sensitivity to each behaviour, not the effect of any intervention."
    return text


async def attach_ranking(experiment_id: str) -> None:
    from sqlalchemy.orm.attributes import flag_modified
    from app.core.database import AsyncSessionLocal
    from app.models.agent import SpawnedAgent
    from app.models.measurement import Experiment, Probe, ProbeAnswer
    from app.services.measurement.probe import segments_for

    async with AsyncSessionLocal() as db:
        e = await db.get(Experiment, experiment_id)
        if not e or not (e.spec or {}).get("targeting"):
            return
        probes = {p.variant_key: p for p in (await db.execute(select(Probe).where(Probe.experiment_id == experiment_id))).scalars().all()}
        base = probes.get("baseline")
        if not base or not (base.aggregates or {}).get("transitions"):
            return
        rows: dict[str, dict[str, dict]] = {}
        for key, p in probes.items():
            answers = (await db.execute(select(ProbeAnswer).where(ProbeAnswer.probe_id == p.id))).scalars().all()
            rows[key] = {x.agent_id: {"answer": x.answer or {}, "segments": {}} for x in answers}
        ids = list(rows["baseline"].keys())
        agents = (await db.execute(select(SpawnedAgent).where(SpawnedAgent.id.in_(ids)))).scalars().all() if ids else []
        for ag in agents:
            if ag.id in rows["baseline"]:
                rows["baseline"][ag.id]["segments"] = segments_for(ag)
        info = e.spec["targeting"]
        menu = await behaviours_for(e.session_id)
        arms = {}
        for v in (e.variants or []):
            k = v.get("key") or ""
            dial = str(((v.get("spec") or {}).get("nudge") or {}).get("dial") or "")
            if not dial:
                continue
            p = probes.get(k)
            if p and (p.aggregates or {}).get("transitions"):
                arms[dial] = (p.aggregates, rows.get(k) or {})
        t = rank(control_agg=base.aggregates, control_rows=rows["baseline"], arms=arms, candidate_id=info.get("candidate_id"), points=int(info.get("points") or POINTS_DEFAULT),
                 menu=menu, seed=int(e.seed or 0))
        t["journey_probe_id"] = info.get("journey_probe_id")
        results = dict(e.results or {})
        results["targeting"] = t
        e.results = results
        flag_modified(e, "results")
        await db.commit()
