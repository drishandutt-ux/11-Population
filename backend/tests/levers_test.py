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


def test_a_rule_must_name_real_dials_within_its_bound_and_a_basis_and_evidence_is_optional():
    ok = {"lever": "nurse phone line", "deltas": {"friction.emotional_resistance": -3}, "bound": 4, "evidence": [{"ref": "Audit"}], "basis": "because"}
    assert lv.validate_rule(ok) == []
    # Evidence is optional — a rule without it is an assumption, and says so.
    assert lv.validate_rule({**ok, "evidence": []}) == []
    assert lv.basis_class({**ok, "evidence": []}) == lv.BASIS_ASSUMPTION
    assert lv.basis_class({**ok, "evidence": [{"ref": "  "}]}) == lv.BASIS_ASSUMPTION
    assert lv.basis_class(ok) == lv.BASIS_EVIDENCE
    assert lv.lever_spec({**ok, "id": "r", "evidence": []}, {"id": "c"})["basis_class"] == lv.BASIS_ASSUMPTION
    assert any("needs the lever" in p for p in lv.validate_rule({**ok, "lever": ""}))
    assert any("not a dial" in p for p in lv.validate_rule({**ok, "deltas": {"friction.made_up": -1}}))
    assert any("not a dial" in p for p in lv.validate_rule({**ok, "deltas": {"nodot": -1}}))
    assert any("outside the rule's bound" in p for p in lv.validate_rule({**ok, "deltas": {"friction.time_cost": -5}}))
    assert any("is zero" in p for p in lv.validate_rule({**ok, "deltas": {"friction.time_cost": 0}}))
    assert any("whole number" in p for p in lv.validate_rule({**ok, "deltas": {"friction.time_cost": "lots"}}))
    assert any("at least one dial" in p for p in lv.validate_rule({**ok, "deltas": {}}))
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
    assert "lever run under rule 'nurse phone line' (reviewed by M. Hunt; 0 evidence line(s); dials friction.emotional_resistance -3, trust.reliability +2; applies to everyone)" in text
    assert "ASSUMPTION" not in text
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


def test_an_assumption_run_reads_as_a_what_if_and_the_record_says_so():
    base_rows, lever_rows = _rows({"a5": "yes", "a6": "yes"})
    c_agg, l_agg = jn.aggregate(base_rows, SPEC), jn.aggregate(lever_rows, SPEC)
    c_map = {r["agent_id"]: {"answer": r["answer"], "segments": r["segments"]} for r in base_rows}
    l_map = {r["agent_id"]: {"answer": r["answer"], "segments": r["segments"]} for r in lever_rows}
    s = lv.shift(control_agg=c_agg, lever_agg=l_agg, control_rows=c_map, lever_rows=l_map, candidate_id="step3->step4", seed=1, assumed=True)
    assert s["assumed"] and s["sentence"].startswith("Assumed effect, not a forecast")
    plain = lv.shift(control_agg=c_agg, lever_agg=l_agg, control_rows=c_map, lever_rows=l_map, candidate_id="step3->step4", seed=1)
    assert not plain["assumed"] and plain["sentence"].startswith("With the lever in place")
    s["rule"] = {"rule_id": "r1", "lever": "nurse phone line", "deltas": RULE["deltas"], "applies_to": {}, "reviewed_by": "M. Hunt", "reviewed_at": "2026-09-29",
                 "basis_class": "assumption", "evidence_count": 0}
    e = SimpleNamespace(id="e1", name="Lever", seed=1, model="m", created_at=None, results={"lever": s})
    r = rec.record_from_lever(e)
    assert r["label"].startswith("Assumed effect:") and r["lever"]["assumed"] and any("what-if, not a forecast" in c for c in r["caveats"])
    text, _ = rec.records_block([r])
    assert "ASSUMPTION" in text and "NO evidence" in text
    assert "ASSUMPTION" in rec.FIGURE_RULES


