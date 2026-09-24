"""Experiments — A/B/n tests built on the probe primitive.

An experiment is a set of variants (two offers, two prices, two messages) and ONE instrument.
Each variant becomes an ordinary probe carrying the experiment's id, so every arm is a full
probe result on its own. What this module adds is the comparison:

- **within-subjects** (default): every agent answers every variant, in separate calls with no
  memory of the other arms (the runner hides sibling answers from the agent's history). The
  lift is a paired difference — each agent is its own control — so the interval is tight even
  at 50 agents. This is the cheapest credible design.
- **between-subjects**: the population is split by seed into disjoint groups, one per variant.
  Use it when the variants are not independent (a price war, a rumour) or when you want each
  agent to see exactly one offer.

The instrument declares which numbers get compared (`Instrument.metrics`), which answer field
counts as a decision (`decision_key`, for "who flipped") and which explains it (`driver_key`,
for coding the reasons). This module knows nothing about purchase intent in particular.
"""
from __future__ import annotations

import asyncio
import random
import traceback
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.redis_client import publish, session_channel
from app.models.agent import SpawnedAgent
from app.models.measurement import Experiment, Probe, ProbeAnswer
from app.services.measurement import instruments, stats
from app.services.measurement.probe import (
    PROBE_CONCURRENCY, BASE_SPLIT_KEYS, _select_agents, answered, run_probe, segments_for, split_keys, split_label,
)

DESIGNS = ("within", "between", "choice")
CHOICE_ARM = "all"   # the single arm of a choose-between-them experiment
MIN_VARIANTS, MAX_VARIANTS = 2, 6
SEGMENT_KEYS = BASE_SPLIT_KEYS   # plus this session's dynamic dials, from the rows themselves
SEGMENT_ITERATIONS = 600   # per-bucket bootstraps are many and small; this keeps analysis fast
MAX_FLIP_ROWS = 60


# ── analysis (pure Python; no I/O) ────────────────────────────────────────────

def _fmt(value: float, fmt: str, currency: str = "", *, signed: bool = False) -> str:
    sym = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency, "")
    sign = "+" if signed and value > 0 else ("−" if signed and value < 0 else "")
    v = abs(value) if signed else value
    if fmt == "share":
        return f"{sign}{round(v * 100)} points" if signed else f"{round(v * 100)}%"
    if fmt == "money":
        return f"{sign}{sym}{v:,.2f}"
    return f"{sign}{v:,.2f}".rstrip("0").rstrip(".")


def _level(values: list[float], fmt: str) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _lift(design: str, a: list[float], b: list[float], seed: int, *, iterations: int = 2000) -> dict:
    if design == "between":
        return stats.unpaired_lift(a, b, iterations=iterations, seed=seed)
    out = stats.paired_lift(list(zip(a, b)), iterations=iterations, seed=seed)
    return {"mean": out["mean"], "low": out["low"], "high": out["high"], "n": out["n"],
            "significant": out["significant"]}


def _metric_series(design: str, metric, control_rows: dict, variant_rows: dict) -> tuple[list[float], list[float], list[str]]:
    """Per-metric value lists for the two arms. Within-subjects: aligned by agent, only agents
    with a usable value in BOTH arms. Between: each arm on its own."""
    if design == "between":
        a = [v for v in (metric.value(r["answer"]) for r in control_rows.values()) if v is not None]
        b = [v for v in (metric.value(r["answer"]) for r in variant_rows.values()) if v is not None]
        return a, b, []
    a, b, ids = [], [], []
    for agent_id in sorted(set(control_rows) & set(variant_rows)):
        va = metric.value(control_rows[agent_id]["answer"])
        vb = metric.value(variant_rows[agent_id]["answer"])
        if va is None or vb is None:
            continue
        a.append(va); b.append(vb); ids.append(agent_id)
    return a, b, ids


