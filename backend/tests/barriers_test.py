"""Barriers (brief L6-05): what stands in the way of an outcome, ranked and traceable.

Run:  cd backend && pytest tests/barriers_test.py -q
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.measurement.instruments import barriers as bar  # noqa: E402
from app.services.simulation import records as rec  # noqa: E402
from app.services.simulation import structure as st  # noqa: E402


def _row(k, blocked, barrier, theme, removal, weight, dep="Q1 most deprived"):
    return {"agent_id": f"a{k}", "agent": {"name": f"N{k}", "role": "r"}, "segments": {"stance": "direct", "deprivation": dep},
            "answer": {"reasoning": "why", "blocked": blocked, "barrier": barrier, "barrier__theme": theme, "removal": removal, "removal__theme": removal, "weight": weight}}


ROWS = [
    _row(1, "yes", "£200 a month", "cost", "NHS pays", 90),
    _row(2, "yes", "cannot afford it", "cost", "NHS pays", 80),
    _row(3, "partly", "monthly GP reviews", "GP capacity", "nurse-led reviews", 60, dep="Q5 least deprived"),
    _row(4, "yes", "no appointments", "GP capacity", "nurse-led reviews", 70, dep="Q5 least deprived"),
    _row(5, "yes", "pharmacy shortages", "supply", "stock", 50),
    _row(6, "no", "", "", "", 0, dep="Q5 least deprived"),
    _row(7, "no", "", "", "", 0),
]


def test_barriers_are_ranked_by_who_cited_them_then_weight_with_their_twins_and_removals():
    ranked = bar.rank_barriers(ROWS)
    assert [b["theme"] for b in ranked] == ["cost", "GP capacity", "supply"]
    cost = ranked[0]
    assert cost["count"] == 2 and round(cost["share"], 3) == round(2 / 7, 3) and cost["weight_mean"] == 85.0 and cost["agent_ids"] == ["a1", "a2"]
    assert cost["twins"][0]["barrier"] == "£200 a month" and cost["removals"][0]["value"] == "NHS pays" and cost["evidence"] == []
    # ties on count break on weight
    assert ranked[1]["weight_mean"] == 65.0


def test_the_aggregate_carries_the_headline_the_ranking_and_a_sentence():
    agg = bar.aggregate(ROWS, {"seed": 1, "outcome": "You take it up"})
    assert agg["n"] == 7 and agg["headline"]["successes"] == 5 and agg["headline"]["metric"] == "blocked_share"
    assert agg["barriers"][0]["theme"] == "cost" and agg["barriers_coded"] is True and agg["outcome"] == "You take it up"
    assert agg["sentence"].startswith("71% see something in the way") and "\"cost\" (2 twins, weight 85/100)" in agg["sentence"]
    assert "deprivation" in agg["segments"] and agg["blocked"][0]["value"] == "yes"
    assert bar.aggregate([], {})["n"] == 0


def test_a_barriers_probe_becomes_a_record_with_its_ranked_list_and_the_prompt_line():
    agg = bar.aggregate(ROWS, {"seed": 1, "outcome": "You take it up"})
    p = SimpleNamespace(id="b1", instrument="barriers", spec={"outcome": "You take it up", "stimulus": "You take it up"}, seed=1, schema_id="barriers.v1",
                        prompt_hash="h", model="m", agent_count=7, answer_count=7, created_at=None, aggregates=agg)
    r = rec.record_from_probe(p)
    assert r["label"] == "What's in the way of: You take it up" and r["outcome"] == "You take it up"
    assert [b["theme"] for b in r["barriers"]] == ["cost", "GP capacity", "supply"] and r["barriers"][0]["agent_ids"] == ["a1", "a2"]
    text, _ = rec.records_block([r])
    assert "barriers ranked: 1. cost (2 twins, weight 85/100); 2. GP capacity (2 twins, weight 65/100); 3. supply (1 twins, weight 50/100)" in text
    assert "only source for what stands in the way" in rec.FIGURE_RULES
    # a non-barriers record carries none
    v = SimpleNamespace(id="v1", instrument="verdict", spec={"question": "Q"}, seed=1, schema_id="v", prompt_hash="h", model="m", agent_count=3, answer_count=3, created_at=None,
                        aggregates={"n": 3, "headline": {"metric": "for_share", "label": "In favour", "share": 0.6, "low": 0.2, "high": 0.9, "n": 3, "successes": 2}, "sentence": "s", "segments": {}})
    assert rec.record_from_probe(v)["barriers"] == []


def test_the_report_structure_picks_the_newest_barriers_record():
    agg = bar.aggregate(ROWS, {"seed": 1, "outcome": "You take it up"})
    p = SimpleNamespace(id="b1", instrument="barriers", spec={"outcome": "You take it up"}, seed=1, schema_id="barriers.v1", prompt_hash="h", model="m",
                        agent_count=7, answer_count=7, created_at=None, aggregates=agg)
    r = rec.record_from_probe(p)
    b = st.barriers_from_records([{"id": "x", "barriers": []}, r])
    assert b["record_id"] == "b1" and b["outcome"] == "You take it up" and b["n"] == 7
    assert [i["theme"] for i in b["items"]] == ["cost", "GP capacity", "supply"] and b["items"][0]["removals"] == ["NHS pays"]
    assert st.barriers_from_records([{"id": "x", "barriers": []}]) is None
    s = st.build_structure(session_query="Q", records=[r], headline=None, positions=[], evidence=[], frame={"level": "none"}, cited_record_ids=[], claimed_band=None)
    assert s["outcome"]["barriers"]["record_id"] == "b1"


def test_the_instrument_is_declared_for_the_picker_and_the_ab_test():
    from app.services.measurement import instruments
    instruments._load()
    inst = instruments.get("barriers")
    assert inst and not inst.hidden and inst.page == "barriers" and inst.stimulus_key == "outcome"
    assert [m.key for m in inst.metrics] == ["blocked", "weight"] and inst.metrics[0].primary
    assert inst.metrics[0].value({"blocked": "partly"}) == 1.0 and inst.metrics[0].value({"blocked": "no"}) == 0.0
    assert inst.inputs[0].default_from == "session_query" and inst.decision_key == "blocked" and inst.driver_key == "barrier__theme"
