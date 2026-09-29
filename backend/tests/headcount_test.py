"""Headcounts (brief L7-02): the gap in individuals, from a denominator that is never invented.

Run:  cd backend && pytest tests/headcount_test.py -q
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.measurement import headcount as hc  # noqa: E402
from app.services.measurement.instruments import journey as jn  # noqa: E402
from app.services.simulation import records as rec  # noqa: E402
from app.services.simulation import structure as st  # noqa: E402
from tests.journey_test import ROWS, SPEC, STAGES  # noqa: E402

FRAME = {"sizing": {"tam": {"value": "141,000", "label": "adults in Blackpool", "source": "ONS mid-year estimates", "year": "2023"},
                    "sam": {"value": "34%", "label": "adults living with obesity", "source": "OHID Fingertips", "year": "2024"}, "som": {}}}


def test_figures_are_read_as_counts_or_shares_never_guessed():
    assert hc.parse_figure("141,000") == {"kind": "count", "value": 141000.0}
    assert hc.parse_figure("1.2 million") == {"kind": "count", "value": 1200000.0}
    assert hc.parse_figure("48k") == {"kind": "count", "value": 48000.0}
    assert hc.parse_figure("26%") == {"kind": "share", "value": 0.26}
    assert hc.parse_figure("26.4 per cent") == {"kind": "share", "value": 0.264}
    assert hc.parse_figure(5000) == {"kind": "count", "value": 5000.0}
    assert hc.parse_figure("") is None and hc.parse_figure("not on file") is None and hc.parse_figure(0) is None


def test_the_denominator_is_the_in_scope_slice_from_the_frame_or_the_analysts_own_figure():
    d = hc.denominator_from_frame(FRAME)
    assert d["people"] == 47940 and d["basis"] == "official_statistic" and d["derived"] == "SAM share × TAM" and "OHID" in d["source"] and d["year"] == "2024"
    d2 = hc.denominator_from_frame({"sizing": {"sam": {"value": "48,000", "label": "eligible adults", "source": "NICE", "year": "2025"}, "tam": {}}})
    assert d2["people"] == 48000 and d2["derived"] == "SAM"
    assert hc.denominator_from_frame({"sizing": {"sam": {"value": "34%"}, "tam": {}}}) is None       # a share with nothing to multiply through
    assert hc.denominator_from_frame(None) is None and hc.denominator_from_frame({"sizing": None}) is None
    own = hc.denominator_for({"denominator": {"people": "50,000", "source": "client channel data", "label": "patients on the register"}}, FRAME)
    assert own["people"] == 50000 and own["basis"] == "client_supplied" and own["source"] == "client channel data"
    assert hc.denominator_for({"denominator": {"people": ""}}, FRAME)["basis"] == "official_statistic"


def test_a_typed_denominator_is_not_mistaken_for_an_anchored_step():
    # Every step derived from a client-supplied denominator carries that basis, but only a step
    # with its own known figure is held fixed — the transitions keep their intervals.
    agg = jn.aggregate(ROWS, SPEC)
    stages = jn.stages_of(SPEC)
    hc.apply(agg, denominator=hc.denominator_for({"denominator": {"people": "141,000", "source": "client"}}, FRAME), stages=stages)
    t = agg["transitions"][0]
    assert t["basis"] == "client_supplied" and t["stuck_low"] < t["stuck_people"] < t["stuck_high"]
    assert agg["funnel"][1]["basis"] == "client_supplied" and not agg["funnel"][1].get("anchor")


def test_headcounts_multiply_the_shares_through_the_denominator_with_their_intervals():
    agg = jn.aggregate(ROWS, SPEC)
    stages = jn.stages_of(SPEC)
    hc.apply(agg, denominator=hc.denominator_for({}, FRAME), stages=stages)
    h = agg["headcount"]
    assert h["available"] and h["denominator"]["people"] == 47940 and not h["weighted"] and "47,940 people in scope" in h["sentence"]
    f = agg["funnel"]
    assert f[0]["people"] == 47940 and f[1]["people"] == round(47940 * 5 / 8) and f[3]["people"] == round(47940 * 0.25)
    assert f[0]["basis"] == "official_statistic" and f[3]["people_low"] < f[3]["people"] < f[3]["people_high"]
    # step1 → step2: 8 at risk, 75% through → 25% of 47,940 stuck
    t = agg["transitions"][0]
    assert t["at_risk_people"] == 47940 and t["through_people"] == round(47940 * 0.75) and t["stuck_people"] == 47940 - round(47940 * 0.75)
    assert t["stuck_low"] <= t["stuck_people"] <= t["stuck_high"] and t["basis"] == "official_statistic"
    # candidates carry the same numbers
    c = next(c for c in agg["candidates"] if c["id"] == "step1->step2")
    assert c["stuck_people"] == t["stuck_people"]


def test_without_a_denominator_or_an_anchor_headcounts_are_unavailable_and_say_why():
    agg = jn.aggregate(ROWS, SPEC)
    hc.apply(agg, denominator=None, stages=jn.stages_of(SPEC))
    assert agg["headcount"]["available"] is False and "No sizing figure on file" in agg["headcount"]["reason"]
    assert "people" not in agg["funnel"][0] and "stuck_people" not in agg["transitions"][0]


def test_a_known_headcount_for_a_step_is_held_fixed_and_the_steps_after_it_scale_from_it():
    spec = {"stages": [dict(STAGES[0]), {**STAGES[1], "people": "20,000", "people_source": "client channel data 2025"}, dict(STAGES[2]), dict(STAGES[3])], "seed": 1}
    stages = jn.stages_of(spec)
    assert stages[1]["people"] == 20000 and stages[1]["people_source"] == "client channel data 2025" and "people" not in stages[0]
    agg = jn.aggregate(ROWS, spec)
    hc.apply(agg, denominator=hc.denominator_for(spec, FRAME), stages=stages)
    f = agg["funnel"]
    assert f[0]["people"] == 47940 and f[0]["basis"] == "official_statistic"                 # before the anchor: the denominator
    assert f[1]["people"] == 20000 and f[1]["people_low"] == 20000 and f[1]["basis"] == "client_supplied"   # the anchor, exact
    # after it: scaled from the anchor by the panel's shares (5 of 8 reached step2, 3 of 8 reached step3)
    assert f[2]["people"] == round(20000 / (5 / 8) * (3 / 8)) and f[2]["basis"] == "client_anchored" and f[2]["anchor"] == "Assessed"
    # the transition into the anchored step is the difference of the two figures, with no interval
    t = agg["transitions"][0]
    assert t["through_people"] == 20000 and t["stuck_people"] == 47940 - 20000 and t["stuck_low"] == t["stuck_high"] == t["stuck_people"] and t["basis"] == "client_supplied"
    assert "held fixed at 20,000 at 'Assessed'" in agg["headcount"]["sentence"] and agg["headcount"]["anchors"][0]["step"] == "Assessed"
    # an anchor alone is enough — no denominator needed for the steps after it
    agg2 = jn.aggregate(ROWS, spec)
    hc.apply(agg2, denominator=None, stages=stages)
    assert agg2["headcount"]["available"] and agg2["funnel"][0]["people"] is None and agg2["funnel"][2]["people"] == round(20000 / (5 / 8) * (3 / 8))


def test_frame_weights_change_the_share_the_headcount_is_built_on():
    agg = jn.aggregate(ROWS, SPEC)
    stages = jn.stages_of(SPEC)
    weights = {f"a{k}": 1.0 for k in range(1, 9)}
    weights["a7"] = weights["a8"] = 3.0          # the two who finished stand for more people
    hc.apply(agg, denominator={"people": 10000, "basis": "official_statistic", "label": "x", "source": "s", "year": ""}, stages=stages, rows=ROWS, weights=weights)
    h = agg["headcount"]
    assert h["weighted"] and h["ess"] < 8
    last = agg["funnel"][3]
    assert last["share"] == 0.25 and last["share_weighted"] == round(6 / 12, 4) and last["people"] == 5000
    assert "weighted to the sampling frame" in h["sentence"]
    # equal weights: not weighted
    agg2 = jn.aggregate(ROWS, SPEC)
    hc.apply(agg2, denominator={"people": 10000, "basis": "official_statistic", "label": "x", "source": "s", "year": ""}, stages=stages, rows=ROWS, weights={k: 1.0 for k in weights})
    assert agg2["headcount"]["weighted"] is False and agg2["funnel"][3]["people"] == 2500


def test_the_validation_requires_a_source_for_any_typed_figure():
    inst = jn.INSTRUMENT
    assert inst.validate({**SPEC, "denominator": {"people": "50,000", "source": "client data"}}) == []
    assert "needs a source" in inst.validate({**SPEC, "denominator": {"people": "50,000"}})[0]
    assert "must be a count" in inst.validate({**SPEC, "denominator": {"people": "34%", "source": "x"}})[0]
    assert "needs a source line" in inst.validate({"stages": [{**STAGES[0], "people": 100}, STAGES[1], STAGES[2]], "seed": 1})[0]
    assert inst.validate({**SPEC, "denominator": {"people": ""}}) == []


def test_the_record_the_prompt_line_the_structure_and_the_csv_carry_the_people():
    agg = jn.aggregate(ROWS, SPEC)
    stages = jn.stages_of(SPEC)
    hc.apply(agg, denominator=hc.denominator_for({}, FRAME), stages=stages)
    p = SimpleNamespace(id="j1", instrument="journey", spec=SPEC, seed=1, schema_id="journey.v1", prompt_hash="h", model="m",
                        agent_count=8, answer_count=8, created_at=None, aggregates=agg)
    r = rec.record_from_probe(p)
    c = r["candidates"][0]
    assert c["stuck_people"] == 47940 - round(47940 * 0.75) and c["basis"] == "official_statistic" and r["headcount"]["available"]
    text, _ = rec.records_block([r])
    assert "≈11,985 people stuck (" in text and "headcounts: 47,940 people in scope" in text and "(≈47,940 people)" in text
    assert "headcount" in rec.FIGURE_RULES.lower()
    s = st.candidates_from_records([r])
    assert s["headcount"]["available"] and s["headcount"]["basis"] == "official_statistic" and s["items"][0]["stuck_people"] == 11985 and s["funnel"][0]["people"] == 47940
    from app.services.simulation import export
    row = export.records_rows([r])[0]
    assert row["top_candidate_people"] == 11985 and row["headcount_basis"] == "official_statistic"
    md = export.client_markdown(run={"title": "t", "question": "q", "population": {"n": 8}, "frame": {"level": "none"}, "evidence": {}, "generated_at": "now"},
                                report={"answer": "x", "structure": {"outcome": {"candidates": s, "caveats": []}}}, records=[r], agents={}, ledger={})
    assert "Headcounts: 47,940 people in scope" in md and "≈11,985 people stuck" in md and "no more real than the share" in md
    # no denominator: the prompt says so and the model is told to give no number of people
    agg2 = jn.aggregate(ROWS, SPEC)
    hc.apply(agg2, denominator=None, stages=stages)
    r2 = rec.record_from_probe(SimpleNamespace(**{**p.__dict__, "aggregates": agg2}))
    text2, _ = rec.records_block([r2])
    assert "headcounts: not available" in text2 and "people stuck" not in text2
