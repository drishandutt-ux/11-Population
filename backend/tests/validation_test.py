"""Behavioural validation (brief L3-05): the battery and the confidence score it produces.

Run:  cd backend && pytest tests/validation_test.py -q
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.agents import validation as val  # noqa: E402


def agent(id_, segment=None, **kw):
    return SimpleNamespace(
        id=id_, name=kw.get("name", f"Twin {id_}"), age=44, role=kw.get("role", "GP partner"),
        background="Runs a list in Blackpool.", stance="direct", humanity=30, correlation="Prescribes weekly.",
        debate_style="Patient story first.", demographics={"region": "Blackpool"}, segment=segment,
        character=kw.get("character"), validation=kw.get("validation"),
    )


# ── stability: mechanical, no judge ───────────────────────────────────────────

def test_the_same_answer_twice_is_perfectly_stable():
    assert val.stability_of(7, 7) == 1.0


def test_a_one_point_drift_costs_almost_nothing():
    assert val.stability_of(7, 8) == 0.9


def test_a_wide_swing_scores_low():
    assert val.stability_of(2, 9) < 0.35


def test_an_unanswerable_pair_scores_nothing_rather_than_zero():
    assert val.stability_of(None, 4) is None      # None drops out of the blend; 0 would be a verdict


# ── the judge's marks become part scores ──────────────────────────────────────

def test_parts_read_the_judges_marks():
    judged = {
        "knowledge": [{"correct": "yes"}, {"correct": "partly"}],
        "refusal": [{"admitted": "yes"}, {"admitted": "no"}],
        "register": 8,
    }
    parts = val.score_parts(judged, 1.0)
    assert parts == {"stability": 1.0, "refusal": 0.5, "knowledge": 0.75, "register": 0.8}


def test_inventing_an_answer_to_an_unknowable_question_costs_the_refusal_part():
    strong = val.score_parts({"refusal": [{"admitted": "yes"}, {"admitted": "yes"}]}, None)
    weak = val.score_parts({"refusal": [{"admitted": "no"}, {"admitted": "no"}]}, None)
    assert strong["refusal"] == 1.0 and weak["refusal"] == 0.0
    assert val.headline(strong) > val.headline(weak)


def test_a_missing_part_drops_out_of_the_blend_instead_of_scoring_zero():
    # Only stability scored: the headline is the stability score, not 30% of it.
    assert val.headline({"stability": 1.0, "refusal": None, "knowledge": None, "register": None}) == 100
    assert val.headline({"stability": None, "refusal": None, "knowledge": None, "register": None}) is None


def test_the_headline_is_the_weighted_blend():
    parts = {"stability": 1.0, "refusal": 1.0, "knowledge": 0.0, "register": 0.0}
    assert val.headline(parts) == 55          # .30 + .25 of the weight scored full marks


def test_bands():
    assert val.band(90) == "strong" and val.band(60) == "fair" and val.band(10) == "weak"
    assert val.band(None) == "unscored"


# ── who gets scored ───────────────────────────────────────────────────────────

def test_a_small_population_is_scored_whole():
    agents = [agent(str(k), segment="A") for k in range(10)]
    assert len(val.pick_agents(agents, 250)) == 10


def test_a_large_population_is_sampled_evenly_across_segments():
    agents = [agent(f"a{k}", segment="A") for k in range(200)] + [agent(f"b{k}", segment="B") for k in range(20)]
    picked = val.pick_agents(agents, 40)
    by_seg = {}
    for a in picked:
        by_seg[a.segment] = by_seg.get(a.segment, 0) + 1
    assert len(picked) == 40
    assert by_seg["B"] == 20 and by_seg["A"] == 20    # the small segment is not drowned out


# ── what the population reads as ──────────────────────────────────────────────

def test_population_summary_names_the_weakest_part():
    agents = [
        agent("1", validation={"score": 80, "parts": {"stability": 1.0, "refusal": 0.2, "knowledge": 0.9, "register": 0.8}}),
        agent("2", validation={"score": 60, "parts": {"stability": 0.8, "refusal": 0.0, "knowledge": 0.7, "register": 0.7}}),
        agent("3", validation=None),
    ]
    out = val.population_summary(agents)
    assert out["scored"] == 2 and out["mean"] == 70
    assert out["weakest"] == "refusal"
    assert out["bands"] == {"strong": 1, "fair": 1}


def test_an_unvalidated_population_says_so_rather_than_scoring_zero():
    assert val.population_summary([agent("1"), agent("2")]) == {"scored": 0, "mean": None, "bands": {}, "weakest": None, "parts": {}}


def test_test_retest_across_the_population_uses_the_labs_agreement_rule():
    """Agreement only means something over many pairs — it counts an answer as agreeing when it
    lands within 10% of the spread the population actually produced. Here the spread is 2-9, so
    the tolerance is ±0.7: the two identical pairs agree, the 9→8 drift does not."""
    agents = [agent(str(k), validation={"score": 80, "parts": {}, "answers": {"a": {"scale": v}, "b": {"scale": w}}})
              for k, (v, w) in enumerate([(7, 7), (3, 3), (9, 8), (2, 9)])]
    out = val.population_summary(agents)
    assert out["retest"]["agreement"] == 0.5 and out["retest"]["n"] == 4


# ── the battery itself ────────────────────────────────────────────────────────

ITEMS = {
    "knowledge": [{"question": "What does the local formulary let you start?", "expected": "names the gate"}],
    "unknowable": [{"question": "What is Oxford's ICB spending on this?", "why": "another area's internal figure"}],
    "restatement": {"a": "How ready are you to prescribe it, 0-10?", "b": "On a 0-10 scale, how willing are you to start someone on it?", "scale": "0 = never, 10 = today"},
}


def test_the_stability_pair_is_asked_in_two_separate_contexts():
    a = val._answer_prompt(ITEMS, "a")
    b = val._answer_prompt(ITEMS, "b")
    assert ITEMS["restatement"]["a"] in a and ITEMS["restatement"]["b"] not in a
    assert ITEMS["restatement"]["b"] in b and ITEMS["restatement"]["a"] not in b
    # The second call asks for nothing but the scale, so it cannot be primed by the first.
    assert list(val._answer_schema(ITEMS, "b")["properties"]) == ["scale"]


def test_the_answer_prompt_licenses_not_knowing():
    assert "I don't know" in val._answer_prompt(ITEMS, "a")


def test_the_judge_sees_the_record_and_the_expected_answers_but_not_the_score():
    prompt = val._judge_prompt(val.persona_record(agent("1", character={"decision_rules": "Guideline first."})), ITEMS, {"k0": "The gate is two referrals.", "u0": "About £2m."})
    assert "Guideline first." in prompt and "names the gate" in prompt
    assert "another area's internal figure" in prompt and "About £2m." in prompt


def test_a_hand_authored_twin_is_its_own_segment_of_one():
    spec = val._segment_spec(agent("1", segment=None, role="Community pharmacist"), {})
    assert spec["name"] == "Community pharmacist"
    spec2 = val._segment_spec(agent("2", segment="Coastal GPs"), {"Coastal GPs": {"name": "Coastal GPs", "description": "d"}})
    assert spec2["description"] == "d"
