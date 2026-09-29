"""Movability (brief L7-03): how much of each gap a plausible lever can reach, counted from
who could reach each barrier — never asserted.

Run:  cd backend && pytest tests/movability_test.py -q
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

import pytest  # noqa: E402

from app.services.measurement import headcount as hc  # noqa: E402
from app.services.measurement import movability as mv  # noqa: E402
from app.services.measurement.instruments import journey as jn  # noqa: E402
from app.services.simulation import records as rec  # noqa: E402
from app.services.simulation import structure as st  # noqa: E402
from tests.headcount_test import FRAME  # noqa: E402
from tests.journey_test import ROWS, SPEC, _row  # noqa: E402

# Five stuck at step1 (3 GP access — system; 2 no bus — partner: a transport subsidy), one stuck at step2 (cost — partner),
# one at step3 (side effects — partner: nurse line), two who finished.
ROWS2 = [
    _row(1, "step1", "no", "cannot get a GP slot", "GP access", "more GP appointments", 90),
    _row(2, "step1", "unlikely", "8am phone scramble", "GP access", "more GP appointments", 70),
    _row(3, "step1", "no", "no appointments for weeks", "GP access", "more GP appointments", 80),
    _row(4, "step1", "no", "no bus to the surgery", "transport", "a bus fare or a lift", 60, dep="Q5 least deprived"),
    _row(5, "step1", "no", "cannot afford the taxi", "transport", "a bus fare or a lift", 65),
    _row(6, "step2", "no", "£9.90 an item", "prescription cost", "free scripts", 80, dep="Q5 least deprived"),
    _row(7, "step3", "no", "side effects in week 6", "side effects", "nurse call", 60, dep="Q5 least deprived", who="people I serve"),
    _row(8, "step4", "yes", dep="Q5 least deprived"),
    _row(9, "step4", "yes"),
    _row(10, "step2", "yes"),
]
CLASSES = {"GP access": ("system", "more GP appointments", "the ICB"), "transport": ("partner", "a bus fare or a lift to the surgery", "a charity or the manufacturer"),
           "prescription cost": ("system", "free prescriptions", "central government"), "side effects": ("partner", "nurse phone line in weeks 4-12", "a pharmacy chain")}


def _classed(agg):
    for t in agg["transitions"]:
        for b in t["barriers"]:
            r, lever, actor = CLASSES[b["theme"]]
            b.update({"reach": r, "lever": lever, "actor": actor, "reach_reason": "test"})
    return agg


def test_the_score_counts_each_stuck_twin_by_who_could_reach_its_barrier():
    agg = _classed(jn.aggregate(ROWS2, SPEC))
    t = agg["transitions"][0]           # 5 stuck: 3 system (GP access), 2 partner (transport)
    m = mv.score(t)
    assert m["scored"] and m["movable_count"] == 2 and m["movable_share"] == 0.4 and m["system_count"] == 3 and m["system_share"] == 0.6
    assert m["structural_count"] == 0 and m["unscored_count"] == 0
    assert m["levers"] == [{"theme": "transport", "lever": "a bus fare or a lift to the surgery", "actor": "a charity or the manufacturer", "count": 2}]
    # a stuck twin who named no barrier counts as no removal named (structural side)
    t2 = {**t, "stuck": 6}
    m2 = mv.score(t2)
    assert m2["structural_count"] == 1 and round(m2["movable_share"], 4) == round(2 / 6, 4)
    # nothing classed → not scored
    m3 = mv.score({"stuck": 3, "barriers": [{"theme": "x", "count": 3}]})
    assert m3["scored"] is False and m3["unscored_count"] == 3
    assert mv.score({"stuck": 0, "barriers": []})["scored"] is False


def test_movable_people_follow_the_headcount():
    agg = _classed(jn.aggregate(ROWS2, SPEC))
    hc.apply(agg, denominator={"people": 100000, "basis": "official_statistic", "label": "x", "source": "s", "year": ""}, stages=jn.stages_of(SPEC))
    t = agg["transitions"][0]
    m = mv.score(t)
    assert t["stuck_people"] == 50000 and m["movable_people"] == 20000 and m["movable_low"] < 20000 < m["movable_high"]
    assert "40% movable (2 of 5 stuck; ≈20,000 people)" in mv.sentence({**t, "movability": m}) and "60% needs the system" in mv.sentence({**t, "movability": m})
    assert "levers: a bus fare or a lift to the surgery (a charity or the manufacturer)" in mv.sentence({**t, "movability": m})
    assert mv.sentence({"movability": {"scored": False}}) == "movability not scored"


def test_candidates_are_ranked_by_the_movable_gap_first():
    agg = _classed(jn.aggregate(ROWS2, SPEC))
    assert [c["id"] for c in agg["candidates"]] == ["step1->step2", "step3->step4", "step2->step3"]   # by stuck, then gap, before scoring
    # make the big gap immovable: every barrier at step1 needs the system
    for b in agg["transitions"][0]["barriers"]:
        b["reach"] = "system"
    mv.apply(agg)
    ids = [c["id"] for c in agg["candidates"]]
    # step3->step4 has 1 movable (nurse line, partner) and outranks step1->step2 (5 stuck, 0 movable); step2->step3 has 0 (cost needs the system)
    assert ids == ["step3->step4", "step1->step2", "step2->step3"] and [c["rank"] for c in agg["candidates"]] == [1, 2, 3]
    assert agg["candidates"][0]["movability"]["movable_count"] == 1 and agg["candidates"][1]["movability"]["movable_count"] == 0 and agg["candidates"][1]["stuck"] == 5
    assert agg["movability"]["classified"] is True and agg["movability"]["unscored"] == 0
    # unscored everywhere: the ranking falls back to who is stuck
    agg2 = jn.aggregate(ROWS2, SPEC)
    mv.apply(agg2)
    assert [c["id"] for c in agg2["candidates"]] == ["step1->step2", "step3->step4", "step2->step3"] and agg2["movability"]["classified"] is False


@pytest.mark.asyncio
async def test_classify_asks_only_about_barriers_with_a_removal_and_never_guesses_the_rest(monkeypatch):
    seen = {}
    async def fake_analyze(schema, system, user, **kw):
        seen["user"] = user
        return {"items": [{"index": 1, "reach": "partner", "lever": "a lift", "actor": "a charity", "reason": "r"}, {"index": 2, "reach": "bogus"}, {"index": 9, "reach": "system"}]}
    monkeypatch.setattr(mv, "analyze", fake_analyze)
    barriers = [{"theme": "transport", "count": 2, "removals": [{"value": "a lift"}], "twins": [{"barrier": "no bus", "removal": "a lift"}], "step_label": "A → B"},
                {"theme": "GP access", "count": 3, "removals": [{"value": "more GPs"}], "twins": []},
                {"theme": "fate", "count": 1, "removals": [], "twins": []}]
    out = await mv.classify(barriers, session_id="s", question="Q")
    assert out[0] == {"reach": "partner", "lever": "a lift", "actor": "a charity", "reason": "r"}
    assert out[1]["reach"] == "unscored"                                   # a bad class is never guessed
    assert out[2]["reach"] == "none" and "nothing" in out[2]["reason"]      # no removal → not even asked
    assert "1. [A → B] transport — named by 2 · what would remove it: a lift · in their words: \"no bus\" → \"a lift\"" in seen["user"] and "fate" not in seen["user"]
    # every barrier without a removal: no call at all
    async def boom(*a, **k):
        raise AssertionError("should not be called")
    monkeypatch.setattr(mv, "analyze", boom)
    assert [x["reach"] for x in await mv.classify([{"theme": "fate", "removals": []}], session_id="s", question="Q")] == ["none"]


def test_the_record_the_prompt_the_structure_and_the_export_carry_movability():
    agg = _classed(jn.aggregate(ROWS2, SPEC))
    hc.apply(agg, denominator=hc.denominator_for({}, FRAME), stages=jn.stages_of(SPEC))
    mv.apply(agg)
    p = SimpleNamespace(id="j1", instrument="journey", spec=SPEC, seed=1, schema_id="journey.v1", prompt_hash="h", model="m",
                        agent_count=10, answer_count=10, created_at=None, aggregates=agg)
    r = rec.record_from_probe(p)
    c = r["candidates"][0]
    assert c["movability"]["movable_share"] == 0.4 and c["barriers"][0]["reach"] == "system" and c["barriers"][1]["lever"].startswith("a bus fare")
    text, _ = rec.records_block([r])
    assert "40% movable (2 of 5 stuck; ≈9,588 people), 60% needs the system, levers: a bus fare or a lift to the surgery (a charity or the manufacturer)" in text
    assert "MOVABILITY" in rec.FIGURE_RULES
    s = st.candidates_from_records([r])
    assert s["items"][0]["movability"]["movable_share"] == 0.4 and s["items"][0]["barriers"][1]["reach"] == "partner" and s["items"][1]["from"] == "Started"
    from app.services.simulation import export
    row = export.records_rows([r])[0]
    assert row["top_candidate_movable_share"] == 0.4 and row["top_candidate_movable_people"] == 9588
    md = export.client_markdown(run={"title": "t", "question": "q", "population": {"n": 10}, "frame": {"level": "none"}, "evidence": {}, "generated_at": "now"},
                                report={"answer": "x", "structure": {"outcome": {"candidates": s, "caveats": []}}}, records=[r], agents={}, ledger={})
    assert "movable 40% (≈9,588 people), needs the system 60%" in md and "ranked by the movable gap first" in md and "(2 twins; partner: a bus fare" in md
    # unscored: said plainly
    agg2 = jn.aggregate(ROWS2, SPEC)
    mv.apply(agg2)
    r2 = rec.record_from_probe(SimpleNamespace(**{**p.__dict__, "aggregates": agg2}))
    text2, _ = rec.records_block([r2])
    assert "movability not scored" in text2
