"""Lever simulation (brief L7-04) gated on calibration rules (brief L4-02).

Run:  cd backend && pytest tests/levers_test.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.measurement import headcount as hc  # noqa: E402
from app.services.measurement import levers as lv  # noqa: E402
from app.services.measurement.instruments import journey as jn  # noqa: E402
from app.services.simulation import records as rec  # noqa: E402
from tests.headcount_test import FRAME  # noqa: E402
from tests.journey_test import SPEC, _row  # noqa: E402

RULE = {"id": "r1", "lever": "nurse phone line", "description": "A nurse phone line in weeks 4-12 of treatment", "applies_to": {},
        "deltas": {"friction.emotional_resistance": -3, "trust.reliability": 2}, "bound": 4, "status": "reviewed", "reviewed_by": "M. Hunt", "reviewed_at": "2026-09-29T00:00:00",
        "evidence": [{"ref": "Audit 2025", "note": ""}], "basis": "Discontinuation halves where a nurse line exists."}


def test_a_rule_must_name_real_dials_within_its_bound_with_evidence_and_a_basis():
    ok = {"lever": "nurse phone line", "deltas": {"friction.emotional_resistance": -3}, "bound": 4, "evidence": [{"ref": "Audit"}], "basis": "because"}
    assert lv.validate_rule(ok) == []
    assert any("needs the lever" in p for p in lv.validate_rule({**ok, "lever": ""}))
    assert any("not a dial" in p for p in lv.validate_rule({**ok, "deltas": {"friction.made_up": -1}}))
    assert any("not a dial" in p for p in lv.validate_rule({**ok, "deltas": {"nodot": -1}}))
    assert any("outside the rule's bound" in p for p in lv.validate_rule({**ok, "deltas": {"friction.time_cost": -5}}))
    assert any("is zero" in p for p in lv.validate_rule({**ok, "deltas": {"friction.time_cost": 0}}))
    assert any("whole number" in p for p in lv.validate_rule({**ok, "deltas": {"friction.time_cost": "lots"}}))
    assert any("at least one dial" in p for p in lv.validate_rule({**ok, "deltas": {}}))
    assert any("evidence" in p for p in lv.validate_rule({**ok, "evidence": []}))
    assert any("basis" in p for p in lv.validate_rule({**ok, "basis": ""}))
    assert any("bound must be" in p for p in lv.validate_rule({**ok, "bound": 9}))


def test_a_rule_covers_everyone_or_the_segments_it_names_and_shifts_dials_within_the_scale():
    assert lv.applies({"applies_to": {}}, {"deprivation": "Q1 most deprived"})
    assert lv.applies({"applies_to": {"deprivation": ["Q1 most deprived", "Q2"]}}, {"deprivation": "Q2"})
    assert not lv.applies({"applies_to": {"deprivation": ["Q1 most deprived"]}}, {"deprivation": "Q5 least deprived"})
    assert not lv.applies({"applies_to": {"stance": "direct"}}, {"deprivation": "Q1 most deprived"})   # a missing key does not match
    dials = {"friction": {"emotional_resistance": 8, "time_cost": 1}, "trust": {"reliability": 9}}
    out = lv.adjusted_dials(dials, RULE)
    assert out["friction"]["emotional_resistance"] == 5 and out["trust"]["reliability"] == 10 and out["friction"]["time_cost"] == 1
    assert dials["friction"]["emotional_resistance"] == 8                       # the original is untouched
    assert lv.adjusted_dials({}, RULE)["friction"]["emotional_resistance"] == 2   # an unset dial starts at the midpoint
    # a delta beyond the bound is clamped to it
    assert lv.adjusted_dials({"friction": {"time_cost": 9}}, {"deltas": {"friction.time_cost": -9}, "bound": 2})["friction"]["time_cost"] == 7


def test_the_refusal_names_the_missing_rule_and_a_draft_is_not_enough():
    r = lv.refusal("bus subsidy", [])
    assert r["refused"] and r["missing"] and "No calibration rule for 'bus subsidy'" in r["reason"] and "will not guess" in r["reason"]
    r2 = lv.refusal("bus subsidy", [{"id": "d1", "lever": "bus subsidy", "status": "draft"}])
    assert r2["refused"] and not r2["missing"] and r2["drafts"] == ["d1"] and "has not been reviewed" in r2["reason"]


def test_the_twin_is_told_the_change_as_a_world_not_an_answer():
    spec = lv.lever_spec(RULE, {"id": "step3->step4", "step": 3, "from": {"label": "Started"}, "to": {"label": "Still on it"}})
    assert spec["rule_id"] == "r1" and spec["deltas"] == RULE["deltas"] and spec["from"] == "Started" and spec["reviewed_by"] == "M. Hunt"
    block = lv.counterfactual_block(spec)
    assert block.startswith("A CHANGE NOW IN PLACE") and "A nurse phone line in weeks 4-12 of treatment." in block
    assert "It bears on the step from 'Started' to 'Still on it'." in block and "no more helpful than it would actually be" in block


def _rows(progress_at_step3: dict):
    """Eight twins; a7 and a6 sit at step3; the lever arm changes their progress per `progress_at_step3`."""
    base = [_row(1, "step1", "no", "no slot", "GP access", "walk-in", 90), _row(2, "step1", "yes"), _row(3, "step2", "yes"),
            _row(4, "step2", "no", "cost", "cost", "free", 80, dep="Q5 least deprived"), _row(5, "step3", "no", "side effects", "side effects", "nurse", 60),
            _row(6, "step3", "no", "side effects", "side effects", "nurse", 60, dep="Q5 least deprived"), _row(7, "step4", "yes", dep="Q5 least deprived"), _row(8, "step4", "yes")]
    lever = []
    for r in base:
        r2 = {**r, "answer": dict(r["answer"])}
        if r["answer"]["reached"] == "step3" and r["agent_id"] in progress_at_step3:
            r2["answer"]["progress"] = progress_at_step3[r["agent_id"]]
            if r2["answer"]["progress"] == "yes":
                r2["answer"].update({"barrier": "", "removal": "", "weight": 0, "barrier__theme": ""})
        lever.append(r2)
    return base, lever


def test_the_shift_is_counted_from_the_two_arms_on_the_same_twins():
    base_rows, lever_rows = _rows({"a5": "yes", "a6": "yes"})
    stages = jn.stages_of(SPEC)
    c_agg = jn.aggregate(base_rows, SPEC)
    hc.apply(c_agg, denominator=hc.denominator_for({}, FRAME), stages=stages)
    l_agg = jn.aggregate(lever_rows, SPEC)
    c_map = {r["agent_id"]: {"answer": r["answer"], "segments": r["segments"]} for r in base_rows}
    l_map = {r["agent_id"]: {"answer": r["answer"], "segments": r["segments"]} for r in lever_rows}
    s = lv.shift(control_agg=c_agg, lever_agg=l_agg, control_rows=c_map, lever_rows=l_map, candidate_id="step3->step4", seed=1)
    assert s["available"] and s["step"] == 3 and s["from"]["label"] == "Started"
    # step3 → step4: 4 at risk (a5, a6, a7, a8); 2 through before, 4 after → +0.5, both movers up
    assert s["conversion"]["then"] == 0.5 and s["conversion"]["now"] == 1.0 and s["conversion"]["lift"] == 0.5 and s["conversion"]["n"] == 4
    assert s["movement"] == {"up": 2, "down": 0, "unchanged": 2, "n": 4}
    assert s["stuck"] == {"then": 2, "now": 0}
    # the end of the journey is unchanged (progress does not move 'reached')
    assert s["end"]["then"] == s["end"]["now"] and s["end"]["lift"] == 0.0
    # people moved: the at-risk headcount × the lift
    at_risk = c_agg["transitions"][2]["at_risk_people"]
    assert s["people"]["moved"] == round(at_risk * 0.5) and s["people"]["stuck_now"] == 0 and s["people"]["basis"] == "official_statistic"
    assert "deprivation" in s["segments"] and "a shift of +50 points" in s["sentence"] and "2 twins moved through" in s["sentence"]
    # a lever that does nothing: zero shift, not significant
    same_c, same_l = _rows({})
    s0 = lv.shift(control_agg=jn.aggregate(same_c, SPEC), lever_agg=jn.aggregate(same_l, SPEC),
                  control_rows={r["agent_id"]: {"answer": r["answer"], "segments": r["segments"]} for r in same_c},
                  lever_rows={r["agent_id"]: {"answer": r["answer"], "segments": r["segments"]} for r in same_l}, candidate_id="step3->step4")
    assert s0["conversion"]["lift"] == 0.0 and not s0["conversion"]["significant"] and "not distinguishable from zero" in s0["sentence"]
    # an unknown candidate: nothing
    assert lv.shift(control_agg=c_agg, lever_agg=l_agg, control_rows=c_map, lever_rows=l_map, candidate_id="step9->step10")["available"] is False


def test_a_lever_run_becomes_a_record_with_its_rule_and_the_prompt_line():
    base_rows, lever_rows = _rows({"a5": "yes", "a6": "yes"})
    stages = jn.stages_of(SPEC)
    c_agg = jn.aggregate(base_rows, SPEC)
    hc.apply(c_agg, denominator=hc.denominator_for({}, FRAME), stages=stages)
    l_agg = jn.aggregate(lever_rows, SPEC)
    s = lv.shift(control_agg=c_agg, lever_agg=l_agg, control_rows={r["agent_id"]: {"answer": r["answer"], "segments": r["segments"]} for r in base_rows},
                 lever_rows={r["agent_id"]: {"answer": r["answer"], "segments": r["segments"]} for r in lever_rows}, candidate_id="step3->step4", seed=1)
    s["rule"] = {"rule_id": "r1", "lever": "nurse phone line", "deltas": RULE["deltas"], "applies_to": {}, "reviewed_by": "M. Hunt", "reviewed_at": "2026-09-29"}
    s["covered"] = 8
    e = SimpleNamespace(id="e1", name="Lever: nurse phone line", seed=1, model="m", created_at=None, results={"lever": s, "comparisons": []})
    r = rec.record_from_experiment(e)
    assert r["kind"] == "lever" and r["label"] == "Lever: nurse phone line — shift at Started → Still on it at 6 months"
    assert r["estimate"]["format"] == "lift" and r["estimate"]["value"] == 0.5 and r["lever"]["rule"]["reviewed_by"] == "M. Hunt" and r["provenance"]["rule_id"] == "r1"
    assert any("calibration rule 'nurse phone line' (reviewed by M. Hunt)" in c for c in r["caveats"])
    text, _ = rec.records_block([r])
    assert "lever run under rule 'nurse phone line' (reviewed by M. Hunt; dials friction.emotional_resistance -3, trust.reliability +2; applies to everyone)" in text
    assert "people moved" in text and "end of journey" in text
    assert "MODELLED SHIFT" in rec.FIGURE_RULES
    # not yet counted: no record
    assert rec.record_from_experiment(SimpleNamespace(id="e2", results={"lever": {"available": False}, "comparisons": []})) is None


def test_the_run_refuses_without_a_reviewed_rule_and_never_asks_the_twins_to_imagine(monkeypatch):
    async def no_rules(session_id):
        return [{"id": "d1", "lever": "bus subsidy", "status": "draft", "applies_to": {}, "deltas": {"friction.money_pain": -2}}]
    monkeypatch.setattr(lv, "rules_for_session", no_rules)
    rule, named = asyncio.run(lv.find_rule("s", "bus subsidy"))
    assert rule is None and [n["id"] for n in named] == ["d1"]
    rule2, _ = asyncio.run(lv.find_rule("s", "Bus Subsidy for Q1"))
    assert rule2 is None
    async def reviewed(session_id):
        return [{"id": "r1", "lever": "bus subsidy", "status": "reviewed", "applies_to": {}, "deltas": {"friction.money_pain": -2}}]
    monkeypatch.setattr(lv, "rules_for_session", reviewed)
    rule3, _ = asyncio.run(lv.find_rule("s", "a bus subsidy"))
    assert rule3 and rule3["id"] == "r1"
    rule4, _ = asyncio.run(lv.find_rule("s", "anything", rule_id="r1"))
    assert rule4 and rule4["id"] == "r1"
