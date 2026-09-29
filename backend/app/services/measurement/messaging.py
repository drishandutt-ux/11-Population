"""Message testing against the panel (brief L7-06): framings shown to the twins stuck at a step,
the shift counted by cohort, backfire reported as prominently as a win.

The Lab's A/B tool already puts two framings in front of the same twins and pairs the answers.
What L7-06 adds is the frame around it:

  * **Who answers.** A message run is a within-subjects experiment on the Journey instrument
    over the twins at risk at one candidate's step (reached the 'from' step or beyond in the
    baseline run): a baseline arm and one arm per message, each arm the same twins answering the
    journey again having *read that message* (`spec.message`, shown in the user message by
    `probe.build_user_message` as something they have just seen — a stimulus, not a change in
    the world). Nothing about the twin is altered; no dial moves.
  * **The ranking** is counted from the arms: for each message the paired shift in conversion at
    the step (`levers.shift`) with its interval; the ones whose interval sits above zero rank
    first, then the indistinguishable ones by size, then the ones that hurt. Where the twins
    carry frame weights (L2-02) the weighted shift is counted beside the unweighted one
    (`stats.weighted_paired_lift`) and the run says so.
  * **Backfire has equal billing**: a message that lowers conversion overall, or lowers it for
    one deprivation band of 3+ paired twins while helping the rest, is flagged on the row, listed
    in `backfires`, opened in the sentence with *BACKFIRE:* and shown above the winner.
  * **What it is and is not.** The brief gates message testing on the same calibration as the
    lever run (L4-02 / L4-04). A message is a stimulus rather than a dial change, so the run is
    not refused; instead every result — the sentence, the record, the records block the report
    model reads and a FIGURE_RULES clause — carries the label **modelled reaction to a framing,
    not a forecast of uptake**. A forecast is the rule book's and the lever run's job.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select

from app.services.measurement import levers, stats

MAX_MESSAGES = 6
MAX_TEXT = 1500
MAX_LABEL = 60
MIN_BAND = 3          # a deprivation band counts toward a backfire flag only with this many paired twins

LABEL = "a modelled reaction to a framing, not a forecast of uptake"


# ── the messages ─────────────────────────────────────────────────────────────

def clean_messages(raw: Any) -> list[dict]:
    """`[{label, text}]` — text required, label defaulted from the text; blanks and duplicates dropped."""
    out: list[dict] = []
    seen: set[str] = set()
    for j, m in enumerate(raw if isinstance(raw, list) else [], 1):
        if isinstance(m, str):
            m = {"text": m}
        if not isinstance(m, dict):
            continue
        text = str(m.get("text") or "").strip()[:MAX_TEXT]
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        label = str(m.get("label") or "").strip()[:MAX_LABEL] or (text[:40].rstrip() + ("…" if len(text) > 40 else ""))
        out.append({"key": f"m{len(out) + 1}", "label": label, "text": text})
        if len(out) >= MAX_MESSAGES:
            break
    return out


def message_block(message: dict) -> str:
    """The framing as the twin reads it. A thing seen, not a change made — the twin decides what
    it does to them."""
    label = str(message.get("label") or "").strip()
    return ("A MESSAGE YOU HAVE JUST SEEN (this run asks how you react to it; nothing else about your life has changed):\n"
            + (f"[{label}] " if label else "") + str(message.get("text") or "").strip()
            + "\nTake it as you would if it really reached you — through whichever channel people like you actually see such things — "
              "no more persuasive than it would actually be. If it would not move you, say so through your answers.")


# ── the run ──────────────────────────────────────────────────────────────────

async def start(session_id: str, *, journey_probe_id: str, candidate_id: str, messages: Any, mode: str) -> dict:
    """Create the message run: a baseline arm plus one arm per message, over the twins at risk at
    the candidate's step. Returns `{experiment_id, messages, at_risk}` or `{error}`."""
    from app.core.config import get_settings
    from app.core.database import AsyncSessionLocal
    from app.models.measurement import Experiment, Probe, ProbeAnswer
    from app.services.measurement import instruments, probe as probe_svc
    from app.services.measurement.instruments.journey import stages_of
    from app.services.measurement.targeting import at_risk_ids

    msgs = clean_messages(messages)
    if not msgs:
        return {"error": "Nothing to test: write at least one message."}

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
        base_spec = {k: v for k, v in (base.spec or {}).items() if k not in ("seed", "lever", "nudge", "message")}
        base_seed = int(base.seed or 0)
    stages = stages_of(base_spec)
    ids = at_risk_ids(rows, stages, int(candidate.get("step") or 1))
    if len(ids) < 2:
        return {"error": "Fewer than two twins are at risk at this step; nothing can be tested."}
    flt = dict(base_spec.get("agent_filter") or {})
    flt["agent_ids"] = ids
    shared = {**base_spec, "agent_filter": flt}

    inst = instruments.get("journey")
    model = get_settings().agent_model("pro" if mode == "pro" else "fast")
    # Arm keys are short (`m1`, `m2` …): `probes.variant_key` is VARCHAR(48) in Postgres. The
    # baseline arm reuses the targeting baseline kind so the journey postprocess keeps only headcounts.
    variants = [{"key": "baseline", "label": "No message", "spec": {"targeting_baseline": True}}]
    for m in msgs:
        variants.append({"key": m["key"], "label": m["label"], "spec": {"message": m}})
    async with AsyncSessionLocal() as db:
        e = Experiment(
            id=str(uuid.uuid4()), session_id=session_id,
            name=f"Messages tested at {(candidate.get('from') or {}).get('label')} → {(candidate.get('to') or {}).get('label')}"[:160],
            design="within", instrument="journey", variants=variants,
            spec={**shared, "messaging": {"journey_probe_id": journey_probe_id, "candidate_id": candidate.get("id"), "messages": msgs, "at_risk": len(ids)}},
            seed=base_seed, model=model, status="queued",
        )
        db.add(e)
        for v in variants:
            spec = {**shared, **v["spec"], "seed": base_seed}
            db.add(Probe(id=str(uuid.uuid4()), session_id=session_id, instrument="journey", schema_id=inst.schema_id(), spec=spec, experiment_id=e.id,
                         variant_key=v["key"], seed=base_seed, model=model, prompt_hash=probe_svc.prompt_hash(inst, spec), status="queued"))
        await db.commit()
    return {"experiment_id": e.id, "messages": msgs, "at_risk": len(ids)}