def _flips(instrument, control_rows: dict, variant_rows: dict) -> Optional[dict]:
    """Agents whose decision changed between the control and this variant, with both reasons
    and (if the instrument names one) the driver behind the new answer."""
    key = instrument.decision_key
    if not key:
        return None
    paired = sorted(set(control_rows) & set(variant_rows))
    rows = []
    for agent_id in paired:
        ca, va = control_rows[agent_id], variant_rows[agent_id]
        frm, to = ca["answer"].get(key), va["answer"].get(key)
        if frm == to:
            continue
        rows.append({
            "agent_id": agent_id,
            "name": va["agent"].get("name", ""),
            "role": va["agent"].get("role", ""),
            "from": frm, "to": to,
            "reasoning_control": ca["answer"].get("reasoning", ""),
            "reasoning_variant": va["answer"].get("reasoning", ""),
            "driver": va["answer"].get(instrument.driver_key, "") if instrument.driver_key else "",
            "segments": va.get("segments") or {},
        })
    share = stats.wilson(len(rows), len(paired))
    # Every paired agent's movement, stayers included — what the flow diagram draws.
    matrix: dict[tuple, int] = {}
    for agent_id in paired:
        k = (str(control_rows[agent_id]["answer"].get(key)), str(variant_rows[agent_id]["answer"].get(key)))
        matrix[k] = matrix.get(k, 0) + 1
    return {
        "n": len(rows),
        "paired": len(paired),
        "share": share,
        "matrix": sorted(({"from": f, "to": t, "count": c} for (f, t), c in matrix.items()),
                         key=lambda d: (-d["count"], d["from"], d["to"])),
        "direction": stats.distribution([f"{r['from']} → {r['to']}" for r in rows]),
        "reasons": stats.distribution([r["driver"] for r in rows if r["driver"]]) if instrument.driver_key else [],
        "rows": rows[:MAX_FLIP_ROWS],
    }


def _segment_lifts(design: str, metric, control_rows: dict, variant_rows: dict, seed: int) -> dict:
    """The primary metric's lift inside every segment bucket — the heat-map. Thin buckets are
    flagged, not hidden."""
    out: dict[str, list[dict]] = {}
    for key in split_keys(list(control_rows.values()) + list(variant_rows.values())):
        buckets: dict[str, tuple[dict, dict]] = {}
        for agent_id, row in control_rows.items():
            label = (row.get("segments") or {}).get(key)
            if label is None:
                continue
            c, v = buckets.setdefault(str(label), ({}, {}))
            c[agent_id] = row
        for agent_id, row in variant_rows.items():
            label = (row.get("segments") or {}).get(key)
            if label is None:
                continue
            c, v = buckets.setdefault(str(label), ({}, {}))
            v[agent_id] = row
        rows = []
        for label, (c, v) in buckets.items():
            a, b, _ = _metric_series(design, metric, c, v)
            n = len(a) if design == "within" else min(len(a), len(b))
            if n == 0:
                continue
            lift = _lift(design, a, b, seed, iterations=SEGMENT_ITERATIONS)
            rows.append({
                "segment": key, "value": label, "n": lift["n"], "thin": n < 3,
                "control": _level(a, metric.format), "variant": _level(b, metric.format),
                "mean": lift["mean"], "low": lift["low"], "high": lift["high"],
                "significant": lift["significant"],
            })
        rows.sort(key=lambda d: (-d["n"], d["value"]))
        if rows:
            out[key] = rows
    return out


def _sentence(label_a: str, label_b: str, metric, lift: dict, level_a: float, level_b: float,
              currency: str, flips: Optional[dict], segments: dict) -> str:
    """One plain-language line the report generator can quote."""
    delta = _fmt(lift["mean"], metric.format, currency, signed=True)
    lo, hi = _fmt(lift["low"], metric.format, currency, signed=True), _fmt(lift["high"], metric.format, currency, signed=True)
    name = metric.label.lower()
    if not lift.get("significant"):
        return (
            f"No reliable difference between {label_a} and {label_b} on {name}: {label_b} is {delta} "
            f"({_fmt(level_b, metric.format, currency)} vs {_fmt(level_a, metric.format, currency)}), "
            f"but the 95% interval ({lo} to {hi}) includes zero."
        )
    winner, loser = (label_b, label_a) if lift["mean"] > 0 else (label_a, label_b)
    s = (f"{winner} beats {loser} on {name} by {delta.lstrip('+−')} "
         f"({_fmt(level_b, metric.format, currency)} vs {_fmt(level_a, metric.format, currency)}; 95% CI {lo} to {hi})")
    if flips and flips.get("reasons"):
        top = flips["reasons"][0]
        s += f", driven by {top['value']} among the {flips['n']} who changed their answer"
    # Where the effect does not hold: solid buckets whose interval includes zero, or that reverse.
    gone: dict[str, list[str]] = {}
    reversed_: dict[str, list[str]] = {}
    for key, rows in segments.items():
        for r in rows:
            if r["thin"]:
                continue
            if (r["mean"] > 0) != (lift["mean"] > 0) and r["significant"]:
                reversed_.setdefault(key, []).append(r["value"])
            elif not r["significant"]:
                gone.setdefault(key, []).append(r["value"])
    if reversed_:
        s += f"; the effect reverses for {_bucket_list(reversed_)}"
    elif gone:
        s += f"; the effect is not reliable for {_bucket_list(gone)}"
    return s + "."


