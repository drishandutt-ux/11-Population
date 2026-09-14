"""Choice — the "which one" instrument behind the choose-between-them experiment design.

Every agent sees ALL the variants at once, labelled, and picks the best and the runner-up.
One call per agent. Internal: it is not offered in the picker; the experiments layer builds
its spec (the composed material, the option keys, the question) from the base tool's
variants. Its reasons are free words coded into themes like Ask's.
"""
from __future__ import annotations

from app.services.evidence.llm import enum, i, obj, s
from app.services.measurement import stats
from app.services.measurement.instruments import Instrument, register
from app.services.measurement.themes import THEME_KEY, apply_themes

DIRECTIVE = """

YOU ARE CHOOSING BETWEEN OPTIONS, NOT WRITING A POST.
- This answer is private. Say which option you would really go for.
- Judge them against each other, for YOU, in your life. Pick one best and one runner-up; they
  must be different options.
- Reason first, then the choice. The key factor is the one thing that made the winner win, in
  your own words and specific to these options."""


def schema_for(spec: dict) -> dict:
    keys = [str(k) for k in (spec.get("option_keys") or [])] or ["A", "B"]
    return obj({
        "reasoning": s("2-3 sentences, in character: how you weighed the options"),
        "choice": enum(keys, "The option you would go for"),
        "runner_up": enum(keys, "Your second choice (must differ from choice)"),
        "confidence": i("How sure you are of the winner, 0-100"),
        "key_factor": s("The single thing that made the winner win, in 3-8 words of your own"),
    })


def _verbatims(rows: list[dict], key: str, limit: int = 3) -> list[dict]:
    out = []
    for r in rows:
        if r["answer"].get("choice") != key:
            continue
        out.append({
            "agent_id": r["agent_id"], "name": r["agent"].get("name", ""), "role": r["agent"].get("role", ""),
            "reasoning": r["answer"].get("reasoning", ""), "key_factor": r["answer"].get("key_factor", ""),
            "theme": r["answer"].get(THEME_KEY, ""),
        })
        if len(out) >= limit:
            break
    return out


def aggregate(rows: list[dict], spec: dict) -> dict:
    if not rows:
        return {"n": 0, "sentence": "No answers yet."}
    keys = [str(k) for k in (spec.get("option_keys") or [])]
    labels = {str(k): str(v) for k, v in (spec.get("option_labels") or {}).items()}
    answers = [r["answer"] for r in rows]
    seed = int(spec.get("seed") or 0)

    n = len(rows)
    preference = []
    for k in keys:
        w = stats.share_of([a.get("choice") for a in answers], lambda v, k=k: v == k)
        runner = sum(1 for a in answers if a.get("runner_up") == k)
        themed = [a.get(THEME_KEY) for a in answers if a.get("choice") == k and a.get(THEME_KEY)]
        preference.append({
            "key": k, "label": labels.get(k, k), **w,
            "runner_up": runner, "runner_up_share": round(runner / n, 4),
            "themes": stats.distribution(themed) if themed else [],
            "confidence": stats.mean_ci([a.get("confidence", 0) for a in answers if a.get("choice") == k], seed=seed),
            "segments": {
                sk: stats.segment(rows, sk, lambda rs, k=k: stats.share_of([r["answer"].get("choice") for r in rs], lambda v: v == k))
                for sk in ("stance", "age_band", "humanity_band", "purchase_intent_prior")
            },
            "verbatims": _verbatims(rows, k),
        })
    preference.sort(key=lambda d: (-d["share"], d["key"]))

    head_to_head = {}
    for a in answers:
        pair = (str(a.get("choice")), str(a.get("runner_up")))
        head_to_head[pair] = head_to_head.get(pair, 0) + 1
    h2h = [{"first": f, "second": s_, "count": c} for (f, s_), c in sorted(head_to_head.items(), key=lambda kv: -kv[1])]

    top = preference[0]
    second = preference[1] if len(preference) > 1 else None
    gap = (top["share"] - second["share"]) if second else top["share"]
    clear = bool(second) and top["low"] > second["high"]
    top_theme = top["themes"][0]["value"] if top["themes"] else ""
    sentence = (
        f"{top['label']} is preferred by {stats.pct(top['share'])} ({top['successes']} of {n})"
        + (f", {round(gap * 100)} points ahead of {second['label']}" if second else "")
        + (" — a clear winner, the intervals do not overlap" if clear else
           " — but the intervals overlap, so the order is not settled" if second else "")
        + (f"; what made it win: \"{top_theme}\"." if top_theme else ".")
    )
    return {
        "n": n,
        "headline": {"metric": "preference", "label": f"Prefer {top['label']}", **{k: top[k] for k in ("share", "low", "high", "n", "successes")}},
        "sentence": sentence,
        "preference": preference,
        "head_to_head": h2h,
        "clear_winner": clear,
        "winner": top["key"],
        "themes_coded": any(p["themes"] for p in preference),
    }


async def postprocess(probe_ids: list[str], model: str) -> None:
    await apply_themes(probe_ids, model=model)


class ChoiceInstrument(Instrument):
    def schema_for(self, spec: dict) -> dict:  # type: ignore[override]
        return schema_for(spec)


INSTRUMENT = register(ChoiceInstrument(
    key="choice",
    label="Choose between",
    description="Every agent sees all the options and picks the best and a runner-up.",
    answer_schema=schema_for({}),
    question="Which of these would you go for, and which is your second choice?",
    directive=DIRECTIVE,
    aggregate=aggregate,
    inputs=(),
    kpis=(),
    metrics=(),
    decision_key="choice",
    driver_key=THEME_KEY,
    page="choice",
    max_tokens=600,
    version=1,
    stimulus_key="stimulus",
    question_from="question",
    postprocess=postprocess,
    hidden=True,
))
