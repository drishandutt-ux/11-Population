"""Commitment records (brief L7-08): the modelled baseline frozen as a copy when a candidate outcome
is chosen, observed results entered later against it, the comparison counted, the report bound.

Run:  cd backend && pytest tests/commitments_test.py -q
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.measurement import commitments as cm  # noqa: E402
from app.services.measurement.instruments import journey as jn  # noqa: E402
from app.services.simulation import export as ex  # noqa: E402
from app.services.simulation import records as rec  # noqa: E402
from app.services.simulation import structure as st  # noqa: E402
from tests.journey_test import ROWS, SPEC  # noqa: E402

RUN = {"session_id": "s1", "question": "Will people use the caddy?", "title": "Caddies", "generated_at": "2026-09-29T10:00:00Z",
       "population": {"n": 40, "build_id": "build-1234", "mode": "fast"},
       "frame": {"level": "matched", "matched_exactly": ["age", "deprivation"], "weighted_only": ["tenure"], "estimated": [], "ess": 36.2, "thin_cells": [], "geography": "Manchester", "sizing": {"sam": 590000}},
       "evidence": {"web": 12, "personal": 3}, "scoping_snapshot": "snap-1",
       "calibration_rules": [{"id": "r1", "lever": "free liners", "status": "reviewed", "reviewed_by": "MH", "basis_class": "assumption", "deltas": {"friction.money_pain": -3}, "applies_to": {}}]}
LEDGER = {"items": [{"id": "e1", "title": "WRAP food waste report", "source_ref": "https://x", "provenance_class": "grey_literature", "trust_tier": "high", "published_at": "2025", "on_topic": True}],
          "facts": [{"id": "e1#0", "value": "26%", "statistic": "households using a caddy", "group": "", "geography": "Manchester", "year": "2025", "source": "WRAP", "provenance_class": "grey_literature"}]}


def _candidate():
    agg = jn.aggregate(ROWS, SPEC)
    raw = agg["candidates"][0]
    return agg, raw, rec.candidate_summary(raw, "p1")


def _commitment(observed=None, target=None, status="open"):
    agg, raw, cand = _candidate()
    journey = {"probe_id": "p1", "stages": agg["stages"], "funnel": agg["funnel"], "headcount": {"available": False, "reason": "no sizing figure"}, "n": 11, "seed": 1, "model": "m", "prompt_hash": "abc", "created_at": "2026-09-29T09:00:00"}
    related = [{"id": "e9", "kind": "lever", "label": "Lever run: free liners", "estimate": {"value": 0.1}, "sentence": "…", "caveats": [], "lever": {"rule": {"lever": "free liners"}}, "provenance": {}}]
    base = cm.build_baseline(run=RUN, candidate=cand, journey=journey, related=related, ledger=LEDGER, statement=ex.statement(RUN), weights={"n": 40, "weighted": True, "ess": 36.2})
    c = {"id": "c1", "session_id": "s1", "journey_probe_id": "p1", "candidate_id": raw["id"], "label": f"{raw['from']['label']} → {raw['to']['label']}",
         "committed_by": "Drishan", "committed_at": "2026-09-29T10:05:00", "target": cm.clean_target(target), "status": status, "superseded_by": None,
         "closed_by": "", "closed_at": None, "close_note": "", "baseline": base, "observed": observed or [], "created_at": "2026-09-29T10:05:00"}
    c["comparison"] = cm.compare(c["baseline"], c["target"], c["observed"])
    c["sentence"] = cm.sentence(c)
    return c, cand


def test_the_baseline_is_a_copy_of_everything_the_forecast_rested_on():
    c, cand = _commitment()
    b = c["baseline"]
    assert b["candidate"]["conversion"] == cand["conversion"] and b["candidate"]["barriers"] and b["candidate"]["confidence"]
    assert b["population"]["build_id"] == "build-1234" and b["population"]["weights"]["ess"] == 36.2
    assert b["frame"]["level"] == "matched" and b["frame"]["sizing"] == {"sam": 590000}
    assert b["evidence"]["counts"] == {"web": 12, "personal": 3} and b["evidence"]["items"][0]["provenance_class"] == "grey_literature" and b["evidence"]["facts"][0]["value"] == "26%"
    assert b["calibration_rules"][0]["lever"] == "free liners" and b["calibration_rules"][0]["status"] == "reviewed"
    assert b["related"][0]["kind"] == "lever" and b["scoping_snapshot"] == "snap-1"
    assert b["journey"]["prompt_hash"] == "abc" and b["journey"]["stages"][0]["label"] == "At risk"
    assert "SYNTHETIC POPULATION STATEMENT" in b["statement"] and b["frozen_at"].endswith("Z")
    # a copy: mutating the source afterwards does not reach the baseline
    cand["conversion"] = 0.99
    assert b["candidate"]["conversion"] != 0.99


def test_targets_and_observations_are_cleaned_and_a_source_and_date_are_required():
    assert cm.clean_target({"value": "60", "horizon": " March 2027 "}) == {"value": 0.6, "horizon": "March 2027"}
    assert cm.clean_target({"value": 0.45}) == {"value": 0.45} and cm.clean_target({"value": "x", "note": ""}) == {} and cm.clean_target(None) == {}
    ok, err = cm.clean_observed({"value": 51, "source": "ICB audit", "date": "2027-03-01", "low": 48, "high": 54, "note": "Q4"}, entered_by="MH")
    assert err is None and ok["value"] == 0.51 and ok["low"] == 0.48 and ok["high"] == 0.54 and ok["entered_by"] == "MH" and ok["entered_at"].endswith("Z")
    assert cm.clean_observed({"value": 51, "date": "2027-03-01"})[1].startswith("Say where")
    assert cm.clean_observed({"value": 51, "source": "x"})[1].startswith("Say when")
    assert cm.clean_observed({"value": "n/a", "source": "x", "date": "y"})[1].startswith("The observed value is required")
    assert cm.clean_observed({"value": 150, "source": "x", "date": "y"})[1].startswith("The observed value must be")


def test_the_comparison_is_counted_against_the_frozen_interval_and_the_target():
    c, cand = _commitment()
    assert c["comparison"] is None and c["sentence"].endswith("No observed result yet.")
    inside = (float(cand["low"]) + float(cand["high"])) / 2
    c2, _ = _commitment(observed=[{"value": round(inside, 4), "source": "ICB audit", "date": "2027-03-01", "entered_by": "MH", "entered_at": "x", "note": ""}], target={"value": 0.9})
    cp = c2["comparison"]
    assert cp["inside_interval"] is True and cp["target_met"] is False and cp["observations"] == 1
    assert abs(cp["delta"] - (inside - float(cand["conversion"]))) < 1e-6
    assert "inside the modelled interval" in c2["sentence"] and "target not met" in c2["sentence"] and "target 90%" in c2["sentence"]
    # the latest observation by date is the one compared; an observed figure above the interval is outside it
    c3, _ = _commitment(observed=[{"value": round(inside, 4), "source": "a", "date": "2027-01-01", "entered_by": "", "entered_at": "x", "note": ""},
                                  {"value": min(1.0, float(cand["high"]) + 0.2), "source": "ICB audit", "date": "2027-06-01", "entered_by": "", "entered_at": "y", "note": ""}], target={"value": 0.1})
    cp3 = c3["comparison"]
    assert cp3["observations"] == 2 and cp3["observed_date"] == "2027-06-01" and cp3["inside_interval"] is False and cp3["target_met"] is True and cp3["direction"] == "above"
    assert "outside the modelled interval" in c3["sentence"] and "target met" in c3["sentence"]
    # status travels into the sentence
    c4, _ = _commitment(status="superseded")
    assert c4["sentence"].endswith("Superseded by a later commitment.")


def test_a_commitment_becomes_a_record_and_the_report_is_bound_to_the_frozen_forecast():
    c, cand = _commitment(observed=[{"value": 0.5, "source": "ICB audit", "date": "2027-03-01", "entered_by": "MH", "entered_at": "x", "note": ""}], target={"value": 0.6, "horizon": "March 2027"})
    r = rec.record_from_commitment(c)
    assert r["kind"] == "commitment" and r["label"].startswith("Committed: ") and r["estimate"]["format"] == "share" and r["estimate"]["value"] == cand["conversion"]
    assert r["commitment"]["build_id"] == "build-1234" and r["commitment"]["evidence_items"] == 1 and r["commitment"]["rules"] == 1 and r["commitment"]["related"][0]["kind"] == "lever"
    assert r["commitment"]["comparison"]["observed"] == 0.5 and r["provenance"]["design"] == "frozen"
    assert any("frozen copy" in x for x in r["caveats"]) and any("entered by hand" in x for x in r["caveats"])
    text, handles = rec.records_block([r])
    assert "COMMITTED outcome (frozen 20" in text and "population build build-1234, 40 twins, frame matched" in text and "target 60% by March 2027" in text
    assert "OBSERVED 50% on 2027-03-01 (ICB audit)" in text and "the frozen forecast is the only figure that may be quoted" in text and handles["r1"] == "c1"
    assert "A COMMITTED OUTCOME" in rec.FIGURE_RULES and "never from the live journey figure" in rec.FIGURE_RULES
    # no observation: the block says so
    c0, _ = _commitment()
    assert "no observed result yet" in rec.records_block([rec.record_from_commitment(c0)])[0]
    # an empty baseline is no record
    assert rec.record_from_commitment({"id": "x", "baseline": {}}) is None


def test_the_report_structure_and_the_client_document_carry_the_committed_outcomes():
    c, cand = _commitment(observed=[{"value": 0.5, "source": "ICB audit", "date": "2027-03-01", "entered_by": "MH", "entered_at": "x", "note": ""}], target={"value": 0.6})
    r = rec.record_from_commitment(c)
    s = st.build_structure(session_query="Q?", records=[r], headline=None, positions=[], evidence=[], frame={"level": "none"}, cited_record_ids=[], claimed_band=None)
    items = s["outcome"]["commitments"]
    assert items and items[0]["record_id"] == "c1" and items[0]["from"] == cand["from"]["label"] and items[0]["comparison"]["observed"] == 0.5 and items[0]["observations"] == 1
    empty = st.build_structure(session_query="Q?", records=[], headline=None, positions=[], evidence=[], frame={"level": "none"}, cited_record_ids=[], claimed_band=None)
    assert empty["outcome"]["commitments"] is None
    md = ex.client_markdown(run=RUN, report={"answer": "", "structure": s}, records=[r], agents={}, ledger={"facts": [], "items": []})
    assert "## Committed outcomes — the frozen forecasts" in md and "committed by Drishan on 2026-09-29" in md
    assert "**observed 50%** on 2027-03-01 (ICB audit)" in md and "population build build-1234" in md and "counted, not judged" in md
