"""Message testing against the panel (brief L7-06): framings shown to the twins stuck at a step,
the shift counted by cohort, backfire as prominent as a win, labelled a reaction not a forecast.

Run:  cd backend && pytest tests/messaging_test.py -q
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.measurement import messaging as mg  # noqa: E402
from app.services.measurement import stats  # noqa: E402
from app.services.measurement.instruments import journey as jn  # noqa: E402
from app.services.simulation import records as rec  # noqa: E402
from tests.journey_test import SPEC  # noqa: E402
from tests.targeting_test import _arm, _base, _map  # noqa: E402

MSGS = mg.clean_messages([{"label": "Cost", "text": "Liners are free at the library."}, {"text": "Your neighbours already use theirs every week — join them."}])


def test_messages_are_cleaned_keyed_and_capped():
    assert [m["key"] for m in MSGS] == ["m1", "m2"] and MSGS[0]["label"] == "Cost"
    assert MSGS[1]["label"].startswith("Your neighbours") and MSGS[1]["label"].endswith("…")
    # blanks, duplicates and the cap
    many = mg.clean_messages([{"text": ""}, "same", "SAME", {"text": "x"}] + [{"text": f"m{k}"} for k in range(10)])
    assert [m["text"] for m in many][:3] == ["same", "x", "m0"] and len(many) == mg.MAX_MESSAGES
    # the twin reads it as a thing seen, not a change made
    block = mg.message_block(MSGS[0])
    assert "A MESSAGE YOU HAVE JUST SEEN" in block and "[Cost] Liners are free" in block and "no more persuasive" in block


def test_weighted_paired_lift_counts_each_twin_at_its_weight():
    pairs = [(0, 1), (0, 1), (0, 0), (1, 1)]
    plain = stats.paired_lift(pairs, seed=1)
    w = stats.weighted_paired_lift(pairs, [1, 1, 1, 1], seed=1)
    assert abs(w["mean"] - plain["mean"]) < 1e-9 and w["ess"] == 4.0
    heavy = stats.weighted_paired_lift(pairs, [0.1, 0.1, 5, 5], seed=1)   # the two who did not move carry the weight
    assert heavy["mean"] < plain["mean"] and heavy["ess"] < 4
    assert stats.weighted_paired_lift([], [], seed=1)["n"] == 0


def test_messages_are_ranked_winners_first_then_indistinguishable_then_harmful():
    base = _base()
    c_agg = jn.aggregate(base, SPEC)
    win = _arm(base, {"a5": "yes", "a6": "yes", "a7": "yes", "a10": "yes", "a11": "yes"})   # every stuck twin moves through
    flat = _arm(base, {"a10": "yes"})                                                        # one mover: not distinguishable
    harm = _arm(base, {"a8": "no", "a9": "no"})                                              # the two who were through fall back
    arms = {"m1": (jn.aggregate(flat, SPEC), _map(flat)), "m2": (jn.aggregate(win, SPEC), _map(win)), "m3": (jn.aggregate(harm, SPEC), _map(harm))}
    msgs = mg.clean_messages(["one mover", "everyone moves", "puts them off"])
    t = mg.rank(control_agg=c_agg, control_rows=_map(base), arms=arms, candidate_id="step3->step4", messages=msgs, seed=1)
    assert t["available"] and t["n"] == 7 and not t["weighted"]
    order = [r["key"] for r in t["messages"]]
    assert order == ["m2", "m1", "m3"]
    top, mid, bottom = t["messages"]
    assert top["direction"] == "helps" and top["significant"] and abs(top["lift"] - 5 / 7) < 1e-3 and top["rank"] == 1
    assert mid["direction"] == "helps" and not mid["significant"]
    assert bottom["direction"] == "hurts" and bottom["lift"] < 0 and bottom["movement"]["down"] == 2
    assert bottom["hurts"] == bool(bottom["significant"])
    # the text travels with the row; the sentence names the order and the label
    assert top["text"] == "everyone moves" and top["label"] == "everyone moves"
    assert t["sentence"].startswith("Messages ranked by the shift in conversion at 'Started' → 'Still on it at 6 months' (7 twins at risk")
    assert "1. 'everyone moves': +71.4 points" in t["sentence"] and "modelled reaction to a framing, not a forecast of uptake" in t["sentence"]
    if bottom["hurts"]:
        assert "BACKFIRE: 'puts them off' lowers conversion overall" in t["sentence"] and t["backfires"][0]["key"] == "m3"


def test_a_band_the_message_lowers_while_helping_overall_is_a_backfire():
    base = _base()
    c_agg = jn.aggregate(base, SPEC)
    # Q1's three stuck twins all move through; Q5's two who were through both fall back → helps overall, hurts Q5
    mixed = _arm(base, {"a5": "yes", "a6": "yes", "a7": "yes", "a8": "no", "a9": "no"})
    t = mg.rank(control_agg=c_agg, control_rows=_map(base), arms={"m1": (jn.aggregate(mixed, SPEC), _map(mixed))}, candidate_id="step3->step4",
                messages=mg.clean_messages(["split"]), seed=1)
    r = t["messages"][0]
    assert r["direction"] == "helps"
    q5 = next(b for b in r["bands"] if b["value"] == "Q5 least deprived")
    assert q5["lift"] < 0
    if q5["high"] < 0:
        assert any(b["value"] == "Q5 least deprived" for b in r["backfire"]) and "BACKFIRE" in t["sentence"] and "Q5 least deprived" in t["sentence"]
        assert t["backfires"] and t["backfires"][0]["bands"][0]["value"] == "Q5 least deprived"
    # the weighted shift appears once anyone carries a weight other than 1
    tw = mg.rank(control_agg=c_agg, control_rows=_map(base), arms={"m1": (jn.aggregate(mixed, SPEC), _map(mixed))}, candidate_id="step3->step4",
                 messages=mg.clean_messages(["split"]), weights={"a5": 3.0, "a8": 0.2}, seed=1)
    assert tw["weighted"] and tw["messages"][0]["weighted"]["lift"] > r["lift"] and "weighted" in tw["sentence"]


def test_a_message_run_becomes_a_record_and_the_report_model_is_bound_to_it():
    base = _base()
    c_agg = jn.aggregate(base, SPEC)
    win = _arm(base, {"a5": "yes", "a6": "yes", "a7": "yes", "a10": "yes", "a11": "yes"})
    t = mg.rank(control_agg=c_agg, control_rows=_map(base), arms={"m1": (jn.aggregate(win, SPEC), _map(win))}, candidate_id="step3->step4",
                messages=mg.clean_messages([{"label": "Cost", "text": "Liners are free."}]), seed=1)
    t["journey_probe_id"] = "p1"
    e = SimpleNamespace(id="e1", name="Messages tested at Started → Still on it", seed=1, model="m", created_at=None, results={"messaging": t, "comparisons": []})
    r = rec.record_from_experiment(e)
    assert r["kind"] == "messaging" and r["label"].startswith("Messages tested at") and r["estimate"]["format"] == "lift"
    assert "not a forecast" in r["estimate"]["label"]
    assert r["messaging"]["messages"][0]["key"] == "m1" and r["messaging"]["messages"][0]["text"] == "Liners are free." and r["messaging"]["n"] == 7
    assert any("modelled reaction to a framing" in c for c in r["caveats"])
    text, handles = rec.records_block([r])
    assert "messages tested (shift in conversion at the step, 7 twins at risk)" in text and "1. 'Cost' +71.4" in text
    assert "NOT a forecast of uptake" in text and "no backfire found" in text and handles["r1"] == "e1"
    assert "WHICH MESSAGE WORKS" in rec.FIGURE_RULES and "not a forecast of uptake" in rec.FIGURE_RULES
    # not yet counted: no record
    assert rec.record_from_experiment(SimpleNamespace(id="e2", results={"messaging": {"available": False}}, seed=1, model="m", name="", created_at=None)) is None