def test_the_system_draft_cites_only_the_material_it_was_shown_and_keeps_real_dials():
    pool = lv.evidence_pool(
        {"from": {"label": "Tried it once"}, "to": {"label": "Uses it weekly"}, "conversion": 0.48, "stuck": 12, "at_risk": 23,
         "barriers": [{"theme": "Liner cost", "count": 3, "removals": ["free liners"], "reach": "partner", "lever": "free liners",
                       "evidence": [{"unit_id": "u1", "title": "Pilot liner sub-study", "source": "pilot report", "provenance_class": "grey", "twins": 2}]}]},
        {"facts": [{"source": "Pilot report", "year": "2025", "statistic": "six-month use with free liners", "value": "57%", "provenance_class": "grey"}],
         "items": [{"title": "Off topic", "on_topic": False}, {"title": "Council brief", "source_ref": "brief.md", "on_topic": True, "excerpt": "liners free"}]},
    )
    assert [p["handle"] for p in pool] == ["E1", "E2", "E3"] and pool[0]["kind"] == "cited" and pool[1]["kind"] == "fact"
    raw = {"description": "Liners arrive free with the caddy", "applies_to": {"deprivation": ["Q1 most deprived", "nonsense"], "stance": [], "age_band": []},
           "deltas": [{"dial": "friction.money_pain", "points": -2, "why": "nothing to buy"}, {"dial": "friction.made_up", "points": -3, "why": "x"},
                      {"dial": "habit.action_simplicity", "points": 9, "why": "easier"}, {"dial": "trust.reliability", "points": 0, "why": "none"}],
           "evidence": [{"handle": "e2", "note": "57% vs 44%"}, {"handle": "E9", "note": "invented"}], "basis": "Free liners remove the cost."}
    f = lv.clean_draft(raw, lever="Free caddy liners", pool=pool)
    assert f["deltas"] == {"friction.money_pain": -2, "habit.action_simplicity": 4}          # unknown dial dropped, clamped to the bound, zero dropped
    assert f["applies_to"] == {"deprivation": ["Q1 most deprived"]}                          # only allowed values
    assert len(f["evidence"]) == 1 and f["evidence"][0]["ref"].startswith("Pilot report 2025")   # the invented handle is gone
    assert f["author"] == lv.SYSTEM_AUTHOR and "Dials:" in f["basis"] and lv.validate_rule(f) == []
    assert lv.basis_class(f) == lv.BASIS_EVIDENCE
    # nothing to cite → an honest assumption, still a valid draft
    g = lv.clean_draft({**raw, "evidence": [], "basis": ""}, lever="Free caddy liners", pool=[])
    assert g["evidence"] == [] and lv.basis_class(g) == lv.BASIS_ASSUMPTION and lv.validate_rule(g) == []


# ── amendments: the journey refreshed with every signed rule in place ─────────

RULE2 = {"id": "r2", "lever": "free prescriptions", "description": "Prescriptions are free for this group", "applies_to": {"deprivation": ["Q1 most deprived"]},
         "deltas": {"friction.money_pain": -3}, "bound": 4, "status": "reviewed", "reviewed_by": "M. Hunt", "reviewed_at": "2026-09-30T00:00:00", "evidence": [], "basis": "assumed"}
DRAFT = {**RULE2, "id": "d1", "lever": "bus subsidy", "status": "draft", "reviewed_by": ""}


def test_an_amendment_pack_holds_only_signed_rules_and_stacks_the_ones_that_cover_a_twin():
    pack = lv.amendment_pack([RULE, RULE2, DRAFT])
    assert [r["rule_id"] for r in pack] == ["r1", "r2"]
    assert pack[0]["basis_class"] == lv.BASIS_EVIDENCE and pack[1]["basis_class"] == lv.BASIS_ASSUMPTION
    q1, q5 = {"deprivation": "Q1 most deprived"}, {"deprivation": "Q5 least deprived"}
    assert [r["rule_id"] for r in lv.covering(pack, q1)] == ["r1", "r2"] and [r["rule_id"] for r in lv.covering(pack, q5)] == ["r1"]
    dials = {"friction": {"emotional_resistance": 8, "money_pain": 7}, "trust": {"reliability": 9}}
    out = lv.amended_dials(dials, pack, q1)
    assert out["friction"]["emotional_resistance"] == 5 and out["trust"]["reliability"] == 10 and out["friction"]["money_pain"] == 4
    assert lv.amended_dials(dials, pack, q5)["friction"]["money_pain"] == 7          # the second rule does not reach Q5
    assert dials["friction"]["money_pain"] == 7                                        # the original is untouched
    # the twin is told every change that reaches it, together, as a world — and nothing when none does
    block = lv.amendments_block(pack, q1)
    assert block.startswith("CHANGES NOW IN PLACE") and "1. A nurse phone line in weeks 4-12 of treatment." in block and "2. Prescriptions are free for this group." in block
    assert lv.amendments_block(pack, q5).startswith("A CHANGE NOW IN PLACE") and "Prescriptions" not in lv.amendments_block(pack, q5)
    assert lv.amendments_block(lv.amendment_pack([RULE2]), q5) == ""


