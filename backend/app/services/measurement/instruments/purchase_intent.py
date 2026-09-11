"""Purchase intent — the "would you buy it?" ask, and the first instrument in the library.

One call per agent returns a decision, a likelihood, the agent's own walk-away price and the
driver behind it. The walk-away price is the valuable part: elicited once, it gives a demand
curve for free, which is what later makes the price slider instant.
"""
from __future__ import annotations

from app.services.evidence.llm import enum, i, n, obj, s
from app.services.measurement import stats
from app.services.measurement.instruments import InputField, Instrument, Kpi, register

DRIVERS = ["price", "need", "trust", "social", "convenience", "identity", "risk"]

SCHEMA = obj({
    # reasoning FIRST: a model anchored to a stated reason spreads out instead of
    # clustering every number on the midpoint.
    "reasoning": s("1-2 sentences, in character, explaining your decision"),
    "would_buy": enum(["yes", "no", "unsure"], "Would you actually buy this?"),
    "likelihood_0_100": i("How likely you are to buy, 0-100"),
    "max_price": n("The most YOU would pay before walking away, in the offer's currency"),
    "key_driver": enum(DRIVERS, "The single thing that decided it"),
    "sentiment": n("How you feel about the offer, -1 (hostile) to 1 (delighted)"),
})

DIRECTIVE = """

YOU ARE MAKING A DECISION, NOT WRITING A POST.
- This answer is private. Nobody in the discussion sees it, so there is no side to defend and
  nothing to perform. Say what you would actually do, even if it contradicts your public posts.
- Decide about THIS offer, at THIS price, in YOUR life — not about the category in general.
- Reason first, then the numbers, and make the numbers follow the reasoning. If your reason is
  "too expensive for what it is", your likelihood is low and your walk-away price is below the
  asking price. An answer that contradicts itself is worse than an unflattering one.
- Your walk-away price is the most YOU would actually hand over given your income, your
  commitments and what else that money is for. It is not the asking price repeated back, and
  it is not what you think the thing is worth to somebody else.
- "No" is a real answer. Most people, most of the time, do not buy."""


def _reservation(answer: dict) -> float:
    """The agent's walk-away price. `max_price_gbp` is the v1 spelling: the field was renamed
    because the instrument prices in the offer's currency, not always GBP."""
    v = answer.get("max_price", answer.get("max_price_gbp"))
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _verbatims(rows: list[dict], value: str, limit: int = 4) -> list[dict]:
    out = []
    for r in rows:
        if r["answer"].get("would_buy") != value:
            continue
        out.append({
            "agent_id": r["agent_id"],
            "name": r["agent"].get("name", ""),
            "role": r["agent"].get("role", ""),
            "reasoning": r["answer"].get("reasoning", ""),
            "max_price": _reservation(r["answer"]),
        })
        if len(out) >= limit:
            break
    return out


def _yes_share(rows: list[dict]) -> dict:
    return stats.share_of([r["answer"].get("would_buy") for r in rows], lambda v: v == "yes")


def aggregate(rows: list[dict], spec: dict) -> dict:
    if not rows:
        return {"n": 0, "sentence": "No answers yet."}

    answers = [r["answer"] for r in rows]
    price = spec.get("price")
    currency = spec.get("currency", "GBP")
    seed = int(spec.get("seed") or 0)

    head = _yes_share(rows)
    likelihood = stats.mean_ci([a.get("likelihood_0_100", 0) for a in answers], seed=seed)
    reservation = [_reservation(a) for a in answers]
    max_price = stats.mean_ci(reservation, seed=seed)
    curve = stats.demand_curve(reservation, max_price=(float(price) * 2 if price else None))

    # Cross-check: the share whose own walk-away price clears the asking price. Where this
    # disagrees with what they *said*, the stated answer is posturing or the price is marginal,
    # and the client should see both numbers rather than only the flattering one.
    at_price = None
    contradictions = 0
    if price:
        p = float(price)
        at_price = stats.share_of(reservation, lambda v: float(v or 0) >= p)
        contradictions = sum(
            1 for a in answers
            if (a.get("would_buy") == "yes") != (_reservation(a) >= p)
        )

    segments = {
        key: stats.segment(rows, key, lambda rs: _yes_share(rs))
        for key in ("stance", "age_band", "humanity_band", "purchase_intent_prior")
    }
    segments = {k: v for k, v in segments.items() if v}

    drivers = stats.distribution([a.get("key_driver", "") for a in answers])
    top_driver = drivers[0]["value"] if drivers else ""

    sym = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency, "")
    margin = round((head["high"] - head["low"]) / 2 * 100)
    sentence = (
        f"{stats.pct(head['share'])} of this population would buy, ±{margin} points "
        f"({head['successes']} of {head['n']}). "
        f"The median walk-away price is {sym}{max_price['median']:g}"
        + (f", against an asking price of {sym}{float(price):g}" if price else "")
        + (f"; the decision turns mostly on {top_driver}." if top_driver else ".")
    )

    return {
        "n": len(rows),
        "headline": {"metric": "would_buy_share", "label": "Would buy", **head},
        "sentence": sentence,
        "would_buy": stats.distribution([a.get("would_buy", "") for a in answers]),
        "likelihood": likelihood,
        "max_price": {**max_price, "currency": currency},
        "demand_curve": curve,
        "optimal_price": stats.optimal_price(curve),
        "at_asking_price": at_price,
        "consistency": {
            "contradictions": contradictions,
            "share": round(contradictions / len(rows), 4) if price else None,
            "note": "Agents whose stated answer disagrees with their own walk-away price.",
        },
        "drivers": drivers,
        "sentiment": stats.mean_ci([a.get("sentiment", 0) for a in answers], seed=seed),
        "segments": segments,
        "verbatims": {v: _verbatims(rows, v) for v in ("yes", "unsure", "no")},
    }


# This instrument's own input panel. The stimulus lives HERE, not in the Lab shell: it is
# purchase intent's input, not something every future tool inherits. A pricing ladder or a
# conjoint declares entirely different controls.
INPUTS = (
    InputField(
        key="stimulus", type="textarea", label="The offer", required=True,
        help="Write it as the customer would see it. The session query is written for you, the analyst — this is written for them.",
        placeholder="Describe the product or offer exactly as the customer would see it, including the price.",
        default_from="session_query",
    ),
    InputField(
        key="price", type="money", label="Asking price",
        help="Optional. Supplied it, and you also get a demand curve and a check on who actually clears the price.",
        placeholder="34.99",
    ),
    InputField(
        key="currency", type="select", label="Currency", default="GBP",
        options=("GBP", "USD", "EUR"),
    ),
)

KPIS = (
    Kpi("would_buy_share", "Would buy", "share", "Share answering yes, with a Wilson interval."),
    Kpi("likelihood", "Mean likelihood", "mean", "Self-rated 0-100."),
    Kpi("max_price", "Walk-away price", "money", "The most they would pay before walking away."),
    Kpi("sentiment", "Feeling", "mean", "-1 hostile to 1 delighted."),
)

INSTRUMENT = register(Instrument(
    key="purchase_intent",
    label="Purchase intent",
    description="Would they buy it, how likely, and the most they would pay.",
    answer_schema=SCHEMA,
    question=(
        "Would you buy this? Record your decision, how likely you are to buy (0-100), the most "
        "you would pay before walking away, the one thing that decided it, and how you feel about it."
    ),
    directive=DIRECTIVE,
    aggregate=aggregate,
    inputs=INPUTS,
    kpis=KPIS,
    page="purchase_intent",
    max_tokens=500,
    version=2,
))
