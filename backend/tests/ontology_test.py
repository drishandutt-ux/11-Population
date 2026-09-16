"""The typed ontology over the session graph (services/knowledge_graph/ontology.py).

Run:  cd backend && pytest tests/ontology_test.py -q
No network. Covers: the schema's integrity, assembly from classified entities (typed edges,
implied geography containment as inferred nodes/edges, class counts, mention counts), the
classify/type helpers with the model stubbed (batching, unknown values falling back), and the
HTTP surface: GET before a build → schema only; POST on an empty graph → 400; build → stored,
GET returns it; a grown graph flags it stale.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.knowledge_graph import ontology  # noqa: E402


# ── schema ────────────────────────────────────────────────────────────────────

def test_schema_predicates_only_name_known_classes():
    keys = set(ontology.CLASS_KEYS) | {"*"}
    for p in ontology.PREDICATES:
        assert set(p["domain"]) <= keys, p["key"]
        assert set(p["range"]) <= keys, p["key"]
    assert "other" in ontology.CLASS_KEYS and "related_to" in ontology.PREDICATE_KEYS
    assert ontology.SCHEMA["geo_levels"][0] == "nation"


# ── assembly (pure) ───────────────────────────────────────────────────────────

def _classes():
    return {
        "Blackpool": {"cls": "geography", "level": "local_authority", "parent": "North West", "parent_level": "region"},
        "North West": {"cls": "geography", "level": "region", "parent": "England", "parent_level": "nation"},
        "GP": {"cls": "hcp_role", "level": None, "parent": "", "parent_level": None},
        "Obesity": {"cls": "condition", "level": None, "parent": "", "parent_level": None},
        "Oral GLP-1": {"cls": "intervention", "level": None, "parent": "", "parent_level": None},
    }


def test_assemble_types_edges_and_infers_containment():
    entities = ["Blackpool", "North West", "GP", "Obesity", "Oral GLP-1"]
    relations = [["GP", "manages", "Obesity"], ["Oral GLP-1", "is prescribed for", "Obesity"], ["GP", "works in", "Blackpool"]]
    predicates = ["treats", "addresses", "located_in"]
    chunks = ["Blackpool GPs see obesity daily", "obesity in Blackpool", "GLP-1"]
    out = ontology.assemble(entities, relations, _classes(), predicates, chunks)

    by = {n["id"]: n for n in out["nodes"]}
    assert by["Blackpool"]["cls"] == "geography" and by["Blackpool"]["level"] == "local_authority"
    assert by["Blackpool"]["mentions"] == 2 and by["GP"]["mentions"] == 1 and by["Oral GLP-1"]["mentions"] == 0
    # England was never an entity: it arrives as an inferred geography node at nation level
    assert by["England"]["inferred"] is True and by["England"]["level"] == "nation"
    assert by["North West"]["inferred"] is False

    edges = {(e["head"], e["predicate"], e["tail"]) for e in out["edges"]}
    assert ("GP", "treats", "Obesity") in edges
    assert ("Oral GLP-1", "addresses", "Obesity") in edges
    assert ("Blackpool", "within", "North West") in edges and ("North West", "within", "England") in edges
    within = [e for e in out["edges"] if e["predicate"] == "within"]
    assert all(e["inferred"] for e in within)
    typed = next(e for e in out["edges"] if e["predicate"] == "treats")
    assert typed["verb"] == "manages" and typed["inferred"] is False

    assert out["counts"]["geography"] == 3 and out["counts"]["hcp_role"] == 1 and out["counts"]["other"] == 0


def test_assemble_drops_self_loops_duplicates_and_unknown_endpoints():
    entities = ["A", "B"]
    classes = {"A": {"cls": "other", "level": None}, "B": {"cls": "other", "level": None}}
    relations = [["A", "x", "A"], ["A", "x", "B"], ["A", "y", "B"], ["A", "z", "Zed"]]
    out = ontology.assemble(entities, relations, classes, ["related_to", "related_to", "related_to", "related_to"], [])
    assert len(out["edges"]) == 1 and out["edges"][0]["tail"] == "B"


def test_geography_parent_that_is_an_existing_non_geography_is_ignored():
    classes = {
        "Bristol": {"cls": "geography", "level": "local_authority", "parent": "NHS", "parent_level": "region"},
        "NHS": {"cls": "organisation", "level": None, "parent": "", "parent_level": None},
    }
    out = ontology.assemble(["Bristol", "NHS"], [], classes, [], [])
    assert not out["edges"] and len(out["nodes"]) == 2


# ── the model-facing helpers, stubbed ─────────────────────────────────────────

def test_classify_batches_and_falls_back_on_junk(monkeypatch):
    seen = []

    async def fake_analyze(schema, system, user, **kw):
        seen.append(user)
        names = [line[2:] for line in user.splitlines() if line.startswith("- ")]
        nodes = [{"name": n, "cls": "condition", "level": "none", "parent": "", "parent_level": "none"} for n in names[:-1]]
        nodes.append({"name": names[-1], "cls": "not-a-class", "level": "region", "parent": "", "parent_level": "none"})
        nodes.append({"name": "Hallucinated", "cls": "geography", "level": "nation", "parent": "", "parent_level": "none"})
        return {"nodes": nodes}

    monkeypatch.setattr(ontology, "analyze", fake_analyze)
    entities = [f"E{k}" for k in range(ontology.ENTITY_BATCH + 5)]
    out = asyncio.run(ontology.classify_entities(entities, session_id="s"))
    assert len(seen) == 2                       # two batches
    assert set(out) == set(entities)            # nothing invented, nothing dropped
    assert out["E0"]["cls"] == "condition" and out["E0"]["level"] is None
    assert out[entities[-1]]["cls"] == "other"  # unknown class → other


def test_type_relations_keeps_order_and_defaults_to_related_to(monkeypatch):
    async def fake_analyze(schema, system, user, **kw):
        assert "[hcp_role]" in user and "[condition]" in user
        return {"edges": [{"index": 1, "predicate": "treats"}, {"index": 7, "predicate": "treats"}, {"index": 0, "predicate": "bogus"}]}

    monkeypatch.setattr(ontology, "analyze", fake_analyze)
    classes = {"GP": {"cls": "hcp_role"}, "Obesity": {"cls": "condition"}}
    rels = [["GP", "sees", "Obesity"], ["GP", "manages", "Obesity"]]
    out = asyncio.run(ontology.type_relations(rels, classes, session_id="s"))
    assert out == ["related_to", "treats"]


# ── HTTP ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.core.database as dbm
    from app.core.config import get_settings
    import app.models.report, app.models.preset, app.models.kg, app.models.population  # noqa: F401
    from app.services.knowledge_graph import lightrag_service

    monkeypatch.setattr(get_settings(), "app_supabase_url", "")
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/onto.db")
    Session = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(dbm, "engine", eng)
    monkeypatch.setattr(dbm, "AsyncSessionLocal", Session)
    monkeypatch.setattr(dbm, "_sqlite", True)
    lightrag_service._kg_cache.clear()

    async def fake_analyze(schema, system, user, **kw):
        props = schema.get("properties", {})
        if "nodes" in props:
            names = [line[2:] for line in user.splitlines() if line.startswith("- ")]
            cls = {"Blackpool": ("geography", "local_authority", "North West", "region"), "GP": ("hcp_role", "none", "", "none"), "Obesity": ("condition", "none", "", "none")}
            return {"nodes": [{"name": n, "cls": cls.get(n, ("other", "none", "", "none"))[0], "level": cls.get(n, ("other", "none", "", "none"))[1],
                               "parent": cls.get(n, ("other", "none", "", "none"))[2], "parent_level": cls.get(n, ("other", "none", "", "none"))[3]} for n in names]}
        return {"edges": [{"index": 0, "predicate": "treats"}]}

    monkeypatch.setattr(ontology, "analyze", fake_analyze)

    async def _get_db():
        async with Session() as s:
            yield s

    from fastapi.testclient import TestClient
    from app.main import app
    app.dependency_overrides[dbm.get_db] = _get_db
    with TestClient(app) as client:
        yield client, Session
    app.dependency_overrides.clear()


def test_http_ontology_round_trip(api_client):
    client, Session = api_client
    from app.services.knowledge_graph import lightrag_service

    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "Oral GLP-1 uptake in Blackpool", "auto_research": False}).json()["id"]

    # before any build: the schema is there, the ontology is not, and an empty graph refuses to build
    r = client.get(f"/api/v1/sessions/{sid}/kg/ontology")
    assert r.status_code == 200
    body = r.json()
    assert body["ontology"] is None and body["stale"] is False and body["entity_count"] == 0
    assert [c["key"] for c in body["schema"]["classes"]][0] == "geography"
    assert client.post(f"/api/v1/sessions/{sid}/kg/ontology/build").status_code == 400

    # seed a graph straight into the store (no model), then build
    asyncio.run(lightrag_service._save_kg(sid, {"entities": ["GP", "Obesity", "Blackpool"], "relations": [["GP", "treats", "Obesity"]], "chunks": ["GP obesity Blackpool"]}))
    r = client.post(f"/api/v1/sessions/{sid}/kg/ontology/build")
    assert r.status_code == 200, r.text
    onto = r.json()["ontology"]
    assert onto["entity_count"] == 3 and onto["classified"] == 3 and onto["typed"] == 1
    by = {n["id"]: n for n in onto["nodes"]}
    assert by["GP"]["cls"] == "hcp_role" and by["Blackpool"]["level"] == "local_authority"
    assert by["North West"]["inferred"] is True
    assert {(e["head"], e["predicate"], e["tail"]) for e in onto["edges"]} == {("GP", "treats", "Obesity"), ("Blackpool", "within", "North West")}
    assert r.json()["stale"] is False

    # it persisted: GET returns it; a graph that grew since is flagged stale
    assert client.get(f"/api/v1/sessions/{sid}/kg/ontology").json()["ontology"]["built_at"] == onto["built_at"]
    asyncio.run(lightrag_service._save_kg(sid, {"entities": ["GP", "Obesity", "Blackpool", "NHS England"], "relations": [["GP", "treats", "Obesity"]], "chunks": []}))
    body = client.get(f"/api/v1/sessions/{sid}/kg/ontology").json()
    assert body["stale"] is True and body["entity_count"] == 4 and body["ontology"]["entity_count"] == 3

    # another user's session is invisible (dev mode has one user, so assert the 404 path on a random id)
    assert client.get("/api/v1/sessions/does-not-exist/kg/ontology").status_code == 404
