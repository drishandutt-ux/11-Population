"""Population facets (services/population/facets.py). Run:  cd backend && pytest tests/facets_test.py -q"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.population import facets  # noqa: E402


class A:
    def __init__(self, **kw):
        self.age = kw.pop("age", 40); self.humanity = kw.pop("humanity", 30); self.segment = kw.pop("segment", None); self.stance = kw.pop("stance", "direct")
        self.demographics = kw


def test_cell_of_reads_attributes_persona_facets_and_bands():
    a = A(age=37, humanity=72, segment="Commuters", region="Hackney", income_band="middle", gender="female", facets={"commute": "Bus"})
    assert facets.cell_of({"kind": "attribute", "attribute": "region"}, a) == "Hackney"
    assert facets.cell_of({"kind": "attribute", "attribute": "age"}, a) == "30s"
    assert facets.cell_of({"kind": "attribute", "attribute": "register"}, a) == "reactive"
    assert facets.cell_of({"kind": "attribute", "attribute": "segment"}, a) == "Commuters"
    assert facets.cell_of({"kind": "attribute", "attribute": "income_band"}, a) == "middle"
    assert facets.cell_of({"kind": "persona", "key": "commute"}, a) == "Bus"
    assert facets.cell_of({"kind": "persona", "key": "car"}, a) is None
    assert facets.cell_of({"kind": "attribute", "attribute": "gender"}, A(gender="n/a")) is None
    assert facets.cell_of({"kind": "attribute", "attribute": "education"}, {"demographics": {"education": "degree"}}) == "degree"


def test_counts_for_sums_to_the_population_per_facet():
    agents = [A(region="Hackney", facets={"commute": "Bus"}), A(region="Hackney", facets={"commute": "Tube"}), A(region="Camden")]
    out = facets.counts_for([{"key": "place", "kind": "attribute", "attribute": "region"}, {"key": "commute", "kind": "persona"}], agents)
    assert out["place"] == {"Hackney": 2, "Camden": 1} and out["commute"] == {"Bus": 1, "Tube": 1}


def test_pick_facets_cleans_ranks_and_backfills(monkeypatch):
    async def fake_analyze(schema, system, user, **kw):
        assert "Planned segments" in user
        return {"facets": [
            {"key": "Commute Mode!", "label": "Commute mode", "why": "w", "kind": "persona", "attribute": "region", "values_hint": ["Bus", "Tube", "Cycle", ""]},
            {"key": "income", "label": "Income band", "why": "w", "kind": "attribute", "attribute": "income_band", "values_hint": []},
            {"key": "bogus", "label": "Bogus", "why": "", "kind": "attribute", "attribute": "none", "values_hint": []},
            {"key": "income", "label": "dup", "why": "", "kind": "attribute", "attribute": "income_band", "values_hint": []},
        ]}
    monkeypatch.setattr(facets, "analyze", fake_analyze)
    out = asyncio.run(facets.pick_facets("s", "q", {"geography": "London"}, [{"name": "Commuters", "share_pct": 60, "description": "d"}]))
    keys = [f["key"] for f in out]
    assert keys[0] == "place"                                        # place is always present, first when the model forgot it
    assert "commute_mode" in keys and "income" in keys and "bogus" not in keys
    assert keys.count("income") == 1 and len(out) >= facets.MIN_FACETS
    cm = next(f for f in out if f["key"] == "commute_mode")
    assert cm["kind"] == "persona" and cm["attribute"] == "none" and cm["values_hint"] == ["Bus", "Tube", "Cycle"]
    assert "commute_mode (Commute mode): one of Bus / Tube / Cycle" in facets.facets_block_for_prompt(out)


def test_pick_facets_falls_back_when_the_model_fails(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("no model")
    monkeypatch.setattr(facets, "analyze", boom)
    out = asyncio.run(facets.pick_facets("s", "q", None, []))
    assert [f["key"] for f in out][:2] == ["place", "age_band"] and len(out) >= facets.MIN_FACETS
    assert facets.facets_block_for_prompt(out) == ""