def test_the_growth_is_counted_step_by_step_against_the_base_run_on_the_same_twins():
    base_rows = [_row(1, "step1", "no", "no slot", "GP access", "walk-in", 90), _row(2, "step1", "yes"), _row(3, "step2", "yes"),
                 _row(4, "step2", "no", "cost", "cost", "free", 80, dep="Q5 least deprived"), _row(5, "step3", "no", "side effects", "side effects", "nurse", 60),
                 _row(6, "step3", "no", "side effects", "side effects", "nurse", 60, dep="Q5 least deprived"), _row(7, "step4", "yes", dep="Q5 least deprived"), _row(8, "step4", "yes")]
    # with the rules in place: a1 moves from step1 to step2, a5 and a6 reach step4, a8 unchanged
    moved = {"a1": ("step2", "yes"), "a5": ("step4", "yes"), "a6": ("step4", "yes")}
    amended_rows = []
    for r in base_rows:
        r2 = {**r, "answer": dict(r["answer"])}
        if r["agent_id"] in moved:
            r2["answer"].update({"reached": moved[r["agent_id"]][0], "progress": moved[r["agent_id"]][1], "barrier": "", "removal": "", "weight": 0, "barrier__theme": ""})
        amended_rows.append(r2)
    stages = jn.stages_of(SPEC)
    b_agg = jn.aggregate(base_rows, SPEC)
    hc.apply(b_agg, denominator=hc.denominator_for({}, FRAME), stages=stages)
    a_agg = jn.aggregate(amended_rows, SPEC)
    hc.apply(a_agg, denominator=hc.denominator_for({}, FRAME), stages=stages)
    b_map = {r["agent_id"]: {"answer": r["answer"], "segments": r["segments"]} for r in base_rows}
    a_map = {r["agent_id"]: {"answer": r["answer"], "segments": r["segments"]} for r in amended_rows}
    pack = lv.amendment_pack([RULE, RULE2])
    g = lv.growth(base_agg=b_agg, amended_agg=a_agg, base_rows=b_map, amended_rows=a_map, pack=pack, seed=1)
    assert g["available"] and g["n"] == 8 and g["covered"] == 8 and g["assumed"] is True and len(g["rules"]) == 2
    # step 2 (index 1): reached by 6 of 8 then, 7 of 8 now; the end (step4): 2 then, 4 now
    f = {x["key"]: x for x in g["funnel"]}
    assert f["step1"]["then"] == 1.0 and f["step1"]["now"] == 1.0 and f["step1"]["lift"] == 0.0
    assert f["step2"]["reached_then"] == 6 and f["step2"]["reached_now"] == 7 and f["step2"]["lift"] == 0.125
    assert f["step4"]["reached_then"] == 2 and f["step4"]["reached_now"] == 4 and f["step4"]["lift"] == 0.25
    assert g["end"]["then"] == 0.25 and g["end"]["now"] == 0.5 and g["end"]["label"] == stages[-1]["label"]
    assert g["movement"] == {"up": 3, "down": 0, "unchanged": 5, "n": 8}
    # people: the base run's headcount at each step, and the amended run's, both on the same denominator
    assert f["step4"]["people_then"] == b_agg["funnel"][3]["people"] and f["step4"]["people_now"] == a_agg["funnel"][3]["people"]
    assert f["step4"]["people_moved"] == a_agg["funnel"][3]["people"] - b_agg["funnel"][3]["people"] > 0
    assert g["end"]["people_moved"] == f["step4"]["people_moved"]
    # the transition at step 3 → 4: 4 at risk, 2 through then, 4 now
    t = {x["id"]: x for x in g["transitions"]}
    assert t["step3->step4"]["lift"] == 0.5 and t["step3->step4"]["up"] == 2 and t["step3->step4"]["stuck_then"] == 2 and t["step3->step4"]["stuck_now"] == 0
    assert "Assumed effect, not a forecast" in g["sentence"] and "2 signed rules in place" in g["sentence"] and "growth of +25 points" in g["sentence"]
    assert "3 twins moved further along the journey" in g["sentence"] and "people at the end of the journey" in g["sentence"]
    # every rule anchored on evidence: a plain forecast sentence
    g2 = lv.growth(base_agg=b_agg, amended_agg=a_agg, base_rows=b_map, amended_rows=a_map, pack=lv.amendment_pack([RULE]), seed=1)
    assert g2["sentence"].startswith("With 1 signed rule in place")
    # nothing in common: refused
    assert lv.growth(base_agg=b_agg, amended_agg=a_agg, base_rows=b_map, amended_rows={}, pack=pack)["available"] is False
    # the record carries the growth and the records block says the figures are the amended ones
    p = SimpleNamespace(id="p2", session_id="s", instrument="journey", spec={**SPEC, "amendments": {"base_probe_id": "p1", "rules": pack}}, seed=1, model="m",
                        prompt_hash="h", aggregates={**a_agg, "amended": g}, status="complete", completed_at=None, created_at=None, agent_count=8, answer_count=8, failed_count=0)
    r = rec.record_from_probe(p)
    assert r["amended"]["available"] and len(r["amended"]["rules"]) == 2
    text, _ = rec.records_block([r])
    assert "AMENDED RUN" in text and "2 signed rule(s) in place" in text and "NO evidence, an assumption" in text and "growth of +25 points" in text


