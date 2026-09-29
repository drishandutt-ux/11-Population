"""Answers traceable to the documents the twin drew on (brief L6-05): the knowledge block is
numbered, the twin cites the numbers, the answer stores the documents, and barriers and
records roll them up.

Run:  cd backend && pytest tests/sources_test.py -q
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.measurement import probe as probe_svc  # noqa: E402
from app.services.scoping import service  # noqa: E402
from app.services.simulation import records as rec  # noqa: E402

VISIBLE = [
    {"unit": {"id": "u1", "text": "Two GP surgeries in Blackpool have merged.", "source_ref": "[SOURCE web | Gazette | https://g/a | 2025]", "provenance_class": "grey_literature", "trust_tier": "medium"}, "route": "via Local press"},
    {"unit": {"id": "u2", "text": "34% of adults in Blackpool were living with obesity.", "source_ref": "[SOURCE quant | ONS | https://ons/x | 2024]", "provenance_class": "official_statistic", "trust_tier": "high"}, "route": "from a statistic"},
]


def test_the_knowledge_block_is_numbered_and_the_served_items_are_returned():
    block, items = service.numbered_block(VISIBLE)
    assert block.splitlines()[1].startswith("[S1] (via Local press) Two GP surgeries") and "[S2] (from a statistic) 34%" in block
    assert [i["sid"] for i in items] == ["S1", "S2"] and items[1]["unit_id"] == "u2" and items[1]["provenance_class"] == "official_statistic"


def test_the_schema_gains_a_sources_field_and_the_twins_numbers_resolve_to_documents():
    schema = probe_svc.with_sources({"type": "object", "properties": {"reasoning": {"type": "string"}}, "required": ["reasoning"]})
    assert "sources_used" in schema["properties"] and schema["properties"]["sources_used"]["type"] == "array" and schema["required"] == ["reasoning"]
    _, served = service.numbered_block(VISIBLE)
    out = probe_svc.resolve_sources({"reasoning": "r", "sources_used": ["S2", "[S1]", "s2", "S9"]}, served)
    assert [u["unit_id"] for u in out["used_units"]] == ["u2", "u1"] and out["served_units"] == ["u1", "u2"]
    assert out["used_units"][0]["provenance_class"] == "official_statistic" and sorted(out["sources_used"]) == ["S1", "S2"]
    none = probe_svc.resolve_sources({"reasoning": "r"}, served)
    assert none["used_units"] == [] and none["served_units"] == ["u1", "u2"]
    assert "SOURCES:" in probe_svc.SOURCES_RULE


def test_records_roll_up_what_the_twins_cited():
    answers = [
        {"used_units": [{"unit_id": "u2", "source_ref": "ons", "provenance_class": "official_statistic", "trust_tier": "high", "text": "34%"}]},
        {"used_units": [{"unit_id": "u2", "source_ref": "ons", "provenance_class": "official_statistic", "trust_tier": "high", "text": "34%"},
                        {"unit_id": "u1", "source_ref": "gazette", "provenance_class": "grey_literature", "trust_tier": "medium", "text": "merged"}]},
        {"used_units": []},
    ]
    roll = rec.sources_used(answers)
    assert [(u["unit_id"], u["twins"]) for u in roll] == [("u2", 2), ("u1", 1)]
    from types import SimpleNamespace
    p = SimpleNamespace(id="p", instrument="verdict", spec={"question": "Q"}, seed=1, schema_id="v", prompt_hash="h", model="m", agent_count=3, answer_count=3, created_at=None,
                        aggregates={"n": 3, "headline": {"metric": "for_share", "label": "In favour", "share": 0.67, "low": 0.2, "high": 0.9, "n": 3, "successes": 2},
                                    "sentence": "s", "segments": {}, "sources_used": roll})
    assert rec.record_from_probe(p)["sources"][0]["unit_id"] == "u2"
