"""`kg_sources`: the graph's chunks summarised by the material they came from (the simple
view's flow diagram reads it)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.knowledge_graph import lightrag_service as lr  # noqa: E402


def test_kg_sources_groups_chunks_by_material(monkeypatch):
    monkeypatch.setattr(lr, "_load_kg", lambda sid: {
        "entities": ["a", "b"], "relations": [["a", "r", "b"]],
        "chunks": [
            "[SOURCE personal | survey.pdf]\none", "[SOURCE personal | survey.pdf]\ntwo",
            "[SOURCE personal | pasted text]\nthree",
            "[SOURCE youtube | user-supplied video]\nfour",
            "[SOURCE web | user-supplied page https://ons.gov.uk/x]\nfive",
            "[SOURCE web | A title | https://e.com/p | 2024]\nsix",
            "[SOURCE social reddit | UKPersonalFinance | https://reddit.com/x | undated | score 3]\nseven",
            "[SOURCE quant | ONS | https://ons.gov.uk/q | 2023]\neight",
            "no header at all",
        ],
    })
    out = lr.kg_sources("s")
    assert out["chunks"] == 9 and out["entities"] == 2 and out["relations"] == 1
    by = {(r["kind"], r["name"]): r for r in out["sources"]}
    assert by[("file", "survey.pdf")]["chunks"] == 2
    assert ("text", "Pasted text") in by and ("video", "YouTube video") in by
    assert by[("page", "https://ons.gov.uk/x")]["chunks"] == 1
    assert by[("research", "A title")]["ref"] == "https://e.com/p"
    assert ("social", "r/UKPersonalFinance") in by
    assert ("statistics", "ONS") in by
    assert by[("other", "Untagged material")]["chunks"] == 1
    assert out["sources"][0]["kind"] == "file"  # most chunks first


def test_kg_sources_empty_graph(monkeypatch):
    monkeypatch.setattr(lr, "_load_kg", lambda sid: {"entities": [], "relations": [], "chunks": []})
    assert lr.kg_sources("s") == {"sources": [], "chunks": 0, "entities": 0, "relations": 0}