# ── why it moved: the twins' own words behind the count ──────────────────────

ST = jn.stages_of(SPEC)

def _arms():
    """Four twins at the candidate's step (k=0): one the lever moves through, one it pushes back,
    one still stuck under the same barrier theme as a fifth, one through in both arms."""
    def r(k, reached, progress, barrier="", theme="", reasoning="why", removal=""):
        row = _row(k, reached, progress, barrier, theme, removal, 50)
        row["answer"]["reasoning"] = reasoning
        row["agent"] = {"name": f"N{k}", "role": "patient", "segment": "s1"}
        return row
    control = {
        "a1": r(1, "step1", "no", "the 8am phone scramble", "GP access", "I gave up on the phone queue. Nobody rang me."),
        "a2": r(2, "step1", "yes", reasoning="I would go along. It is on my way."),
        "a3": r(3, "step1", "no", "cannot get a GP slot", "GP access", "No slot, no test."),
        "a4": r(4, "step1", "no", "the urine sample bit", "sample collection", "I will not do the sample at work."),
        "a5": r(5, "step2", "yes", reasoning="Already done it."),
    }
    lever = {
        "a1": r(1, "step2", "yes", reasoning="The pharmacist rang me the week the script sat there. That call got me in. I trust them more now."),
        "a2": r(2, "step1", "unlikely", "a stranger ringing about my prescription", "privacy", "A call out of the blue about my pills feels like being checked up on."),
        "a3": r(3, "step1", "no", "cannot get a GP slot", "GP access", "No slot, no test."),
        "a4": r(4, "step1", "no", "the urine sample bit", "sample collection", "Still not doing the sample at work."),
        "a5": r(5, "step2", "yes", reasoning="Already done it."),
    }
    return control, lever


def test_twin_moves_classes_every_twin_at_the_step_with_its_words_from_both_arms():
    control, lever = _arms()
    moves = lv.twin_moves(control_rows=control, lever_rows=lever, stages=ST, k=0)
    by = {m["agent_id"]: m for m in moves}
    assert by["a1"]["move"] == lv.MOVE_THROUGH and by["a2"]["move"] == lv.MOVE_BACK
    assert by["a3"]["move"] == lv.STILL_STUCK and by["a4"]["move"] == lv.STILL_STUCK and by["a5"]["move"] == lv.ALREADY_THROUGH
    # The words travel with the twin, labelled by stage, and the counts agree with the shift's movement.
    assert by["a1"]["then"]["barrier"] == "the 8am phone scramble" and by["a1"]["now"]["reached"] == ST[1]["label"]
    assert by["a1"]["name"] == "N1" and by["a1"]["role"] == "patient"
    assert sum(m["move"] == lv.MOVE_THROUGH for m in moves) == 1 and sum(m["move"] == lv.MOVE_BACK for m in moves) == 1


def test_reasons_uncoded_gives_each_mover_its_own_words_and_groups_the_still_stuck_by_theme():
    control, lever = _arms()
    why = lv.reasons_uncoded(lv.twin_moves(control_rows=control, lever_rows=lever, stages=ST, k=0))
    assert why["n"] == {"through": 1, "back": 1, "still_stuck": 2, "already_through": 1} and why["coded"] is False
    # A mover speaks for itself: the first sentence of what it says under the lever, attributed.
    assert why["through"][0]["quote"] == "The pharmacist rang me the week the script sat there." and why["through"][0]["who"] == "N1, patient"
    # Falling back, the barrier it names now is the reason.
    assert why["back"][0]["reason"] == "a stranger ringing about my prescription"
    # Still stuck: the coded barrier themes, each with one twin's own words.
    assert [(r["reason"], r["n"]) for r in why["still_stuck"]] == [("GP access", 1), ("sample collection", 1)]
    assert why["sentence"].startswith("Why, in their words: 1 moved through — “") and "1 fell back" in why["sentence"] and "2 still stuck, mostly “GP access” (1)" in why["sentence"]


