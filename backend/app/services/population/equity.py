"""Equity stratification by default (brief L6-04): every result is reported by deprivation level
as well as the headline.

One mechanism, three places:

  * **The frame.** `ensure_dimension` puts a deprivation dimension into every sampling frame
    (among the exactly-matched top three) whether or not the planner chose it. The statistics
    search hunts the place's real profile (in England the Index of Multiple Deprivation, IMD:
    the share of the place's neighbourhoods in each national quintile); when nothing is found,
    `reference_target` fills the cell with the national reference — equal fifths, which is how
    IMD deciles are built — labelled `model_inference` like any other estimate, so the ladder
    never leaves it unmatched. Fifths by default; tenths only when the population is large
    enough to fill them (`level_for`).
  * **The twin.** The persona writer places every twin in exactly one cell
    (`demographics.frame.deprivation`) and is told what the cell means for that life
    (`persona_note`). `rank_of` reads any spelling of a cell back to its rank, so the Lab's
    splits, the frame report and the weights all agree.
  * **The result.** `equity_block` turns a record's deprivation split into the equity line the
    brief asks for: the most and least deprived cells side by side, the gap in points, whether
    the gap is real (the two intervals do not overlap), and which cells are thin.

Generic by design: the dimension is "deprivation level"; IMD is the source it resolves to for
an English place, and the label says which index was used. Nothing here is pharma-specific.
"""
from __future__ import annotations

import re
from typing import Any, Optional

KEY = "deprivation"
ATTRIBUTE = "deprivation"
DECILE_MIN_N = 200        # tenths only when at least 200 twins: 20 per cell on average


def level_for(n: Optional[int]) -> str:
    return "decile" if (n or 0) >= DECILE_MIN_N else "quintile"


def size_of(level: str) -> int:
    return 10 if level == "decile" else 5


def label_for(rank: int, level: str) -> str:
    k = size_of(level)
    prefix = "D" if level == "decile" else "Q"
    if rank == 1:
        return f"{prefix}1 most deprived"
    if rank == k:
        return f"{prefix}{k} least deprived"
    return f"{prefix}{rank}"


def labels(level: str) -> list[str]:
    return [label_for(r, level) for r in range(1, size_of(level) + 1)]


def dimension(level: str = "quintile") -> dict:
    word = "decile" if level == "decile" else "quintile"
    return {
        "key": KEY, "label": f"Deprivation (IMD {word})", "attribute": ATTRIBUTE, "kind": "demographic",
        "why": "Equity by default: every result is reported by deprivation level as well as the headline (brief L6-04).",
        "matchable": True, "proxy_attribute": "income", "equity": True, "level": level,
    }


def ensure_dimension(dims: list[dict], n: Optional[int]) -> list[dict]:
    """The frame always carries the deprivation dimension, keyed `deprivation`, inside the top
    three so it is matched exactly rather than only weighted. A dimension the planner already
    chose for deprivation is kept (renamed to the shared key) rather than duplicated."""
    level = level_for(n)
    out = [dict(d) for d in dims or []]
    for d in out:
        if d.get("attribute") == ATTRIBUTE or d.get("key") == KEY or re.search(r"depriv|imd\b", f"{d.get('key', '')} {d.get('label', '')}", re.I):
            d.update({"key": KEY, "attribute": ATTRIBUTE, "equity": True, "level": level, "matchable": True})
            d.setdefault("label", dimension(level)["label"])
            return out
    out.insert(min(2, len(out)), dimension(level))
    return out


def find(dims: list[dict]) -> Optional[dict]:
    return next((d for d in dims or [] if d.get("key") == KEY or d.get("attribute") == ATTRIBUTE), None)


# ── reading a cell back ──────────────────────────────────────────────────────

_MOST = re.compile(r"most\s+deprived|highest\s+deprivation|poorest", re.I)
_LEAST = re.compile(r"least\s+deprived|lowest\s+deprivation|most\s+affluent|wealthiest|richest", re.I)
_RANK = re.compile(r"(?:^|\b)(?:q|d|quintile|decile|imd|rank|band|group)?\s*(\d{1,2})(?:st|nd|rd|th)?\b", re.I)
_PCT = re.compile(r"(\d{1,2})\s*%\s*(most|least)", re.I)


