"""Visuals — show the population a picture and find out what it does to them.

The Visual Lab's instrument (step 1, 2026-10-26). The stimulus is one or more images the
session holds (uploaded by the analyst; generated ones come later), shown to every twin as real
image blocks, with an optional line on where they would come across it. The twin says what it
noticed first, what it took the piece to be saying, what put it off, whether it works on them
(the verdict), how strongly, how it feels, and the one thing it would change. Free-text fields
are coded into shared themes after the run, so "what put people off" reads as a ranked list.

It declares metrics, so the A/B test runs over it unchanged: rate each image blind (paired),
let every twin choose between the images (one call, all pictures labelled by option), or split
the population. Nothing in the experiments layer knows the stimulus is a picture.
"""
from __future__ import annotations

from app.services.evidence.llm import enum, i, n, obj, s
from app.services.measurement import images as images_mod
from app.services.measurement import stats
from app.services.measurement.probe import split_keys
from app.services.measurement.instruments import InputField, Instrument, Kpi, Metric, register
from app.services.measurement.themes import THEME_KEY, apply_themes, theme_key_for

NOTICED = "noticed_first"
PUT_OFF = "put_off"
CHANGE = "change_one"
NOTICED_THEME = theme_key_for(NOTICED)
PUT_OFF_THEME = theme_key_for(PUT_OFF)

SCHEMA = obj({
    "reasoning": s("2-3 sentences, in character: your honest reaction to what you see, and what would actually happen for you"),
    NOTICED: s("The first thing your eye went to, in a few words of your own — a picture, a headline, a colour, a face, a price"),
    "message_taken": s("What you took it to be telling you, in one plain sentence of your own"),
    PUT_OFF: s("What put you off or made you doubt it, in 3-10 words — or 'nothing' if nothing did"),
    "verdict": enum(["yes", "no", "mixed"],
                    "yes = it works on you, you would do what it asks or go along with it; no = it does not; mixed = genuinely torn"),
    "strength": i("How strongly you hold that verdict, 0 (barely) to 100 (certain)"),
    "feeling": n("How it makes you feel, -1 (hostile) to 1 (delighted)"),
    CHANGE: s("The one thing you would change about it, in one sentence — or 'nothing'"),
    "key_factor": s("The single thing that decided your verdict, in 3-8 words of your own"),
})

DIRECTIVE = """

YOU ARE LOOKING AT A PICTURE AND REACTING TO IT, NOT WRITING A POST.
- This answer is private. Nobody in the discussion sees it, so there is nothing to perform.
  Say what you would really think and do.
- React to what is actually in the image: what you can see and read. Do not invent text,
  logos or details that are not there. If a line is too small to read, say so.
- Look as a person, not an analyst: the first thing you noticed is the first thing you noticed,
  and "it put me off" can be a feeling before it is a reason.
- Answer the question you are asked, about THIS image, in YOUR life — would it work on you,
  would you do what it asks, would you walk past.
- Reason first, then the verdict, and make the verdict follow the reasoning. "Mixed" is for
  being genuinely torn, not for hedging.
- The key factor is the one thing that decided it, in your own words. Be specific: "the price
  in the corner" not "price"; "looks like an NHS leaflet" not "design"."""

QUESTION_SUGGESTIONS = (
    "Does this work on you? Would you do what it asks?",
    "Would this stop you as you walked past, or would you walk on?",
    "What do you take this to be saying, and do you believe it?",
    "Does this feel like it was made for people like you?",
    "Would you act on this — tap it, pick it up, go and find out more?",
    "Would you share this with someone you know? Who, and why?",
)


def _verbatims(rows: list[dict], value: str, limit: int = 4) -> list[dict]:
    out = []
    for r in rows:
        if r["answer"].get("verdict") != value:
            continue
        a = r["answer"]
        out.append({
            "agent_id": r["agent_id"],
            "name": r["agent"].get("name", ""),
            "role": r["agent"].get("role", ""),
            "reasoning": a.get("reasoning", ""),
            "noticed_first": a.get(NOTICED, ""),
            "message_taken": a.get("message_taken", ""),
            "put_off": a.get(PUT_OFF, ""),
            "change_one": a.get(CHANGE, ""),
            "key_factor": a.get("key_factor", ""),
            "theme": a.get(THEME_KEY, ""),
        })
        if len(out) >= limit:
            break
    return out


def _yes_share(rows: list[dict]) -> dict:
    return stats.share_of([r["answer"].get("verdict") for r in rows], lambda v: v == "yes")


def _is_nothing(text: str) -> bool:
    t = " ".join(str(text or "").lower().split()).strip(" .!")
    return t in ("", "nothing", "nothing really", "none", "no", "n/a", "nothing in particular", "nothing much")


