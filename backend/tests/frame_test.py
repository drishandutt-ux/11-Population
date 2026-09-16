"""The sampling frame (services/population/frame.py). Run:  cd backend && pytest tests/frame_test.py -q
No network. Categorisation, planned/achieved distributions, weights + ESS, the report, the ladder,
and the model-facing steps with `analyze` stubbed.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.population import frame  # noqa: E402

AGE = {"key": "age", "label": "Age", "attribute": "age", "kind": "demographic", "why": "w", "matchable": True, "proxy_attribute": "other"}
PLACE = {"key": "place", "label": "Place", "attribute": "region", "kind": "demographic", "why": "w", "matchable": True, "proxy_attribute": "other"}
PRICE = {"key": "price_sensitivity", "label": "Price sensitivity", "attribute": "attitude", "kind": "attitudinal", "why": "w", "matchable": False, "proxy_attribute": "income"}
GENDER = {"key": "gender", "label": "Gender", "attribute": "gender", "kind": "demographic", "why": "w", "matchable": True, "proxy_attribute": "other"}

T_AGE = {"status": "found", "categories": [{"label": "18-34", "share_pct": 30, "age_min": 18, "age_max": 34}, {"label": "35-64", "share_pct": 50, "age_min": 35, "age_max": 64}, {"label": "65+", "share_pct": 20, "age_min": 65, "age_max": 120}],
         "source": "ONS mid-year estimates", "year": "2023", "geography": "Blackpool", "proxy_attribute": "other", "note": "", "provenance": "official_statistic"}
T_PLACE = {"status": "found", "categories": [{"label": "Blackpool", "share_pct": 70}, {"label": "Oxford", "share_pct": 30}], "source": "ONS", "year": "2023", "geography": "England", "proxy_attribute": "other", "note": "", "provenance": "official_statistic"}
T_INCOME = {"status": "found", "categories": [{"label": "Low income", "share_pct": 40}, {"label": "Middle income", "share_pct": 40}, {"label": "High income", "share_pct": 20}], "source": "HBAI", "year": "2023", "geography": "UK", "proxy_attribute": "other", "note": "", "provenance": "official_statistic"}
T_GENDER = {"status": "found", "categories": [{"label": "Female", "share_pct": 51}, {"label": "Male", "share_pct": 49}], "source": "Census", "year": "2021", "geography": "England", "proxy_attribute": "other", "note": "", "provenance": "official_statistic"}


class A:
    def __init__(self, age=40, **demo):
        self.age = age
        self.demographics = demo


# ── categorisation ────────────────────────────────────────────────────────────

def test_category_of_age_gender_income_region():
    assert frame.category_of(AGE, T_AGE, age=22) == "18-34"
    assert frame.category_of(AGE, T_AGE, age=64) == "35-64"
    assert frame.category_of(AGE, T_AGE, age=90) == "65+"
    assert frame.category_of(AGE, {"status": "found", "categories": [{"label": "Under 25"}, {"label": "25 to 44"}, {"label": "45+"}]}, age=30) == "25 to 44"
    assert frame.category_of(GENDER, T_GENDER, value="female") == "Female" and frame.category_of(GENDER, T_GENDER, value="M") == "Male"
    inc = {"key": "income", "label": "Income", "attribute": "income", "kind": "demographic"}
    assert frame.category_of(inc, T_INCOME, value="low") == "Low income" and frame.category_of(inc, T_INCOME, value="affluent") == "High income"
    assert frame.category_of(PLACE, T_PLACE, value="Blackpool, Lancashire") == "Blackpool"
    assert frame.category_of(PLACE, T_PLACE, value="Preston") is None
    # a proxy dimension reads the proxy attribute
    proxy = {**T_INCOME, "status": "proxy", "proxy_attribute": "income"}
    assert frame.category_of(PRICE, proxy, value="middle") == "Middle income"


def test_planned_distribution_splits_segments_over_cells():
    segs = [
        {"count": 50, "decision": "accepted", "demographics": {"age_min": 30, "age_max": 39, "regions": ["Blackpool"], "gender_female_pct": 60}},
        {"count": 50, "decision": "proposed", "demographics": {"age_min": 65, "age_max": 74, "regions": ["Oxford", "Preston"], "gender_female_pct": 40}},
        {"count": 20, "decision": "rejected", "demographics": {"age_min": 18, "age_max": 20, "regions": ["Blackpool"]}},
    ]
    age = frame.planned_distribution(AGE, T_AGE, segs, 100)
    assert age == {"18-34": 25.0, "35-64": 25.0, "65+": 50.0}          # 30-39 straddles two bands evenly
    place = frame.planned_distribution(PLACE, T_PLACE, segs, 100)
    assert place == {"Blackpool": 50.0, "Oxford": 25.0}                  # Preston is not a target cell
    gender = frame.planned_distribution(GENDER, T_GENDER, segs, 100)
    assert gender == {"Female": 50.0, "Male": 50.0}


def test_achieved_distribution_counts_and_unplaced():
    agents = [A(22, region="Blackpool"), A(40, region="Oxford"), A(70, region="Nowhere")]
    counts, unplaced = frame.achieved_distribution(PLACE, T_PLACE, agents)
    assert counts == {"Blackpool": 1, "Oxford": 1} and unplaced == 1


# ── weights and the report ────────────────────────────────────────────────────

def _frame(**targets):
    return {"dimensions": [PLACE, AGE, GENDER], "targets": targets, "report": None, "geography": "England"}


def test_weights_move_toward_targets_and_ess_drops():
    fr = _frame(place=T_PLACE)
    agents = [A(30, region="Blackpool")] * 5 + [A(30, region="Oxford")] * 5      # 50/50 panel, 70/30 target
    w, ess = frame.weights_for(fr, agents)
    assert all(w[k] > 1 for k in range(5)) and all(w[k] < 1 for k in range(5, 10))
    assert abs(sum(w[:5]) / sum(w) - 0.7) < 0.02
    assert ess < 10
    w1, ess1 = frame.weights_for({"dimensions": [PLACE], "targets": {}}, agents)
    assert w1 == [1.0] * 10 and ess1 == 10


def test_report_levels_modes_and_thin_cells():
    fr = _frame(place=T_PLACE, age=T_AGE, gender=T_GENDER)
    segs = [{"count": 70, "decision": "accepted", "demographics": {"age_min": 35, "age_max": 64, "regions": ["Blackpool"], "gender_female_pct": 51}},
            {"count": 30, "decision": "accepted", "demographics": {"age_min": 18, "age_max": 34, "regions": ["Oxford"], "gender_female_pct": 51}}]
    rep = frame.build_report(fr, segs, 100)
    assert rep["stage"] == "planned" and rep["matched_exactly"] == ["place", "age", "gender"] and rep["weighted_only"] == []
    age_row = next(d for d in rep["dimensions"] if d["key"] == "age")
    assert age_row["max_deviation_planned"] == 20.0     # no 65+ planned against a 20% target
    assert rep["level"] == "poor"

    agents = [A(40, region="Blackpool", gender="female")] * 7 + [A(25, region="Oxford", gender="male")] * 3
    rep2 = frame.build_report(fr, segs, 10, agents)
    assert rep2["stage"] == "achieved" and rep2["n"] == 10 and rep2["ess"] is not None
    assert any("65+" in c for c in rep2["thin_cells"])
    line = frame.summary_line(rep2)
    assert line.startswith("Frame match") and "thin cell" in line
    assert frame.summary_line(None).startswith("No sampling frame")


def test_four_dimensions_split_exact_and_weighted():
    inc = {"key": "income", "label": "Income", "attribute": "income", "kind": "demographic", "why": "", "matchable": True, "proxy_attribute": "other"}
    fr = {"dimensions": [PLACE, AGE, GENDER, inc], "targets": {"place": T_PLACE, "age": T_AGE, "gender": T_GENDER, "income": T_INCOME}}
    rep = frame.build_report(fr, [], 10)
    assert rep["matched_exactly"] == ["place", "age", "gender"] and rep["weighted_only"] == ["income"]


# ── the ladder ────────────────────────────────────────────────────────────────

def test_gaps_proxy_upload_skip():
    fr = _frame(place=T_PLACE, age={"status": "missing", "categories": []})
    assert [d["key"] for d in frame.gaps(fr)] == ["age", "gender"]
    up = frame.uploaded_target([{"label": "A", "share_pct": 30}, {"label": "B", "share_pct": 60}], "client panel", "Blackpool")
    assert up["status"] == "uploaded" and up["provenance"] == "client_data"
    assert [c["share_pct"] for c in up["categories"]] == [33.3, 66.7]    # rescaled to 100
    with pytest.raises(ValueError):
        frame.uploaded_target([{"label": "A", "share_pct": 100}], "", "")
    px = frame.proxy_target(fr, "place")
    assert px["status"] == "proxy" and px["proxy_attribute"] == "region" and "via Place" in px["note"]
    with pytest.raises(ValueError):
        frame.proxy_target(fr, "age")
    assert frame.skipped_target()["status"] == "skipped"
    assert frame.target_counts(fr, 50) == {"place": {"Blackpool": 35.0, "Oxford": 15.0}}


def test_weighted_level_and_ess():
    assert frame.weighted_level("share", [1.0, 0.0, 1.0, None], [3.0, 1.0, 1.0, 9.0]) == 0.8
    assert frame.weighted_level("mean", [], []) is None
    assert frame.ess_of([1.0, 1.0, 1.0, 1.0]) == 4.0 and frame.ess_of([4.0, 0.0, 0.0, 0.0]) == 1.0


# ── model-facing steps, stubbed ───────────────────────────────────────────────

def test_pick_dimensions_and_derive_targets(monkeypatch):
    async def fake_analyze(schema, system, user, **kw):
        props = schema.get("properties", {})
        if "dimensions" in props:
            return {"dimensions": [{"key": "Place!", "label": "Place", "attribute": "region", "kind": "demographic", "why": "w", "matchable": True, "proxy_attribute": "other"},
                                   {"key": "place", "label": "dup", "attribute": "region", "kind": "demographic", "why": "", "matchable": True, "proxy_attribute": "other"},
                                   {"key": "price", "label": "Price sensitivity", "attribute": "attitude", "kind": "attitudinal", "why": "w", "matchable": False, "proxy_attribute": "income"}]}
        if "status" in props:
            if "Price sensitivity" in user:
                return {"status": "proxy", "categories": [{"label": "Low", "share_pct": 40}, {"label": "High", "share_pct": 60}], "source": "HBAI", "year": "2023", "geography": "UK", "proxy_attribute": "income", "note": "income stands in"}
            return {"status": "found", "categories": [{"label": "Blackpool", "share_pct": 70}, {"label": "Oxford", "share_pct": 30}], "source": "ONS", "year": "2023", "geography": "England", "proxy_attribute": "other", "note": ""}
        return {}
    monkeypatch.setattr(frame, "analyze", fake_analyze)
    dims = asyncio.run(frame.pick_dimensions("s", "q", {"geography": "England"}, "dials"))
    assert [d["key"] for d in dims] == ["place", "price"]                 # slugged and de-duplicated

    class E:
        structured = {"facts": [{"statistic": "population", "value": "70%", "group": "adults", "geography": "Blackpool", "year": "2023"}], "source_label": "ONS"}
        author = "ONS"; excerpt = "Blackpool 70%, Oxford 30%"; source_ref = "u"; title = "t"
    targets = asyncio.run(frame.derive_targets("s", dims, "England", [E()]))
    assert targets["place"]["status"] == "found" and targets["place"]["provenance"] == "official_statistic"
    assert targets["price"]["status"] == "proxy" and targets["price"]["proxy_attribute"] == "income"
    empty = asyncio.run(frame.derive_targets("s", dims, "England", []))
    assert all(t["status"] == "missing" for t in empty.values())


def test_estimate_refuses_attitudinal_and_labels_demographic(monkeypatch):
    async def fake_analyze(schema, system, user, **kw):
        return {"allowed": True, "refusal_reason": "", "categories": [{"label": "18-34", "share_pct": 30, "age_min": 18, "age_max": 34}, {"label": "35+", "share_pct": 70, "age_min": 35, "age_max": 120}], "reasoning": "census pattern", "confidence": 55}
    monkeypatch.setattr(frame, "analyze", fake_analyze)
    est = asyncio.run(frame.estimate_target("s", AGE, "Blackpool"))
    assert est["status"] == "estimated" and est["provenance"] == "model_inference" and est["confidence"] == 55
    refused = asyncio.run(frame.estimate_target("s", PRICE, "Blackpool"))
    assert refused["status"] == "missing" and "declined" in refused["note"]


# ── the frame drives the search ───────────────────────────────────────────────

def test_search_targets_lead_with_dimensions_then_sizing(monkeypatch):
    async def fake_analyze(schema, system, user, **kw):
        assert "FRAME DIMENSIONS" in user and "PUBLISHERS TICKED" in user
        return {"targets": [
            {"key": "age", "fact": "population by age, Blackpool mid-2023", "queries": [{"query": "population estimates by single year of age Blackpool", "sources": ["ons", "bogus"]}]},
            {"key": "tam", "fact": "population of Blackpool", "queries": [{"query": "Blackpool mid-year population estimate", "sources": ["nomis"]}]},
            {"key": "som", "fact": "GLP-1 prescribing Blackpool", "queries": [{"query": "GLP-1 items prescribed Blackpool", "sources": []}]},
        ]}
    monkeypatch.setattr(frame, "analyze", fake_analyze)
    out = asyncio.run(frame.search_targets("s", [PLACE, AGE, PRICE], "Blackpool", "oral GLP-1", ["ons", "nomis"], "catalogue"))
    keys = [t["frame_key"] for t in out]
    assert keys == ["place", "age", "tam", "sam", "som"]                 # place via fallback, price (attitudinal) not searched
    age = next(t for t in out if t["frame_key"] == "age")
    assert age["dimension"] == "age" and age["priority"] == 1 and age["queries"][0]["sources"] == ["ons"]   # unknown key dropped
    som = next(t for t in out if t["frame_key"] == "som")
    assert som["dimension"] == "size" and som["queries"][0]["sources"] == ["ons", "nomis"]              # empty → all ticked
    place = next(t for t in out if t["frame_key"] == "place")
    assert "population estimates local authority Blackpool" in place["queries"][0]["query"]


def test_search_targets_fall_back_when_the_planner_fails(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("no model")
    monkeypatch.setattr(frame, "analyze", boom)
    out = asyncio.run(frame.search_targets("s", [AGE], "Oxford", "topic", ["ons"], ""))
    assert [t["frame_key"] for t in out] == ["age", "tam", "sam", "som"] and all(t["queries"] for t in out)


def test_extract_sizing_reads_only_what_is_stated(monkeypatch):
    async def fake_analyze(schema, system, user, **kw):
        return {"tam": {"value": "141,100", "label": "Blackpool residents", "source": "ONS MYE", "year": "2023"}, "sam": {"value": "", "label": "", "source": "", "year": ""},
                "som": {"value": "3,200", "label": "patients prescribed", "source": "OpenPrescribing", "year": "2026"}, "note": "no prevalence figure on file"}
    monkeypatch.setattr(frame, "analyze", fake_analyze)

    class E:
        structured = {"facts": [{"statistic": "population", "value": "141,100", "group": "residents", "geography": "Blackpool", "year": "2023"}], "source_label": "ONS"}
        author = "ONS"; excerpt = ""; source_ref = ""; title = ""
    sz = asyncio.run(frame.extract_sizing("s", "Blackpool", "GLP-1", [E()]))
    assert sz["tam"]["value"] == "141,100" and sz["sam"] == {} and sz["som"]["source"] == "OpenPrescribing"
    assert asyncio.run(frame.extract_sizing("s", "Blackpool", "GLP-1", []))["tam"] == {}