def rank_of(value: Any, level: str) -> Optional[int]:
    """The rank (1 = most deprived) a cell label or a twin's value names, at this level.
    Understands 'Q1 most deprived', 'D7', 'decile 3', 'quintile 2', '2nd quintile', 'most
    deprived 20%', 'IMD 1-2' (its midpoint), and a decile given when fifths are wanted."""
    k = size_of(level)
    v = str(value or "").strip()
    if not v:
        return None
    low = v.lower()
    m = _PCT.search(low)
    if m:
        pct, which = int(m.group(1)), m.group(2)
        cells = max(1, round(pct / (100 / k)))
        return 1 if which == "most" else k
    # an explicit decile in a quintile frame (or the reverse) is rescaled
    dec = re.search(r"\b(?:d|decile)\s*(\d{1,2})\b", low)
    qui = re.search(r"\b(?:q|quintile)\s*(\d)\b", low)
    if dec and level == "quintile":
        r = int(dec.group(1))
        return (r + 1) // 2 if 1 <= r <= 10 else None
    if qui and level == "decile":
        r = int(qui.group(1))
        return r * 2 - 1 if 1 <= r <= 5 else None
    rng = re.search(r"\b(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\b", low)
    if rng:
        a, b_ = int(rng.group(1)), int(rng.group(2))
        if 1 <= a <= b_ <= 10:
            mid = (a + b_) / 2
            return max(1, min(k, round(mid if k == 10 else (mid + 1) / 2)))
    m = _RANK.search(low)
    if m:
        r = int(m.group(1))
        if 1 <= r <= k:
            return r
        if k == 5 and 1 <= r <= 10:
            return (r + 1) // 2
    if _MOST.search(low):
        return 1
    if _LEAST.search(low):
        return k
    return None


_DECILE_LABEL = re.compile(r"\b(?:d|decile)\s*\d{1,2}\b", re.I)


def explicit_level(value: Any) -> str:
    """The level a label names by its own spelling: 'D7' / 'decile 3' are tenths; anything
    else (Q2, 'most deprived 20%') is read as fifths."""
    return "decile" if _DECILE_LABEL.search(str(value or "")) else "quintile"


def category_for(value: Any, categories: list[dict], level: str) -> Optional[str]:
    """The target category a value falls in, by rank."""
    r = rank_of(value, level)
    if r is None:
        return None
    for c in categories or []:
        if rank_of(c.get("label"), level) == r:
            return c["label"]
    return None


def canonical(value: Any, level: str) -> Optional[str]:
    """A twin's value as the shared cell label, so every split uses one spelling."""
    r = rank_of(value, level)
    return label_for(r, level) if r else None


# ── targets ──────────────────────────────────────────────────────────────────

def reference_target(level: str, geography: str) -> dict:
    """The national reference when the place's own profile was not found: IMD deciles are equal
    tenths of neighbourhoods by construction, so fifths are 20% each. Labelled as an estimate
    because a real town is rarely average."""
    k = size_of(level)
    return {
        "status": "estimated", "categories": [{"label": lab, "share_pct": round(100.0 / k, 1), "age_min": 0, "age_max": 0} for lab in labels(level)],
        "source": "national reference (IMD deciles are equal by construction)", "year": "2019", "geography": geography or "England",
        "proxy_attribute": "other", "provenance": "model_inference", "confidence": 40, "reference": True,
        "note": f"No published deprivation profile for {geography or 'the place'} on file: equal {'tenths' if k == 10 else 'fifths'} assumed — a deprived town will be under-represented in its poorest cells. Upload the local IMD profile to correct it.",
    }


def normalise_target(target: dict, level: str) -> dict:
    """A found distribution in the frame's own cells: categories whose labels name a rank are
    merged into the level's cells (a decile table becomes fifths); anything unreadable is left
    as the source gave it."""
    cats = target.get("categories") or []
    if not cats:
        return target
    merged: dict[int, float] = {}
    for c in cats:
        r = rank_of(c.get("label"), level)
        if r is None:
            return target
        merged[r] = merged.get(r, 0.0) + float(c.get("share_pct") or 0)
    if len(merged) < 2:
        return target
    out = [{"label": label_for(r, level), "share_pct": round(merged.get(r, 0.0), 1), "age_min": 0, "age_max": 0} for r in range(1, size_of(level) + 1) if merged.get(r, 0.0) > 0]
    return {**target, "categories": out}


