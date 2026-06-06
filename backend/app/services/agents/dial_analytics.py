"""Population-level aggregation of the 112 psychological dials.

Rolls every agent's dial profile in a session into:
  - per-dial distributions (mean / min / max / stdev / raw values, plus by-stance means)
  - per-group means
  - a curated market-research scorecard (composite + commercial headline metrics)
  - a stance x scorecard-dial heatmap matrix

Pure functions only — no DB, no I/O — so it is trivially testable and reusable.
"""
from __future__ import annotations

import statistics
from typing import Iterable

GROUP_ORDER = [
    "sentiment", "motivation", "habit", "trust",
    "friction", "identity", "commercial", "product", "composite",
]

GROUP_LABELS = {
    "sentiment": "Sentiment",
    "motivation": "Motivation",
    "habit": "Habit",
    "trust": "Trust",
    "friction": "Friction",
    "identity": "Identity",
    "commercial": "Commercial",
    "product": "Product",
    "composite": "Composite",
}

# Dials where a LOWER value is the healthier / more favorable signal.
NEGATIVE_DIALS = {
    # commercial
    "churn_risk", "objection_intensity", "price_pain",
    # composite
    "emotional_risk",
    # habit
    "dependency_risk", "switching_cost",
    # friction (the whole group is resistance)
    "cognitive_load", "time_cost", "money_pain", "ambiguity", "choice_overload",
    "technical_difficulty", "emotional_resistance", "embarrassment_risk",
    "social_risk", "regret_risk", "friction",
}

# Headline metrics surfaced as the dashboard scorecard, in display order.
SCORECARD_DIALS = [
    "adoption_readiness",
    "purchase_intent",
    "willingness_to_pay",
    "virality_potential",
    "retention_potential",
    "human_resonance",
    "product_emotional_fit",
    "churn_risk",
    "emotional_risk",
]


def _round(x: float, n: int = 2) -> float:
    return round(float(x), n)


def _label(key: str) -> str:
    return key.replace("_", " ").title()


def _rating(mean: float, negative: bool = False) -> str:
    """Qualitative band, orientation-aware (so churn_risk=2 reads as 'strong')."""
    score = (10.0 - mean) if negative else mean
    if score >= 7.5:
        return "strong"
    if score >= 5.0:
        return "moderate"
    if score >= 2.5:
        return "weak"
    return "critical"


def _stats(values: list[float]) -> dict:
    if not values:
        return {"mean": 0.0, "min": 0.0, "max": 0.0, "stdev": 0.0, "n": 0}
    return {
        "mean": _round(statistics.fmean(values)),
        "min": _round(min(values)),
        "max": _round(max(values)),
        "stdev": _round(statistics.pstdev(values)) if len(values) > 1 else 0.0,
        "n": len(values),
    }


def _get(agent, key: str):
    if isinstance(agent, dict):
        return agent.get(key)
    return getattr(agent, key, None)


def _agent_dials(agent) -> dict:
    return _get(agent, "dials") or {}


def _agent_stance(agent) -> str:
    s = _get(agent, "stance")
    return getattr(s, "value", s) or "unknown"


def aggregate_dials(agents: Iterable) -> dict:
    """Aggregate dial profiles across a population.

    Accepts either ORM agents or plain dicts (each needing `dials` and `stance`).
    """
    agents = list(agents)

    # group -> dial -> [values]   and   stance -> group -> dial -> [values]
    groups: dict[str, dict[str, list[float]]] = {}
    by_stance: dict[str, dict[str, dict[str, list[float]]]] = {}

    with_dials = 0
    for a in agents:
        dials = _agent_dials(a)
        if not dials:
            continue
        with_dials += 1
        stance = _agent_stance(a)
        for group, dial_map in dials.items():
            if not isinstance(dial_map, dict):
                continue
            for dial, raw in dial_map.items():
                try:
                    v = float(raw)
                except (TypeError, ValueError):
                    continue
                groups.setdefault(group, {}).setdefault(dial, []).append(v)
                (by_stance.setdefault(stance, {})
                          .setdefault(group, {})
                          .setdefault(dial, []).append(v))

    stances = sorted(by_stance.keys())

    def stance_mean(group: str, dial: str) -> dict:
        out = {}
        for st in stances:
            vals = by_stance.get(st, {}).get(group, {}).get(dial)
            if vals:
                out[st] = _round(statistics.fmean(vals))
        return out

    # ── group + per-dial summaries ──────────────────────────────────────────
    group_out: dict[str, dict] = {}
    flat: dict[str, tuple[str, dict]] = {}  # dial -> (group, summary)
    for group in [g for g in GROUP_ORDER if g in groups] + \
                 [g for g in groups if g not in GROUP_ORDER]:
        dials_out: dict[str, dict] = {}
        all_vals: list[float] = []
        for dial, vals in groups[group].items():
            summary = {
                "label": _label(dial),
                "negative": dial in NEGATIVE_DIALS,
                **_stats(vals),
                "values": [_round(v, 1) for v in vals],
                "by_stance": stance_mean(group, dial),
            }
            dials_out[dial] = summary
            flat.setdefault(dial, (group, summary))
            all_vals.extend(vals)
        group_out[group] = {
            "label": GROUP_LABELS.get(group, group.title()),
            "group_mean": _stats(all_vals)["mean"],
            "dial_count": len(dials_out),
            "dials": dials_out,
        }

    # ── scorecard (headline market-research metrics) ────────────────────────
    scorecard = []
    for key in SCORECARD_DIALS:
        if key not in flat:
            continue
        group, s = flat[key]
        scorecard.append({
            "key": key,
            "label": s["label"],
            "group": group,
            "mean": s["mean"],
            "min": s["min"],
            "max": s["max"],
            "stdev": s["stdev"],
            "negative": s["negative"],
            "rating": _rating(s["mean"], s["negative"]),
            "by_stance": s["by_stance"],
        })

    # ── stance x scorecard heatmap ──────────────────────────────────────────
    heatmap = {
        "rows": stances,
        "cols": [s["label"] for s in scorecard],
        "keys": [s["key"] for s in scorecard],
        "values": [
            [s["by_stance"].get(st) for s in scorecard]
            for st in stances
        ],
    }

    return {
        "agent_count": len(agents),
        "with_dials": with_dials,
        "stances": stances,
        "scorecard": scorecard,
        "heatmap": heatmap,
        "groups": group_out,
    }
