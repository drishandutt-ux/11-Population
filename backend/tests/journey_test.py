"""Journey (brief L7-01): candidate outcomes, one per step where the population drops off.

Run:  cd backend && pytest tests/journey_test.py -q
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.measurement.instruments import journey as jn  # noqa: E402
from app.services.simulation import records as rec  # noqa: E402
from app.services.simulation import structure as st  # noqa: E402

STAGES = [{"label": "At risk", "definition": "meets the criteria, unaware"}, {"label": "Assessed", "definition": "seen by a GP"},
          {"label": "Started", "definition": "first dose taken"}, {"label": "Still on it at 6 months"}]
SPEC = {"stages": STAGES, "seed": 1}


def _row(k, reached, progress, barrier="", theme="", removal="", weight=0, dep="Q1 most deprived", who="myself"):
    return {"agent_id": f"a{k}", "agent": {"name": f"N{k}", "role": "r"}, "segments": {"stance": "direct", "deprivation": dep},
            "answer": {"reasoning": "why", "answering_for": who, "reached": reached, "progress": progress, "barrier": barrier,
                       "barrier__theme": theme, "removal": removal, "removal__theme": removal, "weight": weight}}


ROWS = [
    _row(1, "step1", "no", "cannot get a GP slot", "GP access", "walk-in clinic", 90),
    _row(2, "step1", "unlikely", "8am phone scramble", "GP access", "walk-in clinic", 70),
    _row(3, "step1", "yes"),
    _row(4, "step2", "no", "£9.90 an item", "prescription cost", "free scripts", 80, dep="Q5 least deprived"),
    _row(5, "step2", "yes", dep="Q5 least deprived"),
    _row(6, "step3", "no", "side effects in week 6", "side effects", "nurse call", 60, dep="Q5 least deprived", who="people I serve"),
    _row(7, "step4", "yes", dep="Q5 least deprived"),
    _row(8, "step4", "yes"),
]


def test_stages_are_normalised_with_ordered_keys_from_dicts_strings_or_lines():
    got = jn.stages_of({"stages": STAGES})
    assert [s["key"] for s in got] == ["step1", "step2", "step3", "step4"] and got[0]["label"] == "At risk" and got[0]["definition"] == "meets the criteria, unaware"
    assert [s["label"] for s in jn.stages_of({"stages": ["A", " B ", ""]})] == ["A", "B"]
    assert [s["key"] for s in jn.stages_of({"stages": "one\ntwo\n\nthree"})] == ["step1", "step2", "step3"]
    assert jn.stages_of({}) == []


def test_the_schema_and_the_question_carry_the_steps_and_validation_bounds_them():
    inst = jn.INSTRUMENT
    schema = inst.schema_for(SPEC)
    assert schema["properties"]["reached"]["enum"] == ["step1", "step2", "step3", "step4"]
    assert schema["properties"]["progress"]["enum"] == ["yes", "unlikely", "no"]
    q = inst.question_for(SPEC)
    assert "1. [step1] At risk — meets the criteria, unaware" in q and "4. [step4] Still on it at 6 months" in q
    assert inst.validate(SPEC) == []
    assert "at least 3" in inst.validate({"stages": ["a", "b"]})[0]
    assert "at most 8" in inst.validate({"stages": [str(i) for i in range(9)]})[0]
    assert "Two steps are called" in inst.validate({"stages": ["a", "b", "a"]})[0]


def test_the_funnel_counts_who_reached_each_step():
    stages = jn.stages_of(SPEC)
    f = jn.funnel_of(ROWS, stages)
    assert [x["reached"] for x in f] == [8, 5, 3, 2] and [x["at"] for x in f] == [3, 2, 1, 2]
    assert f[0]["share"] == 1.0 and round(f[3]["share"], 3) == 0.25 and f[1]["label"] == "Assessed"


def test_transitions_give_conversion_gap_stuck_and_ranked_barriers_per_step():
    stages = jn.stages_of(SPEC)
    t = jn.transitions_of(ROWS, stages, seed=1)
    assert [x["id"] for x in t] == ["step1->step2", "step2->step3", "step3->step4"]
    # step1 → step2: 8 at risk; 5 already past + 1 at step1 going on = 6 through; 2 stuck
    a = t[0]
    assert a["n"] == 8 and a["through"] == 6 and a["stuck"] == 2 and a["conversion"] == 0.75 and a["gap"] == 0.25
    assert a["barriers"][0]["theme"] == "GP access" and a["barriers"][0]["count"] == 2 and a["barriers"][0]["agent_ids"] == ["a1", "a2"]
    assert a["barriers"][0]["weight_mean"] == 80.0 and a["barriers"][0]["removals"][0]["value"] == "walk-in clinic"
    # step2 → step3: 5 at risk (a4..a8); 3 past + a5 going on = 4 through; a4 stuck
    b = t[1]
    assert b["n"] == 5 and b["through"] == 4 and b["stuck"] == 1 and b["barriers"][0]["theme"] == "prescription cost"
    # step3 → step4: 3 at risk; 2 past; a6 stuck
    c = t[2]
    assert c["n"] == 3 and c["stuck"] == 1 and c["barriers"][0]["theme"] == "side effects"
    assert a["equity"]["available"] and "deprivation" in a["segments"]
    assert a["label"] == "Share of those at 'At risk' who reach 'Assessed'"


def test_candidates_are_the_steps_with_someone_stuck_ranked_by_stuck_then_gap():
    stages = jn.stages_of(SPEC)
    cands = jn.candidates_of(jn.transitions_of(ROWS, stages, seed=1))
    assert [c["id"] for c in cands] == ["step1->step2", "step3->step4", "step2->step3"]   # 2 stuck; then 1 stuck with gap .33 before 1 stuck with gap .20
    assert [c["rank"] for c in cands] == [1, 2, 3]
    # a step nobody is stuck at is not a candidate
    rows = [_row(1, "step4", "yes"), _row(2, "step2", "yes"), _row(3, "step1", "yes")]
    assert jn.candidates_of(jn.transitions_of(rows, stages)) == []


def test_the_aggregate_carries_the_headline_the_funnel_the_candidates_and_a_sentence():
    agg = jn.aggregate(ROWS, SPEC)
    assert agg["n"] == 8 and agg["headline"]["metric"] == "completed_share" and agg["headline"]["successes"] == 2
    assert agg["headline"]["label"] == "Reach 'Still on it at 6 months'"
    assert len(agg["funnel"]) == 4 and len(agg["transitions"]) == 3 and agg["candidates"][0]["id"] == "step1->step2"
    assert agg["sentence"].startswith("25% reach 'Still on it at 6 months'")
    assert "the biggest drop-off is At risk → Assessed: 75% get through, 2 twins stuck, top barrier \"GP access\"" in agg["sentence"]
    assert agg["answering_for"][0]["value"] == "myself" and agg["barriers_coded"] is True and "deprivation" in agg["segments"]
    assert jn.aggregate([], SPEC)["n"] == 0
    assert "at least two steps" in jn.aggregate(ROWS, {"stages": ["one"]})["sentence"]
    # a twin who names a step that is not on the journey is left out rather than miscounted
    assert jn.aggregate([_row(9, "step9", "yes")], SPEC)["n"] == 0


def test_a_journey_probe_becomes_a_record_with_stable_candidate_ids_and_the_prompt_line():
    agg = jn.aggregate(ROWS, SPEC)
    p = SimpleNamespace(id="j1", instrument="journey", spec=SPEC, seed=1, schema_id="journey.v1", prompt_hash="h", model="m",
                        agent_count=8, answer_count=8, created_at=None, aggregates=agg)
    r = rec.record_from_probe(p)
    assert r["label"] == "Where the population drops off on the way to: Still on it at 6 months"
    assert [c["id"] for c in r["candidates"]] == ["j1:step1->step2", "j1:step3->step4", "j1:step2->step3"]
    c = r["candidates"][0]
    assert c["rank"] == 1 and c["from"]["label"] == "At risk" and c["conversion"] == 0.75 and c["stuck"] == 2
    assert c["barriers"][0]["theme"] == "GP access" and c["barriers"][0]["agent_ids"] == ["a1", "a2"] and c["equity"]["available"]
    assert 5 <= c["confidence"]["score"] <= 95 and [s["key"] for s in r["journey"]] == ["step1", "step2", "step3", "step4"] and len(r["funnel"]) == 4
    text, _ = rec.records_block([r])
    assert "candidates ranked: 1. At risk → Assessed (75% get through, 2 of 8 stuck, top barrier GP access)" in text
    assert "funnel: At risk 100% → Assessed 62% → Started 38% → Still on it at 6 months 25%" in text
    assert "candidates ranked" in rec.FIGURE_RULES
    # a non-journey record carries none
    v = SimpleNamespace(id="v1", instrument="verdict", spec={"question": "Q"}, seed=1, schema_id="v", prompt_hash="h", model="m", agent_count=3, answer_count=3, created_at=None,
                        aggregates={"n": 3, "headline": {"metric": "for_share", "label": "In favour", "share": 0.6, "low": 0.2, "high": 0.9, "n": 3, "successes": 2}, "sentence": "s", "segments": {}})
    vr = rec.record_from_probe(v)
    assert vr["candidates"] == [] and vr["journey"] == [] and vr["funnel"] == []


def test_the_report_structure_picks_the_newest_journey_record():
    agg = jn.aggregate(ROWS, SPEC)
    p = SimpleNamespace(id="j1", instrument="journey", spec=SPEC, seed=1, schema_id="journey.v1", prompt_hash="h", model="m",
                        agent_count=8, answer_count=8, created_at=None, aggregates=agg)
    r = rec.record_from_probe(p)
    c = st.candidates_from_records([{"id": "x", "candidates": []}, r])
    assert c["record_id"] == "j1" and c["n"] == 8 and [f["label"] for f in c["funnel"]] == ["At risk", "Assessed", "Started", "Still on it at 6 months"]
    assert c["items"][0]["from"] == "At risk" and c["items"][0]["to"] == "Assessed" and c["items"][0]["stuck"] == 2
    assert c["items"][0]["barriers"][0]["theme"] == "GP access" and c["items"][0]["barriers"][0]["removals"] == ["walk-in clinic"]
    assert st.candidates_from_records([{"id": "x", "candidates": []}]) is None
    s = st.build_structure(session_query="Q", records=[r], headline=None, positions=[], evidence=[], frame={"level": "none"}, cited_record_ids=[], claimed_band=None)
    assert s["outcome"]["candidates"]["record_id"] == "j1"


def test_the_instrument_is_declared_for_the_picker_the_builder_and_the_ab_test():
    from app.services.measurement import instruments
    instruments._load()
    inst = instruments.get("journey")
    assert inst and not inst.hidden and inst.page == "journey" and inst.form == "journey"
    assert inst.inputs[0].key == "stages" and inst.inputs[0].required
    assert [m.key for m in inst.metrics] == ["progress", "weight"] and inst.metrics[0].primary
    assert inst.metrics[0].value({"progress": "yes"}) == 1.0 and inst.metrics[0].value({"progress": "no"}) == 0.0
    assert inst.decision_key == "progress" and inst.driver_key == "barrier__theme"


def test_the_candidate_barriers_are_traced_through_the_transitions_and_shared_with_the_candidates():
    agg = jn.aggregate(ROWS, SPEC)
    import json
    agg = json.loads(json.dumps(agg))   # as it comes back from the database: no shared objects
    targets = jn._candidate_barriers(agg)
    assert len(targets) == 3
    targets[0]["evidence"] = [{"unit_id": "u1"}]
    # the candidates were rebuilt from the transitions, so the evidence lands in both
    assert agg["candidates"][0]["barriers"][0]["evidence"] == [{"unit_id": "u1"}]