def test_coded_reasons_keep_only_verbatim_quotes_and_count_every_twin_once():
    control, lever = _arms()
    moves = lv.twin_moves(control_rows=control, lever_rows=lever, stages=ST, k=0)
    through = [m for m in moves if m["move"] == lv.MOVE_THROUGH]
    # A paraphrased quote is replaced by the twin's own first sentence; a twin listed twice counts once.
    coded = lv._coded_group([{"reason": "someone rang them before the script lapsed", "twins": ["T1", "T1"], "quote_twin": "T1", "quote": "The pharmacist phoned me"}], through)
    assert coded == [{"reason": "someone rang them before the script lapsed", "n": 1, "twins": ["N1, patient"],
                      "quote": "The pharmacist rang me the week the script sat there.", "who": "N1, patient"}]
    # A verbatim sentence survives as written; a twin the coder left out becomes its own reason.
    coded = lv._coded_group([{"reason": "the call got them in", "twins": [], "quote_twin": "T1", "quote": "That call got me in."}], through)
    assert coded[0]["quote"] == "The pharmacist rang me the week the script sat there." and coded[0]["n"] == 1


def test_why_moved_falls_back_to_the_uncoded_form_when_the_coder_fails(monkeypatch):
    control, lever = _arms()
    moves = lv.twin_moves(control_rows=control, lever_rows=lever, stages=ST, k=0)

    async def boom(*a, **k):
        raise RuntimeError("no model")
    import app.services.evidence.llm as llm
    monkeypatch.setattr(llm, "analyze", boom)
    why = asyncio.run(lv.why_moved(moves, session_id="s"))
    assert why["coded"] is False and why["n"]["through"] == 1 and why["through"][0]["who"] == "N1, patient"


def test_the_lever_record_carries_the_why():
    control, lever = _arms()
    why = lv.reasons_uncoded(lv.twin_moves(control_rows=control, lever_rows=lever, stages=ST, k=0))
    e = SimpleNamespace(id="e1", name="Lever: x", model="m", seed=1, created_at=None, results={"lever": {
        "available": True, "candidate_id": "c1", "from": {"label": "A"}, "to": {"label": "B"}, "conversion": {"then": 0.5, "now": 0.75, "lift": 0.25, "low": 0.1, "high": 0.4, "n": 4, "significant": True},
        "movement": {"up": 1, "down": 1, "unchanged": 2, "n": 4}, "end": {}, "segments": {}, "rule": RULE, "sentence": "s. " + why["sentence"], "why": why}})
    rec_ = rec.record_from_lever(e)
    assert rec_["lever"]["why"]["n"]["through"] == 1 and "Why, in their words" in rec_["sentence"]


def test_twin_moves_over_the_whole_journey_reads_how_far_each_twin_gets():
    control, lever = _arms()
    control["a5"]["answer"]["reached"] = lever["a5"]["answer"]["reached"] = ST[-1]["key"]
    # a5 is at the end in both runs; a1 gets further (step1 → step2); a2 stays at step1 (its progress changed, not its placement).
    moves = {m["agent_id"]: m["move"] for m in lv.twin_moves(control_rows=control, lever_rows=lever, stages=ST, k=None)}
    assert moves == {"a1": lv.MOVE_THROUGH, "a2": lv.STILL_STUCK, "a3": lv.STILL_STUCK, "a4": lv.STILL_STUCK, "a5": lv.ALREADY_THROUGH}
    # A twin that now stops earlier is 'back' — the amended run's 'moved backward'.
    lever["a5"]["answer"]["reached"] = "step1"
    lever["a5"]["answer"]["progress"] = "no"
    lever["a5"]["answer"]["barrier"] = "the call felt like being checked up on"
    lever["a5"]["answer"]["reasoning"] = "I stopped answering. It felt like being checked up on."
    moves = lv.twin_moves(control_rows=control, lever_rows=lever, stages=ST, k=None)
    back = [m for m in moves if m["move"] == lv.MOVE_BACK]
    assert [m["agent_id"] for m in back] == ["a5"]
    why = lv.reasons_uncoded(moves)
    assert why["n"]["back"] == 1 and why["back"][0]["reason"] == "the call felt like being checked up on" and why["back"][0]["quote"] == "I stopped answering."