def ensure_target(frame: dict, level: str) -> tuple[dict, Optional[str]]:
    """The deprivation cell of a frame is never left missing: a found or supplied profile is
    normalised to the level's cells; nothing on file becomes the labelled national reference.
    Returns (frame, a log line when something was decided)."""
    targets = dict(frame.get("targets") or {})
    dim = find(frame.get("dimensions") or [])
    if not dim:
        return frame, None
    tg = targets.get(KEY) or {}
    note = None
    if tg.get("status") in ("found", "proxy", "uploaded", "estimated") and tg.get("categories"):
        norm = normalise_target(tg, level)
        if norm is not tg:
            note = f"Deprivation profile read as {size_of(level)} cells from {tg.get('source') or tg.get('status')}"
        targets[KEY] = norm
    else:
        targets[KEY] = reference_target(level, frame.get("geography") or "")
        note = "No published deprivation profile found — national reference (equal cells) assumed and labelled model_inference; upload the local IMD profile to correct it"
    return {**frame, "targets": targets}, note


def persona_note(level: str) -> str:
    k = size_of(level)
    return (f"  ({KEY}: the cell is where this persona's neighbourhood sits in the national deprivation ranking, {label_for(1, level)} to "
            f"{label_for(k, level)}; write the persona so it shows — housing, work security, transport, cost pressure, health, how far services are — "
            f"without naming the index)")


# ── the equity line on a record ──────────────────────────────────────────────

def equity_block(buckets: Optional[list[dict]], *, level: Optional[str] = None, fmt: str = "share") -> dict:
    """From a record's deprivation split: cells in rank order, the most and least deprived cells,
    the gap and whether it is real. `{available: False, reason}` when the population carries no
    deprivation levels (built without a sampling frame)."""
    rows = [b for b in (buckets or []) if b.get("value")]
    if not rows:
        return {"available": False, "key": KEY, "reason": "No deprivation levels on this population: it was built without a sampling frame, so results cannot be cut by deprivation."}
    lvl = level or ("decile" if any(explicit_level(b["value"]) == "decile" for b in rows) else "quintile")
    ranked = []
    for b in rows:
        r = rank_of(b["value"], lvl)
        if r is None:
            continue
        ranked.append({"rank": r, "label": label_for(r, lvl), "value": b.get("value"), "n": int(b.get("n") or 0), "thin": bool(b.get("thin")),
                       "share": b.get("share"), "low": b.get("low"), "high": b.get("high"), "mean": b.get("mean")})
    if not ranked:
        return {"available": False, "key": KEY, "reason": "Deprivation cells could not be read on this population."}
    ranked.sort(key=lambda x: x["rank"])
    most, least = ranked[0], ranked[-1]
    metric = "share" if fmt == "share" else "mean"
    a, b_ = most.get(metric), least.get(metric)
    gap = None
    significant = None
    if isinstance(a, (int, float)) and isinstance(b_, (int, float)):
        gap = round((a - b_) * (100 if metric == "share" else 1), 1)
        if all(isinstance(x.get(k2), (int, float)) for x in (most, least) for k2 in ("low", "high")):
            significant = bool(most["high"] < least["low"] or least["high"] < most["low"])
    return {
        "available": True, "key": KEY, "level": lvl, "label": f"Deprivation (IMD {lvl})", "cells": ranked,
        "most": most, "least": least, "gap": gap, "gap_unit": "points" if metric == "share" else "units", "significant": significant,
        "thin": [x["label"] for x in ranked if x["thin"]], "spans": len(ranked) >= 2 and most["rank"] != least["rank"],
    }


def prompt_line(eq: dict) -> str:
    """One clause for the records block: the equity gap the model may write about."""
    if not eq or not eq.get("available"):
        return "equity: not available (no deprivation levels on this population)"
    most, least = eq["most"], eq["least"]
    def fmt(x: dict) -> str:
        return f"{round(float(x['share']) * 100)}%" if isinstance(x.get("share"), (int, float)) else (f"{x.get('mean')}" if x.get("mean") is not None else "n/a")
    verdict = "a real gap" if eq.get("significant") else ("not distinguishable at this size" if eq.get("significant") is False else "gap untested")
    thin = f"; thin: {', '.join(eq['thin'])}" if eq.get("thin") else ""
    return (f"equity: {most['label']} {fmt(most)} (n={most['n']}) vs {least['label']} {fmt(least)} (n={least['n']})"
            + (f", gap {eq['gap']:+g} {eq['gap_unit']}" if eq.get("gap") is not None else "") + f" — {verdict}{thin}")
