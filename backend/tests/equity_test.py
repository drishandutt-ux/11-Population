"""Equity stratification by default (brief L6-04): every result by deprivation level as well as
the headline.

Run:  cd backend && pytest tests/equity_test.py -q
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.population import equity as eq  # noqa: E402
from app.services.population import frame as frame_mod  # noqa: E402
from app.services.simulation import records as rec  # noqa: E402


def test_fifths_by_default_tenths_only_for_a_large_population():
    assert eq.level_for(12) == "quintile" and eq.level_for(199) == "quintile" and eq.level_for(200) == "decile" and eq.level_for(None) == "quintile"
    assert eq.labels("quintile") == ["Q1 most deprived", "Q2", "Q3", "Q4", "Q5 least deprived"]
    assert eq.labels("decile")[0] == "D1 most deprived" and eq.labels("decile")[-1] == "D10 least deprived" and len(eq.labels("decile")) == 10


def test_the_frame_always_carries_deprivation_inside_the_matched_top_three():
    dims = [{"key": "place", "label": "Place", "attribute": "region"}, {"key": "age", "label": "Age", "attribute": "age"},
            {"key": "income", "label": "Income", "attribute": "income"}, {"key": "tenure", "label": "Tenure", "attribute": "tenure"}]
    out = eq.ensure_dimension(dims, 40)
    assert [d["key"] for d in out] == ["place", "age", "deprivation", "income", "tenure"]
    assert out[2]["equity"] is True and out[2]["level"] == "quintile" and out[2]["attribute"] == "deprivation"
    # the planner already chose it under its own name: kept, renamed, not duplicated
    chosen = eq.ensure_dimension([{"key": "imd_decile", "label": "IMD decile", "attribute": "other"}, {"key": "age", "label": "Age", "attribute": "age"}], 300)
    assert [d["key"] for d in chosen] == ["deprivation", "age"] and chosen[0]["level"] == "decile" and chosen[0]["label"] == "IMD decile"
    assert eq.ensure_dimension([], 10)[0]["key"] == "deprivation"


def test_any_spelling_of_a_cell_reads_back_to_its_rank():
    q = "quintile"
    assert eq.rank_of("Q1 most deprived", q) == 1 and eq.rank_of("Q5 least deprived", q) == 5 and eq.rank_of("Q3", q) == 3
    assert eq.rank_of("quintile 2", q) == 2 and eq.rank_of("2nd quintile", q) == 2 and eq.rank_of("most deprived 20%", q) == 1 and eq.rank_of("20% least deprived", q) == 5
    assert eq.rank_of("decile 7", q) == 4 and eq.rank_of("D10", q) == 5 and eq.rank_of("IMD 1-2", q) == 1 and eq.rank_of("deciles 9-10", q) == 5
    assert eq.rank_of("most deprived", q) == 1 and eq.rank_of("least deprived", q) == 5 and eq.rank_of("affluent suburb", q) is None and eq.rank_of("", q) is None
    assert eq.rank_of("Q2", "decile") == 3 and eq.rank_of("D7", "decile") == 7
    assert eq.canonical("decile 3", q) == "Q2" and eq.canonical("nonsense", q) is None
    cats = [{"label": l} for l in eq.labels(q)]
    assert eq.category_for("2nd quintile", cats, q) == "Q2" and eq.category_for("least deprived fifth", cats, q) == "Q5 least deprived"
    # through the frame's own categoriser
    dim = {"key": "deprivation", "attribute": "deprivation"}
    assert frame_mod.category_of(dim, {"categories": cats}, value="Most deprived 20%") == "Q1 most deprived"
    assert frame_mod.agent_cell(dim, {"categories": cats}, {"demographics": {"frame": {"deprivation": "Q4"}}}) == "Q4"


def test_a_found_decile_table_becomes_fifths_and_nothing_found_becomes_the_labelled_reference():
    found = {"status": "found", "source": "IMD 2019", "categories": [{"label": f"Decile {k}", "share_pct": 10 + (5 - k)} for k in range(1, 11)]}
    fr = {"dimensions": [eq.dimension("quintile")], "targets": {"deprivation": found}, "geography": "Blackpool"}
    out, note = eq.ensure_target(fr, "quintile")
    cats = out["targets"]["deprivation"]["categories"]
    assert [c["label"] for c in cats] == eq.labels("quintile") and cats[0]["share_pct"] == 27.0 and "5 cells" in note
    missing = {"dimensions": [eq.dimension("quintile")], "targets": {"deprivation": {"status": "missing", "categories": []}}, "geography": "Blackpool"}
    out2, note2 = eq.ensure_target(missing, "quintile")
    t = out2["targets"]["deprivation"]
    assert t["status"] == "estimated" and t["provenance"] == "model_inference" and t["reference"] is True and len(t["categories"]) == 5 and t["categories"][0]["share_pct"] == 20.0
    assert "national reference" in note2 and "Blackpool" in t["note"]
    # a frame without the dimension is left alone
    assert eq.ensure_target({"dimensions": [], "targets": {}}, "quintile") == ({"dimensions": [], "targets": {}}, None)
    # the persona writer is told what the cell means
    assert "Q1 most deprived" in eq.persona_note("quintile") and "without naming the index" in eq.persona_note("quintile")


def test_the_lab_splits_every_result_by_deprivation():
    from app.services.measurement import probe as probe_svc
    assert "deprivation" in probe_svc.BASE_SPLIT_KEYS
    agent = SimpleNamespace(dials={}, stance=SimpleNamespace(value="direct"), age=40, humanity=50, segment=None,
                            demographics={"region": "Blackpool", "frame": {"deprivation": "most deprived 20%"}})
    assert probe_svc.segments_for(agent)["deprivation"] == "Q1 most deprived"
    agent.demographics = {"deprivation": "D8"}
    assert probe_svc.segments_for(agent)["deprivation"] == "D8"
    agent.demographics = {"region": "Oxford"}
    assert "deprivation" not in probe_svc.segments_for(agent)


def _bucket(label, share, low, high, n, thin=False):
    return {"segment": "deprivation", "value": label, "share": share, "low": low, "high": high, "n": n, "thin": thin}


def test_the_equity_block_reads_the_gap_between_the_most_and_least_deprived_cells():
    buckets = [_bucket("Q3", 0.5, 0.2, 0.8, 4), _bucket("Q5 least deprived", 0.9, 0.7, 0.98, 10), _bucket("Q1 most deprived", 0.3, 0.15, 0.5, 12), _bucket("Q2", 0.4, 0.1, 0.7, 2, thin=True)]
    e = eq.equity_block(buckets)
    assert e["available"] and e["level"] == "quintile" and [c["label"] for c in e["cells"]] == ["Q1 most deprived", "Q2", "Q3", "Q5 least deprived"]
    assert e["most"]["n"] == 12 and e["least"]["n"] == 10 and e["gap"] == -60.0 and e["significant"] is True and e["thin"] == ["Q2"]
    line = eq.prompt_line(e)
    assert line.startswith("equity: Q1 most deprived 30% (n=12) vs Q5 least deprived 90% (n=10), gap -60 points — a real gap; thin: Q2")
    overlapping = eq.equity_block([_bucket("Q1 most deprived", 0.6, 0.3, 0.85, 5), _bucket("Q5 least deprived", 0.7, 0.4, 0.9, 5)])
    assert overlapping["significant"] is False and "not distinguishable" in eq.prompt_line(overlapping)
    none = eq.equity_block([])
    assert none["available"] is False and "without a sampling frame" in none["reason"] and "not available" in eq.prompt_line(none)


def test_a_record_carries_its_equity_line_and_the_caveat_when_it_has_none():
    agg = {"n": 12, "headline": {"metric": "for_share", "label": "In favour", "share": 0.5, "low": 0.25, "high": 0.75, "n": 12, "successes": 6}, "sentence": "s",
           "segments": {"deprivation": [_bucket("Q1 most deprived", 0.2, 0.05, 0.5, 6), _bucket("Q5 least deprived", 0.8, 0.55, 0.95, 6)]}}
    p = SimpleNamespace(id="v1", instrument="verdict", spec={"question": "Q?"}, seed=1, schema_id="verdict.v1", prompt_hash="h", model="m", agent_count=12, answer_count=12,
                        created_at=None, aggregates=agg)
    r = rec.record_from_probe(p)
    assert r["equity"]["available"] and r["equity"]["gap"] == -60.0 and r["equity"]["significant"] is True
    assert not any("deprivation" in c.lower() for c in r["caveats"])
    text, _ = rec.records_block([r])
    assert "equity: Q1 most deprived 20% (n=6) vs Q5 least deprived 80% (n=6), gap -60 points — a real gap" in text
    p.aggregates = {**agg, "segments": {}}
    r2 = rec.record_from_probe(p)
    assert r2["equity"]["available"] is False and any(c.startswith("No deprivation levels") for c in r2["caveats"])
    assert "equity: not available" in rec.records_block([r2])[0]
    assert "equity line" in rec.FIGURE_RULES