async def run(experiment_id: str) -> None:
    from app.services.measurement.experiment import run_experiment
    await run_experiment(experiment_id)
    try:
        await attach_ranking(experiment_id)
    except Exception as e:  # noqa: BLE001
        print(f"[messaging] ranking failed for {experiment_id}: {type(e).__name__}: {e}")


# ── the ranking ──────────────────────────────────────────────────────────────

def _weighted(sh: dict, control_rows: dict[str, dict], arm_rows: dict[str, dict], stages: list[dict], k: int, weights: dict[str, float], seed: int) -> Optional[dict]:
    """The same paired shift at the step with each twin counted at its frame weight; None when
    nobody carries a weight other than 1."""
    if not weights or not any(abs(float(w) - 1.0) > 1e-6 for w in weights.values()):
        return None
    a, b = levers._through_flags(control_rows, stages, k), levers._through_flags(arm_rows, stages, k)
    ids = [x for x in a if x in b]
    if not ids:
        return None
    out = stats.weighted_paired_lift([(a[x], b[x]) for x in ids], [float(weights.get(x, 1.0)) for x in ids], seed=seed)
    return {"lift": out["mean"], "low": out["low"], "high": out["high"], "ess": out["ess"], "significant": bool(out["significant"])}


def rank(*, control_agg: dict, control_rows: dict[str, dict], arms: dict[str, tuple[dict, dict[str, dict]]], candidate_id: str, messages: list[dict],
         weights: Optional[dict[str, float]] = None, seed: int = 0) -> dict:
    """The messages ranked by the shift in conversion at the step, counted from the arms. `arms`
    maps a message key to `(arm_aggregates, arm_rows)`."""
    by_key = {m["key"]: m for m in messages}
    stages = control_agg.get("stages") or []
    out_rows: list[dict] = []
    weighted_any = False
    for key, (arm_agg, arm_rows) in arms.items():
        m = by_key.get(key) or {"key": key, "label": key, "text": ""}
        sh = levers.shift(control_agg=control_agg, lever_agg=arm_agg, control_rows=control_rows, lever_rows=arm_rows, candidate_id=candidate_id, seed=seed)
        if not sh.get("available"):
            out_rows.append({"key": key, "label": m["label"], "text": m.get("text") or "", "available": False, "reason": sh.get("reason")})
            continue
        conv = sh["conversion"]
        lift, low, high = float(conv["lift"]), float(conv["low"]), float(conv["high"])
        sig = bool(conv.get("significant"))
        direction = "helps" if lift > 0 else "hurts" if lift < 0 else "none"
        bands = (sh.get("segments") or {}).get("deprivation") or []
        backfire = []
        for b in bands:
            if int(b.get("n") or 0) < MIN_BAND:
                continue
            bh = float(b.get("high") or 0)
            # a band the message clearly lowers while it helps (or does nothing) overall
            if direction != "hurts" and bh < 0:
                backfire.append({"value": b["value"], "n": b["n"], "lift": float(b["lift"]), "low": float(b.get("low") or 0), "high": bh})
        k = int(sh.get("step") or 1) - 1
        w = _weighted(sh, control_rows, arm_rows, stages, k, weights or {}, seed) if stages else None
        weighted_any = weighted_any or bool(w)
        row = {
            "key": key, "label": m["label"], "text": m.get("text") or "", "available": True,
            "lift": round(lift, 4), "low": round(low, 4), "high": round(high, 4), "n": int(conv.get("n") or 0), "significant": sig,
            "direction": direction,      # what the message did to conversion at the step, overall
            "then": conv.get("then"), "now": conv.get("now"),
            "movement": sh.get("movement"), "end": sh.get("end"),
            "segments": sh.get("segments") or {},
            "bands": bands, "backfire": backfire,
            "hurts": bool(lift < 0 and sig),
            "weighted": w,
        }
        if sh.get("people"):
            p = sh["people"]
            row["people"] = {"moved": int(p["moved"]), "low": int(p["low"]), "high": int(p["high"]), "basis": p.get("basis") or ""}
        out_rows.append(row)
    # winners first (interval above zero, largest first), then the indistinguishable by size, then the ones that hurt
    ranked = sorted([r for r in out_rows if r.get("available")],
                    key=lambda r: (0 if r["significant"] and r["lift"] > 0 else 2 if r["hurts"] else 1, -r["lift"], -r["n"]))
    for k, r in enumerate(ranked, 1):
        r["rank"] = k
    unavailable = [r for r in out_rows if not r.get("available")]
    c0 = next((c for c in control_agg.get("candidates") or control_agg.get("transitions") or [] if c.get("id") == candidate_id), {}) or {}
    n_at_risk = ranked[0]["n"] if ranked else 0
    out = {
        "available": bool(ranked), "candidate_id": candidate_id, "step": c0.get("step"), "from": c0.get("from"), "to": c0.get("to"),
        "n": n_at_risk, "messages": ranked + unavailable,
        "any_significant": any(r["significant"] and r["lift"] > 0 for r in ranked),
        "weighted": weighted_any,
        "backfires": [{"key": r["key"], "label": r["label"], "hurts": r["hurts"], "lift": r["lift"], "bands": r["backfire"]} for r in ranked if r["backfire"] or r["hurts"]],
        "end_label": stages[-1].get("label") if stages else None,
        "label": LABEL,
    }
    out["sentence"] = sentence(out)
    return out


