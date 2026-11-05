"""City — every twin's ordinary week and how far each lever would move them (11 Minds City, 2026-11-05).

The 3D city runs in the browser with no model calls: a twin wakes, works, gets hungry, spends,
meets people, notices a poster, and may go and do the OUTCOME. What drives each twin is this
ONE answer, given in character: where they live, their day, how much they go out, how much
spare money they have, how impulsive and sociable they are, how inclined they already are to
the outcome, and — for every lever in the plan — how likely they are to come across it in a
normal week and how far it would move them (it can push them away).

So the city is a model built from the twins' own answers, run forward in time; it is not a
fresh poll at every moment, and the results say so. The answer schema is flat (one field per
lever) because nested arrays are where structured output goes wrong.
"""
from __future__ import annotations

from typing import Any

from app.services.evidence.llm import enum, i, obj, s
from app.services.measurement import city as city_svc
from app.services.measurement import stats
from app.services.measurement.instruments import InputField, Instrument, Kpi, Metric, register

DAYTIME = ("work_away", "work_home", "study", "caring", "retired", "not_working")
EVENING = ("stay_in", "pub", "friends", "eat_out", "gym", "shops", "walk", "church_or_club")
HOME_TYPE = ("house", "flat")
ACT_NOW = ("yes", "maybe", "no")


def _levers(spec: dict) -> list[dict]:
    return [lv for lv in (spec.get("levers") or []) if isinstance(lv, dict) and lv.get("id")]


def _cities(spec: dict) -> list[dict]:
    return [c for c in (spec.get("cities") or []) if isinstance(c, dict) and c.get("id")]


def schema_for(spec: dict) -> dict:
    cities = _cities(spec)
    props: dict[str, Any] = {
        "reasoning": s("2-3 sentences, in character: what your ordinary week looks like and where you honestly stand on the outcome"),
        "home": enum([c["id"] for c in cities] or ["town"], "Which of these places you live in, or the one most like where you live, by its id"),
        "home_type": enum(list(HOME_TYPE), "House or flat"),
        "daytime": enum(list(DAYTIME), "What fills your weekdays"),
        "wake_hour": i("Hour you usually get up, 4-12"),
        "leave_hour": i("Hour you usually leave home on a weekday, 5-14 (the same as wake_hour + 1 if you rarely go out)"),
        "back_hour": i("Hour you are usually home again, 10-23"),
        "evening": enum(list(EVENING), "What you most often do on a weekday evening"),
        "go_out": i("How willing you are to leave the house for something that isn't routine, 0 (almost never) to 100 (always out)"),
        "spare_cash_week": i("Pounds you have spare in a normal week after bills, honestly"),
        "impulse": i("How likely you are to buy on impulse, 0-100"),
        "sociable": i("How much you seek out and talk to other people, 0-100"),
        "eats_out": i("Times a week you buy food or drink out (cafe, takeaway, pub), 0-14"),
        "mood": i("How you usually feel day to day, 0 (low) to 100 (great)"),
        "start_interest": i("How inclined you are to do the outcome RIGHT NOW, as things stand, 0 (not at all) to 100 (already decided)"),
        "act_now": enum(list(ACT_NOW), "Would you do the outcome in the next week as things stand"),
        "barrier": s("The single biggest thing that stops you doing it, in 3-10 words of your own; empty if nothing"),
        "word_of_mouth": i("How likely you are to tell people about it if you did it or heard about it, 0-100"),
        "quote": s("One short line you might actually say out loud about it to a friend, in your own voice"),
    }
    for lv in _levers(spec):
        props[f"meet_{lv['id']}"] = i(f"Lever '{lv['label']}': chance you would come across it in a normal week, 0-100")
        props[f"pull_{lv['id']}"] = i(f"Lever '{lv['label']}': if you did come across it, how far it moves you toward doing the outcome, -100 (puts you off) to 100 (gets you there)")
    return obj(props)


def question_for(spec: dict) -> str:
    plan = city_svc.clean_plan(spec)
    price = f"£{plan['outcome_price']}" if plan["outcome_price"] else "free"
    lines = [
        f"THE OUTCOME: {plan['outcome_label']} — at the {plan['outcome_building']}, {price}, open {plan['open_from']}:00 to {plan['open_to']}:00.",
        plan["outcome_detail"],
        "",
        "THE PLACES:",
        *[f"- [{c['id']}] {c['name']}: {c['blurb']}" for c in plan["cities"]],
        "",
        "THINGS THAT MIGHT HAPPEN (each lever, judged on its own):",
        *[f"- [{lv['id']}] {lv['label']}: {lv['detail']}" for lv in plan["levers"]],
        "",
        "Tell us about your ordinary week in the place you live, where you stand on the outcome as things are, "
        "and for each lever how likely you are to come across it and how far it would move you.",
    ]
    return "\n".join(x for x in lines if x is not None)


