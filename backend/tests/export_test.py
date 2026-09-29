"""Export, client document and delta view (brief L6-06) with the non-removable synthetic-population
statement (brief L6-07).

Run:  cd backend && pytest tests/export_test.py -q
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.simulation import delta as dl  # noqa: E402
from app.services.simulation import export as ex  # noqa: E402

RUN = {"question": "Should GPs prescribe?", "title": "GP", "generated_at": "2026-09-29T10:00:00Z", "population": {"n": 49},
       "frame": {"level": "fair", "matched_exactly": ["place", "age", "deprivation"], "weighted_only": ["income"], "estimated": ["income"]},
       "evidence": {"web": 23, "quant": 3, "social": 7}}


def _record(**kw):
    base = {"id": "r1", "kind": "headline", "instrument": "verdict", "label": "Population verdict on the question", "question": "Q",
            "estimate": {"metric": "for_share", "label": "In favour", "format": "share", "value": 0.37, "low": 0.25, "high": 0.51, "n": 49},
            "weighted": {"weighted": 0.35, "ess": 31.2}, "refusals": {"refused": 1}, "unanimity": {"flagged": False}, "confidence": {"score": 58, "drivers": ["49 twins answered"]},
            "provenance": {"frame_level": "fair", "scoped": True, "model": "m", "seed": 7, "created_at": "2026-09-29"},
            "equity": {"available": True, "most": {"label": "Q1 most deprived", "share": 0.6}, "least": {"label": "Q5 least deprived", "share": 0.4}, "gap": 20.0, "significant": False},
            "splits": {"deprivation": [{"value": "Q1 most deprived", "share": 0.6, "low": 0.4, "high": 0.8, "n": 20, "thin": False}]},
            "sources": [{"unit_id": "u1", "twins": 13}], "caveats": ["Small population.", "Synthetic population: twins."], "barriers": []}
    base.update(kw)
    return base


def test_the_statement_is_specific_to_the_run_and_says_what_it_must_not_be_used_for():
    st = ex.statement(RUN)
    assert st.startswith("SYNTHETIC POPULATION STATEMENT") and "49 synthetic twins" in st
    assert "matched to published distributions on place, age, deprivation and weighted on income" in st and "income was model-estimated" in st
    assert "23 web" in st and "must not be used as evidence of what real people think" in st and "Should GPs prescribe?" in st
    bare = ex.statement({"question": "Q", "population": {"n": 12}, "frame": {"level": "none"}, "evidence": {}})
    assert "not matched to any published distribution" in bare and "no evidence items" in bare


def test_records_flatten_to_one_row_per_record_and_one_per_cut_cell():
    rows = ex.records_rows([_record()])
    assert rows[0]["value"] == 0.37 and rows[0]["equity_most"] == "Q1 most deprived" and rows[0]["equity_gap"] == 20.0 and rows[0]["sources_cited"] == 1
    assert rows[0]["weighted_value"] == 0.35 and rows[0]["scoped"] is True and "Synthetic population" in rows[0]["caveats"]
    csv_text = ex._csv(rows, ex.RECORD_COLUMNS)
    assert csv_text.splitlines()[0].startswith("record_id,kind,instrument") and "Population verdict on the question" in csv_text
    splits = ex.split_rows([_record()])
    assert splits == [{"record_id": "r1", "label": "Population verdict on the question", "split": "deprivation", "cell": "Q1 most deprived", "value": 0.6, "low": 0.4, "high": 0.8, "n": 20, "thin": False}]
    roster = ex.roster_rows([SimpleNamespace(id="a1", name="Rosa", age=44, role="GP", stance=SimpleNamespace(value="direct"), segment="S", humanity=40, weight=1.2,
                                             demographics={"region": "Blackpool", "frame": {"deprivation": "Q1 most deprived"}}, knowledge={"visible": 6, "total": 9, "written_from": "scoped"}, validation={"score": 71})])
    assert roster[0]["deprivation"] == "Q1 most deprived" and roster[0]["knowledge_visible"] == 6 and roster[0]["validation_score"] == 71 and roster[0]["stance"] == "direct"


def test_the_client_document_resolves_every_citation_and_carries_the_statement_top_and_bottom():
    report = {"answer": "Most agree [[record:r1]], said [[twin:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa]]. Obesity is 34% [[fact:e1#0]] per [[evidence:e1]]. About [[unsourced:12%]] said so.",
              "structure": {"direct_answer": {"confidence": {"band": "MEDIUM", "score": 58, "drivers": ["49 twins answered"]}},
                            "outcome": {"caveats": [{"text": "Small population."}], "barriers": {"outcome": "take it up", "items": [{"theme": "cost", "count": 14, "weight_mean": 80, "removals": ["NHS pays"], "agent_ids": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]}]}}}}
    ledger = {"facts": [{"id": "e1#0", "value": "34%", "statistic": "adults with obesity", "source": "ONS", "year": "2024", "provenance_class": "official_statistic"}],
              "items": [{"id": "e1", "title": "Obesity 2024", "provenance_class": "official_statistic"}]}
    md = ex.client_markdown(run=RUN, report=report, records=[_record()], agents={"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa": "Rosa Nair"}, ledger=ledger)
    assert md.count("SYNTHETIC POPULATION STATEMENT") == 2 and md.index("SYNTHETIC POPULATION STATEMENT") < md.index("## Outcome records")
    assert "Confidence (computed): MEDIUM · 58/100" in md
    assert "Most agree [37% (95% CI 25–51%, n=49) — Population verdict on the question, model-inferred], said Rosa Nair." in md
    assert "34% [34% — adults with obesity, ONS 2024, official statistic]" in md and "[Obesity 2024, official statistic]" in md
    assert "12% [unsourced — typed by the model, not counted]" in md
    assert "1. **cost** — 14 twins, weight 80/100; removed by NHS pays; raised by Rosa Nair" in md
    assert "gap 20.0 points, not distinguishable at this size" in md and "- Small population." in md
    assert "[[" not in md


def _side(value, low, high, positions, dissent, barriers, evidence, band, unsourced=0):
    rec = _record(estimate={"metric": "for_share", "label": "In favour", "format": "share", "value": value, "low": low, "high": high, "n": 49})
    recs = [rec] + ([{"id": "b", "kind": "probe", "instrument": "barriers", "barriers": [{"theme": t, "count": c} for t, c in barriers], "estimate": {"n": 49}}] if barriers else [])
    return {"report": {"id": f"rep{value}", "created_at": "t", "structure": {
        "direct_answer": {"confidence": {"band": band, "score": 50}},
        "discussion": {"positions": [{"value": k, "share": v} for k, v in positions.items()], "majority": max(positions, key=positions.get), "dissent": [{"agent_id": d, "position": "against"} for d in dissent]},
        "source_materials": {"evidence": [{"class": k, "count": v} for k, v in evidence.items()]},
        "figures": {"unsourced": ["x"] * unsourced}, "records": {"all": [r["id"] for r in recs]}}}, "records": recs}


def test_the_delta_reads_what_changed_and_whether_the_headline_change_is_real():
    a = _side(0.37, 0.25, 0.51, {"for": 0.37, "mixed": 0.39, "against": 0.24}, ["d1", "d2"], [("cost", 14), ("capacity", 9)], {"web": 23, "quant": 3}, "MEDIUM", 2)
    b = _side(0.62, 0.53, 0.70, {"for": 0.62, "mixed": 0.2, "against": 0.18}, ["d2", "d3"], [("capacity", 12), ("supply", 5)], {"web": 40, "quant": 6, "social": 9}, "HIGH", 0)
    d = dl.compare(a, b)
    assert d["headline"]["change_points"] == 25.0 and d["headline"]["real"] is True
    assert d["positions"][0] == {"value": "for", "then": 0.37, "now": 0.62, "change_points": 25.0}
    assert [x["agent_id"] for x in d["dissent"]["joined"]] == ["d3"] and [x["agent_id"] for x in d["dissent"]["left"]] == ["d1"] and d["dissent"]["majority_now"] == "for"
    assert d["barriers"]["appeared"][0]["theme"] == "supply" and d["barriers"]["dropped"][0]["theme"] == "cost" and d["barriers"]["moved"][0] == {"theme": "capacity", "then": 2, "now": 1, "count_then": 9, "count_now": 12}
    assert d["evidence_total"] == {"then": 26, "now": 55} and next(e for e in d["evidence"] if e["class"] == "social")["change"] == 9
    assert d["confidence"]["now"]["band"] == "HIGH" and d["unsourced"] == {"then": 2, "now": 0}
    s = d["summary"]
    assert "In favour moved +25 points (37% → 62%), a real change" in s and "evidence base went from 26 to 55" in s and "new barrier(s): supply" in s and "barrier(s) gone: cost" in s
    assert "1 twin(s) joined the dissent, 1 left it" in s and "MEDIUM → HIGH" in s
    # overlapping intervals: not a real change
    c = _side(0.40, 0.28, 0.54, {"for": 0.4, "mixed": 0.36, "against": 0.24}, ["d1", "d2"], [("cost", 14), ("capacity", 9)], {"web": 23, "quant": 3}, "MEDIUM", 2)
    d2 = dl.compare(a, c)
    assert d2["headline"]["real"] is False and "not distinguishable" in d2["summary"] and d2["barriers"]["same"][0]["theme"] == "cost"


def test_the_client_document_names_a_twin_once_per_paragraph():
    from app.services.simulation import export as ex
    a = "11111111-1111-1111-1111-111111111111"; post = "aaaaaaaa-1111-1111-1111-111111111111"
    text = (f"[[twin:{a}]] [[twin:{a}]]: \"Most will try it\". For him to be right, his [[twin:{a}|post:{post}]] claim must hold.\n"
            f"Later, [[twin:{a}]] agreed.")
    out = ex.resolve_citations(text, agents={a: "Gary Pendleton"}, records={}, facts={}, items={})
    assert out == "Gary Pendleton: \"Most will try it\". For him to be right, his claim must hold.\nLater, Gary Pendleton agreed."