def _pp(x: Any) -> str:
    return f"{round(float(x or 0) * 100, 1):+.1f}"


def sentence(t: dict) -> str:
    if not t.get("available"):
        return "No message could be tested at this step."
    frm, to = (t.get("from") or {}).get("label"), (t.get("to") or {}).get("label")
    parts = []
    for r in [x for x in t["messages"] if x.get("available")][:6]:
        bit = (f"{r['rank']}. '{r['label']}': {_pp(r['lift'])} points of conversion (95% CI {_pp(r['low'])} to {_pp(r['high'])}"
               f"{', real' if r['significant'] else ', not distinguishable from zero'})")
        if r.get("weighted"):
            bit += f", weighted {_pp(r['weighted']['lift'])}"
        if r.get("people"):
            bit += f", ≈{r['people']['moved']:,} people"
        parts.append(bit)
    text = (f"Messages ranked by the shift in conversion at '{frm}' → '{to}' ({t.get('n')} twins at risk, each read every message in its own run): "
            + "; ".join(parts) + ".")
    bf = t.get("backfires") or []
    if bf:
        bits = []
        for b in bf:
            if b.get("hurts"):
                bits.append(f"'{b['label']}' lowers conversion overall ({_pp(b['lift'])})")
            for band in b.get("bands") or []:
                bits.append(f"'{b['label']}' lowers it for {band['value']} ({_pp(band['lift'])})")
        text += " BACKFIRE: " + "; ".join(bits) + "."
    else:
        text += " No message backfired overall or in any deprivation band of 3+ twins."
    if not t.get("any_significant"):
        text += " No message's shift is distinguishable from zero at this sample size."
    if t.get("weighted"):
        text += " Weighted shifts count each twin at its sampling-frame weight."
    text += f" This is {LABEL}."
    return text


async def attach_ranking(experiment_id: str) -> None:
    from sqlalchemy.orm.attributes import flag_modified
    from app.core.database import AsyncSessionLocal
    from app.models.agent import SpawnedAgent
    from app.models.measurement import Experiment, Probe, ProbeAnswer
    from app.services.measurement.probe import segments_for

    async with AsyncSessionLocal() as db:
        e = await db.get(Experiment, experiment_id)
        if not e or not (e.spec or {}).get("messaging"):
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
        weights: dict[str, float] = {}
        for ag in agents:
            if ag.id in rows["baseline"]:
                rows["baseline"][ag.id]["segments"] = segments_for(ag)
                weights[ag.id] = float(getattr(ag, "weight", None) or 1.0)
        info = e.spec["messaging"]
        msgs = info.get("messages") or []
        arms = {}
        for v in (e.variants or []):
            k = v.get("key") or ""
            if not ((v.get("spec") or {}).get("message")):
                continue
            p = probes.get(k)
            if p and (p.aggregates or {}).get("transitions"):
                arms[k] = (p.aggregates, rows.get(k) or {})
        t = rank(control_agg=base.aggregates, control_rows=rows["baseline"], arms=arms, candidate_id=info.get("candidate_id"), messages=msgs,
                 weights=weights, seed=int(e.seed or 0))
        t["journey_probe_id"] = info.get("journey_probe_id")
        results = dict(e.results or {})
        results["messaging"] = t
        e.results = results
        flag_modified(e, "results")
        await db.commit()