DIRECTIVE = """

YOU ARE DESCRIBING YOUR OWN ORDINARY WEEK, NOT WRITING A POST.
- This answer is private. Describe the week you actually have — your hours, your money, your habits — not the one you would like.
- Money is honest: if there is little left after bills, say so. Most people have less spare than they think.
- Going out: count only leaving the house for something that is not routine.
- For each lever, judge it ON ITS OWN. Most things most people never notice: a poster on a street you do not walk, an advert on a channel you do not watch.
- A lever can put you off (a negative pull) — distrust of adverts, being talked down to, the wrong messenger.
- start_interest is where you are now, before any lever. Be consistent with what you have said before in this session."""


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 1) if xs else None


def aggregate(rows: list[dict], spec: dict) -> dict:
    """What the twins said, before the city runs: per town, how many already would, how
    inclined they start, and per lever its reach (chance of meeting it) and pull. The time
    course — who actually acts, when and why — is computed by the city itself."""
    levers = _levers(spec)
    cities = _cities(spec)
    answered = [r for r in rows if isinstance(r.get("answer"), dict) and r["answer"].get("home")]
    by_city: dict[str, list[dict]] = {c["id"]: [] for c in cities}
    for r in answered:
        by_city.setdefault(r["answer"]["home"], []).append(r)

    def block(rs: list[dict]) -> dict:
        ans = [r["answer"] for r in rs]
        yes = sum(1 for a in ans if a.get("act_now") == "yes")
        out = {
            "n": len(ans),
            "act_now_yes": stats.wilson(yes, len(ans)) if ans else None,
            "start_interest_mean": _mean([float(a.get("start_interest") or 0) for a in ans]),
            "go_out_mean": _mean([float(a.get("go_out") or 0) for a in ans]),
            "spare_cash_median": sorted(float(a.get("spare_cash_week") or 0) for a in ans)[len(ans) // 2] if ans else None,
            "levers": [],
        }
        for lv in levers:
            meet = [float(a.get(f"meet_{lv['id']}") or 0) for a in ans]
            pull = [float(a.get(f"pull_{lv['id']}") or 0) for a in ans]
            # Expected push in a week: chance of meeting it × how far it moves, averaged over people.
            push = _mean([m / 100.0 * p for m, p in zip(meet, pull)])
            out["levers"].append({"id": lv["id"], "label": lv["label"], "meet_mean": _mean(meet), "pull_mean": _mean(pull),
                                  "put_off": sum(1 for p in pull if p < 0), "expected_push": push})
        return out

    return {
        "n": len(answered),
        "overall": block(answered),
        "cities": {cid: block(rs) for cid, rs in by_city.items()},
        "note": "What the twins said about their week and each lever. The city runs these answers forward in time in the browser; it is a model, not a fresh poll.",
    }


class CityInstrument(Instrument):
    def schema_for(self, spec: dict) -> dict:  # type: ignore[override]
        return schema_for(spec)

    def question_for(self, spec: dict) -> str:  # type: ignore[override]
        return question_for(spec)

    def validate(self, spec: dict) -> list[str]:  # type: ignore[override]
        return city_svc.problems(city_svc.clean_plan(spec))


INPUTS = (
    InputField(key="cities", type="city_plan", label="The city plan", required=True,
               help="The places, the outcome and the levers, drafted with the colleague in 11 Minds City."),
)
KPIS = (
    Kpi("act_now_yes", "Would act as things stand", "share", "Share who say they would do the outcome in the next week before any lever."),
)
METRICS = (
    Metric("act_now", "Would act as things stand", "share", lambda a: 1.0 if a.get("act_now") == "yes" else 0.0, primary=True),
    Metric("start_interest", "Starting interest", "mean", lambda a: float(a.get("start_interest") or 0)),
)

INSTRUMENT = register(CityInstrument(
    key="city",
    label="11 Minds City",
    description="A living 3D town built around the session: every twin describes their ordinary week and how far each lever would move them, once; the city then runs those answers forward so you can watch who acts, when, where and why.",
    answer_schema=schema_for({}),
    question="Tell us about your ordinary week and how each lever would move you.",
    directive=DIRECTIVE,
    aggregate=aggregate,
    inputs=INPUTS,
    kpis=KPIS,
    metrics=METRICS,
    decision_key="act_now",
    page="city",
    max_tokens=1100,
    version=1,
    hidden=True,
))