_SEGMENT_LABELS = {
    "stance": "stance", "age_band": "age", "humanity_band": "humanity band",
    "purchase_intent_prior": "purchase-intent prior",
}


def _segment_label(key: str) -> str:
    """What a bucket is a bucket OF, in the sentence — dynamic dials read as their own name."""
    return _SEGMENT_LABELS.get(key) or split_label(key)


def _bucket_list(by_key: dict[str, list[str]], limit: int = 3) -> str:
    """'direct and neutral stance, 45-54 age' — the bucket AND what it is a bucket of."""
    parts = []
    for key, values in list(by_key.items())[:limit]:
        vals = values[:3]
        joined = " and ".join(vals) if len(vals) <= 2 else ", ".join(vals[:-1]) + " and " + vals[-1]
        parts.append(f"{joined} {_segment_label(key)}")
    return "; ".join(parts)


def analyse(instrument, design: str, variants: list[dict], arms: dict[str, dict[str, dict]], seed: int) -> dict:
    """Compare every variant with the control.

    `arms` is {variant_key: {agent_id: row}} where row is {agent_id, agent, answer, segments}
    exactly as the probe runner produces it."""
    control = variants[0]
    control_rows = arms.get(control["key"], {})
    primary = instrument.primary_metric()
    comparisons = []
    for variant in variants[1:]:
        variant_rows = arms.get(variant["key"], {})
        currency = (variant.get("spec") or {}).get("currency") or (control.get("spec") or {}).get("currency") or ""
        metrics = []
        for metric in instrument.metrics:
            a, b, _ = _metric_series(design, metric, control_rows, variant_rows)
            lift = _lift(design, a, b, seed) if a and b else {"mean": 0.0, "low": 0.0, "high": 0.0, "n": 0, "significant": False}
            metrics.append({
                "key": metric.key, "label": metric.label, "format": metric.format,
                "primary": metric is primary, "currency": currency if metric.format == "money" else "",
                "control": _level(a, metric.format), "variant": _level(b, metric.format),
                "lift": lift,
            })
        flips = _flips(instrument, control_rows, variant_rows) if design == "within" else None
        segments = _segment_lifts(design, primary, control_rows, variant_rows, seed) if primary else {}
        prim = next((m for m in metrics if m["primary"]), metrics[0] if metrics else None)
        n_paired = len(set(control_rows) & set(variant_rows)) if design == "within" else None
        comparisons.append({
            "variant": variant["key"], "label": variant.get("label") or variant["key"],
            "control": control["key"], "control_label": control.get("label") or control["key"],
            "n": n_paired if design == "within" else (prim["lift"]["n"] if prim else 0),
            "metrics": metrics,
            "flips": flips,
            "segments": segments,
            "sentence": _sentence(
                control.get("label") or control["key"], variant.get("label") or variant["key"],
                primary, prim["lift"], prim["control"], prim["variant"], currency, flips, segments,
            ) if prim and primary else "",
        })

    # The verdict is about the best variant against the control on the primary metric.
    verdict = ""
    if comparisons:
        best = max(comparisons, key=lambda c: next((m["lift"]["mean"] for m in c["metrics"] if m["primary"]), 0))
        verdict = best["sentence"]
        if len(comparisons) > 1:
            others = [c["label"] for c in comparisons if c is not best]
            verdict += f" ({best['label']} is the strongest of {len(comparisons)} variants; also tested: {', '.join(others)}.)"

    return {
        "design": design,
        "instrument": instrument.key,
        "control": control["key"],
        "primary_metric": primary.key if primary else "",
        "arms": [
            {"key": v["key"], "label": v.get("label") or v["key"], "n": len(arms.get(v["key"], {}))}
            for v in variants
        ],
        "comparisons": comparisons,
        "verdict": verdict,
    }


# ── choice design ─────────────────────────────────────────────────────────────