def _coded_or_raw(answers: list[dict], field: str, theme_field: str, *, drop_nothing: bool = False) -> tuple[list[dict], bool]:
    """A distribution over the coded theme when the run has been coded, else over the raw words."""
    coded = [a.get(theme_field) for a in answers if a.get(theme_field)]
    raw = [a.get(field) for a in answers if a.get(field)]
    use, is_coded = (coded, True) if coded else (raw, False)
    if drop_nothing:
        use = [v for v in use if not _is_nothing(v)]
    return (stats.distribution(use) if use else []), is_coded


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
    noticed, noticed_coded = _coded_or_raw(answers, NOTICED, NOTICED_THEME)
    put_off, put_off_coded = _coded_or_raw(answers, PUT_OFF, PUT_OFF_THEME, drop_nothing=True)
    nothing_put_off = stats.share_of([a.get(PUT_OFF) for a in answers], _is_nothing)

    segments = {
        key: stats.segment(rows, key, lambda rs: _yes_share(rs))
        for key in split_keys(rows)
    }
    segments = {k: v for k, v in segments.items() if v}

    top = themes[0]["value"] if themes else (factors[0]["value"] if factors else "")
    top_noticed = noticed[0]["value"] if noticed else ""
    top_put_off = put_off[0]["value"] if put_off else ""
    margin = round((head["high"] - head["low"]) / 2 * 100)
    sentence = (
        f"{stats.pct(head['share'])} say it works on them, ±{margin} points ({head['successes']} of {head['n']}); "
        f"{stats.pct(open_to['share'])} are at least open to it. "
        f"Mean feeling {feeling['mean']:+.2f}"
        + (f"; most eyes went first to \"{top_noticed}\"" if top_noticed else "")
        + (f"; the most common thing that put people off is \"{top_put_off}\"" if top_put_off else "")
        + (f"; the deciding factor most often named is \"{top}\"." if top else ".")
    )

    return {
        "n": len(rows),
        "headline": {"metric": "yes_share", "label": "Works on them", **head},
        "sentence": sentence,
        "verdict": stats.distribution([a.get("verdict", "") for a in answers]),
        "open_to": open_to,
        "strength": strength,
        "feeling": feeling,
        "themes": themes,
        "factors": factors[:12],
        "themes_coded": bool(themed),
        "noticed": noticed[:10],
        "noticed_coded": noticed_coded,
        "put_off": put_off[:10],
        "put_off_coded": put_off_coded,
        "nothing_put_off": nothing_put_off,
        "changes": [
            {"agent_id": r["agent_id"], "name": r["agent"].get("name", ""), "role": r["agent"].get("role", ""),
             "verdict": r["answer"].get("verdict", ""), "change_one": r["answer"].get(CHANGE, "")}
            for r in rows if r["answer"].get(CHANGE) and not _is_nothing(r["answer"].get(CHANGE))
        ][:24],
        "segments": segments,
        "verbatims": {v: _verbatims(rows, v) for v in ("yes", "mixed", "no")},
    }


INPUTS = (
    InputField(
        key=images_mod.IMAGES_KEY, type="images", label="What they see",
        help="Upload an image or pick from this session's images. Several images are shown together as one piece.",
    ),
    InputField(
        key="setting", type="text", label="Where they come across it",
        help="Optional. The situation the twin meets it in, in a few words.",
        placeholder="A poster at a bus stop · a leaflet in the GP's waiting room · an ad in their feed",
    ),
    InputField(
        key="question", type="textarea", label="What you want to know", required=True,
        help="One question, asked of every agent. Pick a phrasing or write your own.",
        placeholder=QUESTION_SUGGESTIONS[0],
        default=QUESTION_SUGGESTIONS[0],
        suggestions=QUESTION_SUGGESTIONS,
    ),
)

KPIS = (
    Kpi("yes_share", "Works on them", "share", "Share whose verdict is yes, with a Wilson interval."),
    Kpi("open_to", "Open to it", "share", "Yes or mixed."),
    Kpi("strength", "Strength", "mean", "How strongly they hold it, 0-100."),
    Kpi("feeling", "Feeling", "mean", "-1 hostile to 1 delighted."),
)

METRICS = (
    Metric("verdict", "Works on them", "share", lambda a: 1.0 if a.get("verdict") == "yes" else 0.0, primary=True,
           help="Share whose verdict is yes."),
    Metric("open_to", "Open to it", "share", lambda a: 1.0 if a.get("verdict") in ("yes", "mixed") else 0.0,
           help="Yes or mixed."),
    Metric("strength", "Strength", "mean", lambda a: float(a.get("strength") or 0), help="0-100."),
    Metric("feeling", "Feeling", "mean", lambda a: float(a.get("feeling") or 0), help="-1 to 1."),
)


async def postprocess(probe_ids: list[str], model: str) -> None:
    """Code the deciding factor, what was noticed first and what put people off into shared themes."""
    await apply_themes(probe_ids, model=model, fields=["key_factor", NOTICED, PUT_OFF])


class VisualInstrument(Instrument):
    def validate(self, spec: dict) -> list[str]:  # type: ignore[override]
        return images_mod.validate_refs(spec, required=True)


INSTRUMENT = register(VisualInstrument(
    key="visual",
    label="Visuals",
    description="Show them a poster, a pack, a page, an ad. What they noticed first, what they took it to say, what put them off, and whether it works on them — with the reasons coded into themes.",
    answer_schema=SCHEMA,
    question=QUESTION_SUGGESTIONS[0],
    directive=DIRECTIVE,
    aggregate=aggregate,
    inputs=INPUTS,
    kpis=KPIS,
    metrics=METRICS,
    decision_key="verdict",
    driver_key=THEME_KEY,
    page="visual",
    max_tokens=700,
    version=1,
    # The stimulus IS the images: the runner lays them out as image blocks and never stringifies them.
    stimulus_key=images_mod.IMAGES_KEY,
    question_from="question",
    postprocess=postprocess,
))
