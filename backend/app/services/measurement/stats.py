"""Pure-Python statistics for the Behaviour Lab. No LLM, no I/O, numpy-free.

Numbers without error bars are opinions. Every aggregate a probe reports comes from
here, so the interval is computed in one place and unit-tested in one place.
"""
from __future__ import annotations

import math
import random
from typing import Any, Callable, Iterable, Optional, Sequence

Z95 = 1.959963984540054


# ── proportions ───────────────────────────────────────────────────────────────

def wilson(successes: int, n: int, z: float = Z95) -> dict:
    """Share with a Wilson score interval — correct at small n, unlike the normal approximation.

    Returns {share, low, high, n, successes} with share/low/high as 0..1 fractions."""
    if n <= 0:
        return {"share": 0.0, "low": 0.0, "high": 0.0, "n": 0, "successes": 0}
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return {
        "share": round(p, 4),
        "low": round(max(0.0, centre - half), 4),
        "high": round(min(1.0, centre + half), 4),
        "n": n,
        "successes": successes,
    }


def share_of(values: Sequence[Any], predicate: Callable[[Any], bool]) -> dict:
    return wilson(sum(1 for v in values if predicate(v)), len(values))


def distribution(values: Sequence[Any]) -> list[dict]:
    """Counts + Wilson shares per distinct value, most common first."""
    n = len(values)
    counts: dict[Any, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    out = [{"value": k, "count": c, **wilson(c, n)} for k, c in counts.items()]
    out.sort(key=lambda d: (-d["count"], str(d["value"])))
    return out


# ── means ─────────────────────────────────────────────────────────────────────

def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = q * (len(sorted_vals) - 1)
    lo, hi = math.floor(idx), math.ceil(idx)
    if lo == hi:
        return float(sorted_vals[int(idx)])
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo))


def mean_ci(values: Sequence[float], *, iterations: int = 2000, seed: int = 0) -> dict:
    """Mean with a bootstrap 95% interval, plus median and quartiles.

    Bootstrap rather than the t-interval because probe answers are often bounded and skewed
    (a 0-100 likelihood piles up at the ends). `seed` keeps the interval reproducible."""
    vals = [float(v) for v in values if v is not None]
    n = len(vals)
    if n == 0:
        return {"mean": 0.0, "low": 0.0, "high": 0.0, "median": 0.0, "p25": 0.0, "p75": 0.0, "n": 0, "sd": 0.0}
    mean = sum(vals) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
    srt = sorted(vals)
    if n == 1:
        low = high = mean
    else:
        rng = random.Random(seed)
        means = []
        for _ in range(iterations):
            means.append(sum(vals[rng.randrange(n)] for _ in range(n)) / n)
        means.sort()
        low, high = _percentile(means, 0.025), _percentile(means, 0.975)
    return {
        "mean": round(mean, 3),
        "low": round(low, 3),
        "high": round(high, 3),
        "median": round(_percentile(srt, 0.5), 3),
        "p25": round(_percentile(srt, 0.25), 3),
        "p75": round(_percentile(srt, 0.75), 3),
        "sd": round(sd, 3),
        "n": n,
    }


# ── paired lift (A/B within-subjects; used by the experiments layer) ───────────

def paired_lift(pairs: Sequence[tuple[float, float]], *, iterations: int = 2000, seed: int = 0) -> dict:
    """Mean of (b - a) over agents that answered both variants, with a bootstrap interval.

    Pairing is what makes a 50-agent A/B credible: each agent is its own control."""
    diffs = [float(b) - float(a) for a, b in pairs]
    out = mean_ci(diffs, iterations=iterations, seed=seed)
    out["significant"] = bool(diffs) and (out["low"] > 0 or out["high"] < 0)
    return out


# ── segments ──────────────────────────────────────────────────────────────────

def segment(rows: Sequence[dict], key: str, aggregate: Callable[[Sequence[dict]], dict], *, min_n: int = 3) -> list[dict]:
    """Split `rows` by row["segments"][key] and aggregate each bucket.

    Buckets below `min_n` are reported with `thin=True` rather than dropped, so the UI can
    grey them out instead of silently hiding a small but real group."""
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        label = (r.get("segments") or {}).get(key)
        if label is None:
            continue
        buckets.setdefault(str(label), []).append(r)
    out = []
    for label, rs in buckets.items():
        out.append({"segment": key, "value": label, "n": len(rs), "thin": len(rs) < min_n, **aggregate(rs)})
    out.sort(key=lambda d: (-d["n"], d["value"]))
    return out