def compose_choice_spec(instrument, variants: list[dict], shared: dict, question: str, seed: int) -> dict:
    """One probe for the whole comparison: every variant's material, labelled, in one stimulus."""
    parts = []
    for v in variants:
        material = str((v.get("spec") or {}).get(instrument.stimulus_key) or "").strip()
        price = (v.get("spec") or {}).get("price")
        currency = (v.get("spec") or {}).get("currency", "GBP")
        sym = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency, "")
        head = f"OPTION {v['key']} — {v.get('label') or v['key']}"
        if price:
            head += f" (price: {sym}{float(price):g})"
        parts.append(f"{head}\n{material}")
    return {
        **{k: val for k, val in shared.items() if k not in ("price", "currency")},
        "stimulus": "\n\n".join(parts),
        "question": question or instrument.question,
        "option_keys": [v["key"] for v in variants],
        "option_labels": {v["key"]: (v.get("label") or v["key"]) for v in variants},
        "seed": seed,
    }


def choice_results(variants: list[dict], probe: Probe) -> dict:
    agg = dict(probe.aggregates or {})
    pref = {p["key"]: p for p in agg.get("preference") or []}
    return {
        "design": "choice",
        "instrument": "choice",
        "control": variants[0]["key"],
        "primary_metric": "preference",
        "arms": [{"key": v["key"], "label": v.get("label") or v["key"], "n": pref.get(v["key"], {}).get("successes", 0)} for v in variants],
        "comparisons": [],
        "preference": agg.get("preference") or [],
        "head_to_head": agg.get("head_to_head") or [],
        "clear_winner": bool(agg.get("clear_winner")),
        "winner": agg.get("winner"),
        "n": agg.get("n", 0),
        "verdict": agg.get("sentence", ""),
        "probes": {CHOICE_ARM: probe.id},
    }


# ── the run ───────────────────────────────────────────────────────────────────

async def _set(experiment_id: str, **fields) -> None:
    async with AsyncSessionLocal() as db:
        exp = await db.get(Experiment, experiment_id)
        if not exp:
            return
        for k, v in fields.items():
            setattr(exp, k, v)
        await db.commit()


async def _arm_rows(db, probe_id: str) -> dict[str, dict]:
    """One arm's answers by agent. A twin that said the question was not theirs to answer
    (brief L3-06) is left out: a lift must be measured on people who actually answered both
    arms, not on a refusal treated as a value."""
    rows = (await db.execute(
        select(ProbeAnswer, SpawnedAgent)
        .join(SpawnedAgent, SpawnedAgent.id == ProbeAnswer.agent_id, isouter=True)
        .where(ProbeAnswer.probe_id == probe_id)
    )).all()
    out = {}
    for a, ag in rows:
        if not answered({"answer": a.answer or {}}):
            continue
        out[a.agent_id] = {
            "agent_id": a.agent_id,
            "agent": {"name": getattr(ag, "name", ""), "role": getattr(ag, "role", ""),
                      "avatar_color": getattr(ag, "avatar_color", "")},
            "answer": a.answer or {},
            "segments": segments_for(ag) if ag else {},
        }
    return out


def split_between(agents: list[SpawnedAgent], k: int, seed: int) -> list[list[str]]:
    """Disjoint, seeded, equal-as-possible groups of agent ids — one per variant."""
    ids = sorted(a.id for a in agents)
    random.Random(seed).shuffle(ids)
    return [ids[i::k] for i in range(k)]


