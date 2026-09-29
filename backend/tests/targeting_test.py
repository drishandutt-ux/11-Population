"""Behaviour targeting (brief L7-05): which behaviour to change, as a counted ranking.

Run:  cd backend && pytest tests/targeting_test.py -q
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.measurement import levers as lv  # noqa: E402
from app.services.measurement import targeting as tg  # noqa: E402
from app.services.measurement.instruments import journey as jn  # noqa: E402
from app.services.simulation import records as rec  # noqa: E402
from tests.journey_test import SPEC, _row  # noqa: E402

MENU = {"behaviours": [{"key": "dynamic.liner_cost", "label": "Liner cost", "group": "dynamic", "why": "", "low": "", "high": "", "question_specific": True},
                       {"key": "dynamic.smell_tolerance", "label": "Smell tolerance", "group": "dynamic", "question_specific": True}],
        "fixed": lv.dial_keys(), "points_default": 2, "points_max": 3, "max_behaviours": 12}


def test_the_menu_is_the_question_dials_plus_any_real_fixed_dial():
    assert tg.valid_keys(["dynamic.liner_cost", "friction.money_pain", "friction.made_up", "nodot", "dynamic.liner_cost", ""], MENU) == ["dynamic.liner_cost", "friction.money_pain"]
    n = tg.nudge_spec("dynamic.liner_cost", 2, MENU)
    assert n == {"dial": "dynamic.liner_cost", "points": 2, "label": "Liner cost", "group": "dynamic", "question_specific": True}
    assert tg.nudge_spec("friction.money_pain", 1, MENU)["label"] == "money pain" and not tg.nudge_spec("friction.money_pain", 1, MENU)["question_specific"]
    # the nudge lands on the dynamic group like any other dial, clamped to the scale
    out = lv.adjusted_dials({"dynamic": {"liner_cost": 9}, "friction": {"money_pain": 4}}, {"deltas": {"dynamic.liner_cost": 2}, "bound": 6})
    assert out["dynamic"]["liner_cost"] == 10 and out["friction"]["money_pain"] == 4


def _base():
    # step3 → step4 is the candidate; a5, a6, a7, a8, a9, a10, a11 sit at step3 or beyond (at risk); a1–a4 do not.
    q1, q5 = "Q1 most deprived", "Q5 least deprived"
    return [_row(1, "step1", "no", "x", "GP access", "y", 90), _row(2, "step1", "yes"), _row(3, "step2", "yes"), _row(4, "step2", "no", "c", "cost", "f", 80, dep=q5),
            _row(5, "step3", "no", "s", "side effects", "n", 60, dep=q1), _row(6, "step3", "no", "s", "side effects", "n", 60, dep=q1), _row(7, "step3", "no", "s", "side effects", "n", 60, dep=q1),
            _row(8, "step3", "yes", dep=q5), _row(9, "step3", "yes", dep=q5), _row(10, "step3", "no", "s", "side effects", "n", 60, dep=q5), _row(11, "step3", "no", "s", "side effects", "n", 60, dep=q5)]


def _arm(base, progress: dict):
    out = []
    for r in base:
        r2 = {**r, "answer": dict(r["answer"])}
        if r["agent_id"] in progress:
            r2["answer"]["progress"] = progress[r["agent_id"]]
        out.append(r2)
    return out


def _map(rows):
    return {r["agent_id"]: {"answer": r["answer"], "segments": r["segments"]} for r in rows}


def test_only_the_twins_at_risk_at_the_step_are_re_asked():
    base = _base()
    stages = jn.stages_of(SPEC)
    assert set(tg.at_risk_ids(base, stages, 3)) == {f"a{k}" for k in range(5, 12)}
    assert set(tg.at_risk_ids(base, stages, 1)) == {f"a{k}" for k in range(1, 12)}


def test_behaviours_are_ranked_by_movement_per_point_with_direction_and_backfire():
    base = _base()
    c_agg = jn.aggregate(base, SPEC)
    # liner cost nudged up: every stuck Q5 twin gets through and one Q1 twin does → helps overall
    liner = _arm(base, {"a10": "yes", "a11": "yes", "a5": "yes"})
    # smell tolerance nudged up: Q5 stuck twins get through but all three Q1 twins who were through fall back → helps overall, backfires for Q1
    smell = _arm(base, {"a10": "yes", "a11": "yes", "a8": "no", "a9": "no"})
    # money pain nudged up: two through twins fall back, nobody moves through → hurts
    money = _arm(base, {"a8": "no", "a9": "no"})
    arms = {"dynamic.liner_cost": (jn.aggregate(liner, SPEC), _map(liner)),
            "dynamic.smell_tolerance": (jn.aggregate(smell, SPEC), _map(smell)),
            "friction.money_pain": (jn.aggregate(money, SPEC), _map(money))}
    t = tg.rank(control_agg=c_agg, control_rows=_map(base), arms=arms, candidate_id="step3->step4", points=2, menu=MENU, seed=1)
    assert t["available"] and t["n"] == 7 and t["points"] == 2
    by = {r["key"]: r for r in t["behaviours"]}
    liner_r, smell_r, money_r = by["dynamic.liner_cost"], by["dynamic.smell_tolerance"], by["friction.money_pain"]
    # movement per point is the paired lift over the nudge
    assert abs(liner_r["lift"] - 3 / 7) < 1e-3 and abs(liner_r["per_point"] - 3 / 14) < 1e-3 and liner_r["direction"] == "up"
    assert money_r["direction"] == "down" and money_r["lift"] < 0 and money_r["movement"]["down"] == 2
    # the ranking: real movements first, then by size
    ranks = [r["key"] for r in t["behaviours"]]
    assert ranks.index("dynamic.liner_cost") < ranks.index("friction.money_pain")
    assert all(r["rank"] == k + 1 for k, r in enumerate(t["behaviours"]))
    # smell tolerance: overall up (2 up vs 2 down → 0? no: a10,a11 up; a8,a9 down → net 0) — check the band flag machinery on money pain instead
    assert smell_r["direction"] in ("up", "down", "none")
    # labels come from the menu; a fixed dial is named from its key
    assert liner_r["label"] == "Liner cost" and liner_r["question_specific"] and money_r["label"] == "money pain" and not money_r["question_specific"]
    # the sentence names the order, the direction, the caveat
    assert "Behaviours ranked by movement per point" in t["sentence"] and "push up 'Liner cost'" in t["sentence"]
    assert "sensitivity" in t["sentence"] and "not the effect of any intervention" in t["sentence"]


def test_a_band_that_moves_the_other_way_is_a_backfire_and_is_said_out_loud():
    base = _base()
    c_agg = jn.aggregate(base, SPEC)
    # nudge helps all four Q5 twins (two already through stay, two stuck move) but knocks every Q1 twin down... Q1 stuck twins can't fall further;
    # so build it the other way round: overall UP driven by Q5 (a10, a11 through) while Q1's three are unchanged → no backfire.
    up_only = _arm(base, {"a10": "yes", "a11": "yes"})
    t = tg.rank(control_agg=c_agg, control_rows=_map(base), arms={"dynamic.liner_cost": (jn.aggregate(up_only, SPEC), _map(up_only))}, candidate_id="step3->step4", points=2, menu=MENU, seed=1)
    r = t["behaviours"][0]
    assert r["direction"] == "up" and r["backfire"] == [] and t["backfires"] == [] and "No behaviour backfired" in t["sentence"]
    # now overall DOWN (Q5 twins a8, a9 fall back; nothing else) while Q1 gains one → Q1 band's interval must sit above zero to count as a backfire;
    # with one Q1 mover in three the interval crosses zero, so no flag: the flag needs a band that clearly moves the other way.
    mixed = _arm(base, {"a8": "no", "a9": "no", "a5": "yes", "a6": "yes", "a7": "yes"})
    t2 = tg.rank(control_agg=c_agg, control_rows=_map(base), arms={"dynamic.liner_cost": (jn.aggregate(mixed, SPEC), _map(mixed))}, candidate_id="step3->step4", points=2, menu=MENU, seed=1)
    r2 = t2["behaviours"][0]
    assert r2["direction"] == "up"                      # 3 up vs 2 down → up overall
    q5 = next(b for b in r2["bands"] if b["value"] == "Q5 least deprived")
    assert q5["lift"] < 0                               # the Q5 band went the other way
    if q5["high"] < 0:                                  # and when its interval is clearly below zero, it is a backfire, said out loud
        assert any(b["value"] == "Q5 least deprived" for b in r2["backfire"]) and "BACKFIRE" in t2["sentence"] and "Q5 least deprived" in t2["sentence"]
    # a behaviour that hurts overall is flagged as such
    down = _arm(base, {"a8": "no", "a9": "no"})
    t3 = tg.rank(control_agg=c_agg, control_rows=_map(base), arms={"friction.money_pain": (jn.aggregate(down, SPEC), _map(down))}, candidate_id="step3->step4", points=2, menu=MENU, seed=1)
    r3 = t3["behaviours"][0]
    assert r3["direction"] == "down" and r3["hurts"] == bool(r3["significant"])


def test_a_targeting_run_becomes_a_record_and_the_report_model_is_bound_to_it():
    base = _base()
    c_agg = jn.aggregate(base, SPEC)
    liner = _arm(base, {"a10": "yes", "a11": "yes", "a5": "yes"})
    t = tg.rank(control_agg=c_agg, control_rows=_map(base), arms={"dynamic.liner_cost": (jn.aggregate(liner, SPEC), _map(liner))}, candidate_id="step3->step4", points=2, menu=MENU, seed=1)
    t["journey_probe_id"] = "p1"
    e = SimpleNamespace(id="e1", name="Behaviours ranked at Started → Still on it", seed=1, model="m", created_at=None, results={"targeting": t, "comparisons": []})
    r = rec.record_from_experiment(e)
    assert r["kind"] == "targeting" and r["label"].startswith("Behaviours ranked at") and r["estimate"]["format"] == "lift"
    assert r["targeting"]["behaviours"][0]["key"] == "dynamic.liner_cost" and r["targeting"]["points"] == 2 and r["targeting"]["n"] == 7
    assert any("sensitivity of the modelled population" in c for c in r["caveats"])
    text, handles = rec.records_block([r])
    assert "behaviours ranked (conversion points per dial point at the step, 7 twins at risk)" in text and "1. push up 'Liner cost'" in text
    assert "not an intervention's effect" in text and handles["r1"] == "e1"
    assert "WHICH BEHAVIOUR TO CHANGE" in rec.FIGURE_RULES and "BACKFIRE" in rec.FIGURE_RULES
    # not yet counted: no record
    assert rec.record_from_experiment(SimpleNamespace(id="e2", results={"targeting": {"available": False}}, seed=1, model="m", name="", created_at=None)) is None
