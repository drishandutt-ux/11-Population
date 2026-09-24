"""The unanimity check (brief L3-06, §06 adversarial checks): is this agreement real?

A synthetic panel agrees too easily. The same model writes every twin, they read the same room,
and a result can come back 95% one way not because the population thinks that but because the
first few answers set the tone. A number like that is worse than a wrong number — it reads as
a strong finding.

The check is mechanical and needs no model. A population is BUILT to differ: it has stances,
segments, places and registers that were chosen because they should behave differently. So:

  when the headline is lopsided AND the population's own splits show almost no spread between
  buckets that were supposed to disagree, the result is flagged as consensus that the population
  should not have produced.

It flags; it never hides or rewrites a number. A flag says "look at this before you quote it".
"""
from __future__ import annotations

from typing import Any, Optional

#: A headline at or above this share is lopsided enough to be worth checking.
LOPSIDED = 0.85
#: Below this spread between buckets, the splits that were supposed to differ did not.
FLAT = 0.08
#: A bucket smaller than this is noise, not a split.
MIN_BUCKET_N = 3
#: Splits that describe who the twin IS, and so should move an answer if anything does.
#: (Prior splits like `purchase_intent_prior` are excluded: they are dials, not people.)
STRUCTURAL_SPLITS = ("stance", "segment", "region", "age_band", "humanity_band", "income_band", "education")


def _spread(buckets: list[dict]) -> Optional[dict]:
    """Max − min share across the usable buckets of one split."""
    usable = [b for b in buckets if isinstance(b.get("share"), (int, float)) and (b.get("n") or 0) >= MIN_BUCKET_N]
    if len(usable) < 2:
        return None
    shares = [float(b["share"]) for b in usable]
    top = max(usable, key=lambda b: b["share"])
    bottom = min(usable, key=lambda b: b["share"])
    return {
        "spread": round(max(shares) - min(shares), 4),
        "buckets": len(usable),
        "high": {"value": top["value"], "share": round(float(top["share"]), 4), "n": top["n"]},
        "low": {"value": bottom["value"], "share": round(float(bottom["share"]), 4), "n": bottom["n"]},
    }


def check(headline: Any, segments: dict[str, list[dict]], *, n: int = 0) -> Optional[dict]:
    """Flag a result that is more unanimous than its own population should allow.

    `headline` is the instrument's primary share block ({share, n, …}); `segments` the splits it
    already computed. Returns None when there is nothing to say — the common case."""
    share = (headline or {}).get("share") if isinstance(headline, dict) else None
    if not isinstance(share, (int, float)) or not segments:
        return None
    top = max(float(share), 1.0 - float(share))     # lopsided either way: 5% yes is as uniform as 95%

    spreads = {}
    for key in STRUCTURAL_SPLITS:
        got = _spread(segments.get(key) or [])
        if got:
            spreads[key] = got
    if not spreads:
        return None

    widest = max(spreads.items(), key=lambda kv: kv[1]["spread"])
    flat = widest[1]["spread"] <= FLAT
    flagged = top >= LOPSIDED and flat

    if not flagged:
        return {"flagged": False, "top_share": round(top, 4), "widest_split": widest[0], "widest_spread": widest[1]["spread"], "n": n}

    example = widest[1]
    return {
        "flagged": True,
        "top_share": round(top, 4),
        "widest_split": widest[0],
        "widest_spread": example["spread"],
        "n": n,
        "reason": (
            f"{round(top * 100)}% answered the same way, and the widest gap between groups that were "
            f"built to differ is {round(example['spread'] * 100)} points "
            f"({example['high']['value']} {round(example['high']['share'] * 100)}% vs "
            f"{example['low']['value']} {round(example['low']['share'] * 100)}%). "
            "Treat this as agreement the panel may not have reached on its own — check the verbatims, "
            "re-run with a different seed, or ask the question a different way before quoting it."
        ),
    }