# ── weighting (raking to a target census) ─────────────────────────────────────

def rake_weights(rows: Sequence[dict], targets: dict[str, dict[str, float]], *, iterations: int = 30) -> list[float]:
    """Iterative proportional fitting: per-row weights that make the panel's marginals match
    `targets` ({segment_key: {bucket: target_share}}), so a 200-agent panel can be reported
    as "UK adults 18+". Returns weights aligned with `rows` (all 1.0 when targets are empty)."""
    n = len(rows)
    w = [1.0] * n
    if not targets or n == 0:
        return w
    for _ in range(iterations):
        for key, target in targets.items():
            totals: dict[str, float] = {}
            for i, r in enumerate(rows):
                label = str((r.get("segments") or {}).get(key, ""))
                totals[label] = totals.get(label, 0.0) + w[i]
            total_w = sum(w) or 1.0
            for i, r in enumerate(rows):
                label = str((r.get("segments") or {}).get(key, ""))
                want = target.get(label)
                have = totals.get(label, 0.0) / total_w
                if want and have > 0:
                    w[i] *= want / have
    scale = n / (sum(w) or 1.0)
    return [round(x * scale, 6) for x in w]


def weighted_share(flags: Sequence[bool], weights: Sequence[float]) -> float:
    tot = sum(weights) or 1.0
    return round(sum(wt for f, wt in zip(flags, weights) if f) / tot, 4)


# ── demand curves ─────────────────────────────────────────────────────────────

def demand_curve(reservation_prices: Sequence[float], *, points: int = 24, max_price: Optional[float] = None) -> list[dict]:
    """Share who still buy at each price, from each agent's own walk-away price.

    This is what makes the price slider free: elicit the reservation price once, then every
    point on the curve is a comparison, not a model call."""
    vals = [float(v) for v in reservation_prices if v is not None and float(v) > 0]
    if not vals:
        return []
    top = max_price if max_price and max_price > 0 else max(vals) * 1.2
    step = top / max(1, points)
    curve = []
    for k in range(points + 1):
        price = round(step * k, 2)
        buyers = sum(1 for v in vals if v >= price)
        w = wilson(buyers, len(vals))
        curve.append({
            "price": price,
            "share": w["share"],
            "low": w["low"],
            "high": w["high"],
            "revenue_index": round(price * w["share"], 4),
        })
    return curve


def optimal_price(curve: Sequence[dict]) -> dict:
    """The revenue-maximising point on a demand curve (revenue_index = price × share)."""
    if not curve:
        return {"price": 0.0, "share": 0.0, "revenue_index": 0.0}
    best = max(curve, key=lambda p: p["revenue_index"])
    return {"price": best["price"], "share": best["share"], "revenue_index": best["revenue_index"]}


# ── reliability ───────────────────────────────────────────────────────────────

def agreement(a: Sequence[Any], b: Sequence[Any]) -> dict:
    """Test-retest agreement between two runs of the same probe on the same agents.

    Exact agreement for categoricals; for numbers, the share within 10% of the scale."""
    pairs = list(zip(a, b))
    if not pairs:
        return {"agreement": 0.0, "n": 0}
    if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x, _ in pairs):
        span = (max(max(a), max(b)) - min(min(a), min(b))) or 1
        hits = sum(1 for x, y in pairs if abs(float(x) - float(y)) <= 0.1 * span)
    else:
        hits = sum(1 for x, y in pairs if x == y)
    return {**wilson(hits, len(pairs)), "agreement": round(hits / len(pairs), 4)}


def polarisation(values: Sequence[float]) -> float:
    """Variance of a stance distribution, normalised 0..1 — how split the room is."""
    vals = [float(v) for v in values if v is not None]
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    span = (max(vals) - min(vals)) or 1.0
    return round(min(1.0, var / ((span / 2) ** 2)), 4)


def pct(x: float) -> str:
    return f"{round(x * 100)}%"
