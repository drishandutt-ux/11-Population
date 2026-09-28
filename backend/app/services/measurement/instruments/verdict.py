"""Verdict — the population's answer to the session question, as a typed probe (brief L6-01).

Every report needs at least one computed number, even when the analyst ran no Lab tool. This
hidden instrument asks each twin the session question itself and gets back a position
(for / against / mixed), a confidence and a one-line verdict. From those the report's
headline outcome record is computed exactly like any Lab result — share with a Wilson interval,
the population's own splits, refusals, the unanimity check — and never typed by the report
model. The one-liners also feed the Agent Opinions sidebar, so the two agree.
"""
from __future__ import annotations

from app.services.evidence.llm import enum, i, obj, s
from app.services.measurement import stats
from app.services.measurement.probe import split_keys
from app.services.measurement.instruments import Instrument, register

SCHEMA = obj({
    "reasoning": s("2-3 sentences, in character: how you actually come down on this question, and why"),
    "position": enum(["for", "against", "mixed"],
                     "for = yes, it should happen / it would work; against = no; mixed = genuinely torn, it depends"),
    "confidence": i("How sure you are of that position, 0 (a guess) to 100 (certain)"),
    "verdict": s("Your verdict in ONE line of at most 20 words, in your own voice — the line a reader would quote"),
})

DIRECTIVE = """

YOU ARE GIVING YOUR VERDICT ON THE QUESTION, NOT WRITING A POST.
- This answer is private. Say where you honestly come down, as yourself, from your own life and work.
- "mixed" means genuinely torn or "it depends on X" — not a hedge to avoid committing.
- Reason first; make the position follow the reasoning; then the one-line verdict a reader could quote."""


def _verbatims(rows: list[dict], value: str, limit: int = 4) -> list[dict]:
    out = []
    for r in rows:
        if r["answer"].get("position") != value:
            continue
        out.append({
            "agent_id": r["agent_id"], "name": r["agent"].get("name", ""), "role": r["agent"].get("role", ""),
            "verdict": r["answer"].get("verdict", ""), "reasoning": r["answer"].get("reasoning", ""),
            "confidence": r["answer"].get("confidence", 0),
        })
        if len(out) >= limit:
            break
    return out


def _for_share(rows: list[dict]) -> dict:
    return stats.share_of([r["answer"].get("position") for r in rows], lambda v: v == "for")


def aggregate(rows: list[dict], spec: dict) -> dict:
    if not rows:
        return {"n": 0, "sentence": "No answers yet."}
    answers = [r["answer"] for r in rows]
    seed = int(spec.get("seed") or 0)
    head = _for_share(rows)
    against = stats.share_of([a.get("position") for a in answers], lambda v: v == "against")
    mixed = stats.share_of([a.get("position") for a in answers], lambda v: v == "mixed")
    confidence = stats.mean_ci([a.get("confidence", 0) for a in answers], seed=seed)
    segments = {key: stats.segment(rows, key, lambda rs: _for_share(rs)) for key in split_keys(rows)}
    segments = {k: v for k, v in segments.items() if v}
    margin = round((head["high"] - head["low"]) / 2 * 100)
    sentence = (
        f"{stats.pct(head['share'])} of the population come down in favour, ±{margin} points ({head['successes']} of {head['n']}); "
        f"{stats.pct(against['share'])} against, {stats.pct(mixed['share'])} torn. Mean confidence {confidence['mean']:.0f}/100."
    )
    return {
        "n": len(rows),
        "headline": {"metric": "for_share", "label": "In favour", **head},
        "sentence": sentence,
        "position": stats.distribution([a.get("position", "") for a in answers]),
        "against": against,
        "mixed": mixed,
        "confidence": confidence,
        "segments": segments,
        "verbatims": {v: _verbatims(rows, v) for v in ("for", "mixed", "against")},
    }


INSTRUMENT = register(Instrument(
    key="verdict",
    label="Verdict",
    description="Every twin's position on the session question — the report's headline outcome record.",
    answer_schema=SCHEMA,
    question="Where do you come down on this question?",
    directive=DIRECTIVE,
    aggregate=aggregate,
    inputs=(),
    kpis=(),
    metrics=(),
    decision_key="position",
    page="verdict",
    max_tokens=500,
    version=1,
    stimulus_key="stimulus",
    question_from="question",
    hidden=True,
))
