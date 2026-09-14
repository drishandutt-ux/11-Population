"""Ask — the generic reaction instrument.

Every "which email lands", "does this poster make you want to go", "what happens in your
street if this goes ahead" has the same shape: show a person something, ask them to react,
get back a verdict, a strength, a feeling and a reason. So the schema is fixed and the
QUESTION is free text. The reason is free words, coded into shared themes after the run
(`services/measurement/themes.py`) so the driver mix works without an enum per question.

Anything with a price still belongs to purchase intent; this covers everything else.
"""
from __future__ import annotations

from app.services.evidence.llm import enum, i, n, obj, s
from app.services.measurement import stats
from app.services.measurement.instruments import InputField, Instrument, Kpi, Metric, register
from app.services.measurement.themes import THEME_KEY, apply_themes

SCHEMA = obj({
    "reasoning": s("2-3 sentences, in character: your honest reaction, and what would actually happen for you"),
    "verdict": enum(["yes", "no", "mixed"],
                    "yes = this works for you / you would go along with it; no = it does not; mixed = genuinely torn"),
    "strength": i("How strongly you hold that verdict, 0 (barely) to 100 (certain)"),
    "feeling": n("How it makes you feel, -1 (hostile) to 1 (delighted)"),
    "key_factor": s("The single thing that decided it, in 3-8 words of your own"),
})

DIRECTIVE = """

YOU ARE REACTING TO SOMETHING, NOT WRITING A POST.
- This answer is private. Nobody in the discussion sees it, so there is nothing to perform.
  Say what you would really think and do.
- Answer the question you are asked, about THIS material, in YOUR life — not about the topic in
  general. If the question asks what would happen, say what would happen to you and people like you.
- Reason first, then the verdict, and make the verdict follow the reasoning. "Mixed" is for being
  genuinely torn, not for hedging.
- The key factor is the one thing that decided it, in your own words. Be specific: "the 4-7pm
  price" not "price"; "sounds like every other email" not "tone"."""

QUESTION_SUGGESTIONS = (
    "Does this work for you? Would you go along with it?",
    "Would you open this email and act on it?",
    "Does this make you want to find out more, or switch off?",
    "Is this believable, and does it change what you would do?",
    "What would happen for you and people like you if this went ahead?",
    "Would you share this with someone you know? Who, and why?",
)


def _verbatims(rows: list[dict], value: str, limit: int = 4) -> list[dict]:
    out = []
    for r in rows:
        if r["answer"].get("verdict") != value:
            continue
        out.append({
            "agent_id": r["agent_id"],
            "name": r["agent"].get("name", ""),
            "role": r["agent"].get("role", ""),
            "reasoning": r["answer"].get("reasoning", ""),
            "key_factor": r["answer"].get("key_factor", ""),
            "theme": r["answer"].get(THEME_KEY, ""),
        })
        if len(out) >= limit:
            break
    return out


def _yes_share(rows: list[dict]) -> dict:
    return stats.share_of([r["answer"].get("verdict") for r in rows], lambda v: v == "yes")


def aggregate(rows: list[dict], spec: dict) -> dict:
    if not rows:
        return {"n": 0, "sentence": "No answers yet."}
    answers = [r["answer"] for r in rows]
    seed = int(spec.get("seed") or 0)

    head = _yes_share(rows)
    open_to = stats.share_of([a.get("verdict") for a in answers], lambda v: v in ("yes", "mixed"))
    strength = stats.mean_ci([a.get("strength", 0) for a in answers], seed=seed)
    feeling = stats.mean_ci([a.get("feeling", 0) for a in answers], seed=seed)

    themed = [a.get(THEME_KEY) for a in answers if a.get(THEME_KEY)]
    themes = stats.distribution(themed) if themed else []
    factors = stats.distribution([a.get("key_factor", "") for a in answers])

    segments = {
        key: stats.segment(rows, key, lambda rs: _yes_share(rs))
        for key in ("stance", "age_band", "humanity_band", "purchase_intent_prior")
    }
    segments = {k: v for k, v in segments.items() if v}

    top = themes[0]["value"] if themes else (factors[0]["value"] if factors else "")
    margin = round((head["high"] - head["low"]) / 2 * 100)
    sentence = (
        f"{stats.pct(head['share'])} say yes, ±{margin} points ({head['successes']} of {head['n']}); "
        f"{stats.pct(open_to['share'])} are at least open to it. "
        f"Mean feeling {feeling['mean']:+.2f}"
        + (f"; the most common deciding factor is \"{top}\"." if top else ".")
    )

    return {
        "n": len(rows),
        "headline": {"metric": "yes_share", "label": "Yes", **head},
        "sentence": sentence,
        "verdict": stats.distribution([a.get("verdict", "") for a in answers]),
        "open_to": open_to,
        "strength": strength,
        "feeling": feeling,
        "themes": themes,
        "factors": factors[:12],
        "themes_coded": bool(themed),
        "segments": segments,
        "verbatims": {v: _verbatims(rows, v) for v in ("yes", "mixed", "no")},
    }


INPUTS = (
    InputField(
        key="material", type="textarea", label="What they see", required=True,
        help="The email, the poster copy, the proposal, the announcement — exactly as a person would meet it.",
        placeholder="Paste the material as the audience would see it.",
        default_from="session_query",
    ),
    InputField(
        key="question", type="textarea", label="What you want to know", required=True,
        help="One question, asked of every agent. Pick a phrasing or write your own.",
        placeholder="Does this work for you?",
        default=QUESTION_SUGGESTIONS[0],
        suggestions=QUESTION_SUGGESTIONS,
    ),
)

KPIS = (
    Kpi("yes_share", "Yes", "share", "Share whose verdict is yes, with a Wilson interval."),
    Kpi("open_to", "Open to it", "share", "Yes or mixed."),
    Kpi("strength", "Strength", "mean", "How strongly they hold it, 0-100."),
    Kpi("feeling", "Feeling", "mean", "-1 hostile to 1 delighted."),
)

METRICS = (
    Metric("verdict", "Yes", "share", lambda a: 1.0 if a.get("verdict") == "yes" else 0.0, primary=True,
           help="Share whose verdict is yes."),
    Metric("open_to", "Open to it", "share", lambda a: 1.0 if a.get("verdict") in ("yes", "mixed") else 0.0,
           help="Yes or mixed."),
    Metric("strength", "Strength", "mean", lambda a: float(a.get("strength") or 0), help="0-100."),
    Metric("feeling", "Feeling", "mean", lambda a: float(a.get("feeling") or 0), help="-1 to 1."),
)


async def postprocess(probe_ids: list[str], model: str) -> None:
    await apply_themes(probe_ids, model=model)


INSTRUMENT = register(Instrument(
    key="ask",
    label="Ask",
    description="Show them anything, ask them anything. A verdict, how strongly, how it feels, and why — with the reasons coded into themes.",
    answer_schema=SCHEMA,
    question=QUESTION_SUGGESTIONS[0],
    directive=DIRECTIVE,
    aggregate=aggregate,
    inputs=INPUTS,
    kpis=KPIS,
    metrics=METRICS,
    decision_key="verdict",
    driver_key=THEME_KEY,
    page="ask",
    max_tokens=600,
    version=1,
    stimulus_key="material",
    question_from="question",
    postprocess=postprocess,
))