async def run_experiment(experiment_id: str) -> None:
    """Background task: run every arm, then compare them."""
    try:
        async with AsyncSessionLocal() as db:
            exp = await db.get(Experiment, experiment_id)
            if not exp:
                return
            probes = (await db.execute(
                select(Probe).where(Probe.experiment_id == experiment_id).order_by(Probe.created_at)
            )).scalars().all()
            agents = (await db.execute(
                select(SpawnedAgent).where(SpawnedAgent.session_id == exp.session_id)
            )).scalars().all()
            session_id, design, seed, model = exp.session_id, exp.design, exp.seed, exp.model
            variants = list(exp.variants or [])
            shared = dict(exp.spec or {})
            by_key = {p.variant_key: p for p in probes}

            instrument = instruments.get(exp.instrument)
            if not instrument or (design != "choice" and not instrument.supports_experiments()):
                exp.status, exp.error = "failed", f"instrument '{exp.instrument}' cannot be run as an experiment"
                exp.completed_at = datetime.utcnow()
                await db.commit()
                return

            chosen = _select_agents(list(agents), shared, seed)
            if design == "between":
                groups = split_between(chosen, len(variants), seed)
                for variant, group in zip(variants, groups):
                    p = by_key.get(variant["key"])
                    if p:
                        spec = dict(p.spec or {})
                        flt = dict(spec.get("agent_filter") or {})
                        flt["agent_ids"] = group
                        spec["agent_filter"] = flt
                        p.spec = spec
            exp.status = "running"
            exp.agent_count = len(chosen)
            await db.commit()
            probe_ids = ([by_key[CHOICE_ARM].id] if CHOICE_ARM in by_key else []) if design == "choice" \
                else [by_key[v["key"]].id for v in variants if v["key"] in by_key]

        if not chosen:
            await _set(experiment_id, status="failed", error="no agents matched the filter", completed_at=datetime.utcnow())
            await publish(session_channel(session_id), {"type": "experiment_complete", "experiment_id": experiment_id, "status": "failed"})
            return

        await publish(session_channel(session_id), {
            "type": "experiment_started", "experiment_id": experiment_id,
            "probe_ids": probe_ids, "agent_count": len(chosen), "design": design,
        })

        # Every arm at once, sharing one probe's worth of concurrency between them. Arms are
        # independent calls with no memory of each other, so order carries no information.
        per_arm = max(4, PROBE_CONCURRENCY // max(1, len(probe_ids)))
        await asyncio.gather(*(run_probe(pid, concurrency=per_arm) for pid in probe_ids))

        # Population-level coding runs ONCE across every arm, so themes are shared between them.
        arm_instrument = instruments.get("choice") if design == "choice" else instrument
        if arm_instrument and arm_instrument.postprocess:
            try:
                await arm_instrument.postprocess(probe_ids, model)
            except Exception as e:  # noqa: BLE001
                print(f"[experiment] postprocess failed: {type(e).__name__}: {e}")

        if design == "choice":
            async with AsyncSessionLocal() as db:
                probe = await db.get(Probe, probe_ids[0])
            if not probe or probe.status == "failed" or not (probe.aggregates or {}).get("n"):
                await _set(experiment_id, status="failed", error=(probe.error if probe else None) or "the choice probe produced no answers",
                           completed_at=datetime.utcnow())
                await publish(session_channel(session_id), {"type": "experiment_complete", "experiment_id": experiment_id, "status": "failed"})
                return
            results = choice_results(variants, probe)
            status = "complete" if probe.status == "complete" else "stopped"
            await _set(experiment_id, status=status, results=results, completed_at=datetime.utcnow())
            await publish(session_channel(session_id), {
                "type": "experiment_complete", "experiment_id": experiment_id, "status": status,
                "verdict": results.get("verdict", ""),
            })
            print(f"[experiment] {experiment_id}: {status} — {results.get('verdict', '')[:120]}")
            return

        async with AsyncSessionLocal() as db:
            probes = (await db.execute(select(Probe).where(Probe.id.in_(probe_ids)))).scalars().all()
            by_id = {p.id: p for p in probes}
            arms: dict[str, dict[str, dict]] = {}
            for v in variants:
                p = by_key.get(v["key"])
                if p and p.id in by_id:
                    arms[v["key"]] = await _arm_rows(db, p.id)

        statuses = {by_id[pid].status for pid in probe_ids if pid in by_id}
        if "failed" in statuses and all(not arms.get(v["key"]) for v in variants):
            await _set(experiment_id, status="failed", error="every arm failed", completed_at=datetime.utcnow())
            await publish(session_channel(session_id), {"type": "experiment_complete", "experiment_id": experiment_id, "status": "failed"})
            return

        results = analyse(instrument, design, variants, arms, seed)
        results["probes"] = {v["key"]: by_key[v["key"]].id for v in variants if v["key"] in by_key}
        status = "complete" if statuses <= {"complete"} else "stopped"
        await _set(experiment_id, status=status, results=results, completed_at=datetime.utcnow())
        await publish(session_channel(session_id), {
            "type": "experiment_complete", "experiment_id": experiment_id, "status": status,
            "verdict": results.get("verdict", ""),
        })
        print(f"[experiment] {experiment_id}: {status} — {results.get('verdict', '')[:120]}")

    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        await _set(experiment_id, status="failed", error=f"{type(e).__name__}: {e}", completed_at=datetime.utcnow())
