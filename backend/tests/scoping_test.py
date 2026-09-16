"""Scoped retrieval (services/scoping). Run:  cd backend && pytest tests/scoping_test.py -q
No network. The engine and profiles are pure; the tagger and the HTTP surface run with the
model stubbed.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.scoping import engine, profiles, registry, tagger  # noqa: E402

ONTO = {
    "nodes": [
        {"id": "England", "cls": "geography", "level": "nation"}, {"id": "North West", "cls": "geography", "level": "region"},
        {"id": "Blackpool", "cls": "geography", "level": "local_authority"}, {"id": "Oxford", "cls": "geography", "level": "local_authority"},
        {"id": "GP", "cls": "hcp_role"}, {"id": "Community pharmacist", "cls": "hcp_role"},
        {"id": "Local press", "cls": "channel"}, {"id": "Rep visits", "cls": "channel"}, {"id": "NHS app", "cls": "channel"},
        {"id": "Obesity", "cls": "condition"}, {"id": "IMD 1-2 households", "cls": "attitude_segment"},
    ],
    "edges": [
        {"head": "Blackpool", "predicate": "within", "tail": "North West"}, {"head": "North West", "predicate": "within", "tail": "England"},
        {"head": "GP", "predicate": "treats", "tail": "Obesity"},
    ],
    "entity_count": 11,
}


def _unit(text, **facets):
    prov = facets.pop("provenance_class", "grey_literature")
    trust = facets.pop("trust_tier", "medium")
    return {"id": text[:12], "text": text, "source_ref": "", "provenance_class": prov, "trust_tier": trust, "facets": facets}


class _Agent:
    def __init__(self, **kw):
        self.id = kw.pop("id", "a1"); self.session_id = kw.pop("session_id", "s1")
        self.name = kw.pop("name", "A"); self.role = kw.pop("role", "Retail worker"); self.background = kw.pop("background", "")
        self.humanity = kw.pop("humanity", 60); self.segment = kw.pop("segment", None)
        self.demographics = kw.pop("demographics", None); self.exposure = kw.pop("exposure", None)


# ── engine ────────────────────────────────────────────────────────────────────

def test_ancestors_follow_within_edges_transitively():
    anc = engine.ancestors_map(ONTO)
    assert anc["Blackpool"] == {"North West", "England"}
    assert anc["North West"] == {"England"}
    assert "Oxford" not in anc


def test_base_match_semantics():
    anc = engine.ancestors_map(ONTO)
    geo = registry.BY_KEY["geography"]
    assert engine.base_match(geo, ["North West"], ["Blackpool"], anc)[0]           # region reaches the town
    assert not engine.base_match(geo, ["Oxford"], ["Blackpool"], anc)[0]           # another town does not
    assert engine.base_match(geo, [], ["Blackpool"], anc) == (True, "unscoped")    # silent unit is public
    assert engine.base_match(geo, ["Oxford"], [], anc) == (True, "not applied")     # twin without a place
    reg = registry.BY_KEY["register"]
    assert engine.base_match(reg, "technical", "lay", anc)[0] is False
    assert engine.base_match(reg, "lay", "technical", anc)[0] is True
    tm = registry.BY_KEY["time"]
    assert engine.base_match(tm, "2026-09-01", "2025-01-01", anc)[0] is False
    assert engine.base_match(tm, [], "2025-01-01", anc) == (True, "unknown")
    proj = registry.BY_KEY["project"]
    assert engine.base_match(proj, [], "s1", anc)[0] is False                      # deny-by-default when silent
    assert engine.base_match(proj, "s1", "s1", anc)[0] is True
    role = registry.BY_KEY["role"]
    assert engine.base_match(role, ["GP", "public"], ["public"], anc)[0] is True
    assert engine.base_match(role, ["GP"], ["patient", "public"], anc)[0] is False


def test_rules_deny_require_allow_boost_route_and_hard_dimensions():
    anc = engine.ancestors_map(ONTO)
    pv = {"geography": ["Blackpool"], "role": ["public"], "channel": ["Local press"], "register": "lay", "project": "s1"}
    audit = _unit("41% dropout in the audit", geography=["Blackpool"], role=["GP"], register="technical", project="s1")
    story = _unit("Oxford gets it on the NHS", geography=["Oxford"], channel=["Local press"], register="lay", project="s1", provenance_class="social_signal")

    assert engine.evaluate(audit, pv, [], anc)["visible"] is False                 # role + register fail
    allow_all = [{"dimension": "role", "when": "any", "effect": "allow", "override": ["role", "register"]}]
    assert engine.evaluate(audit, pv, allow_all, anc)["visible"] is True            # allow re-admits soft failures
    other_project = dict(audit, facets={**audit["facets"], "project": "s2"})
    ev = engine.evaluate(other_project, pv, [{"dimension": "project", "when": "any", "effect": "allow", "override": ["project", "role", "register"]}], anc)
    assert ev["visible"] is False and any(k == "project" for k, _ in ev["failed"])  # hard dimension stays failed

    ev = engine.evaluate(story, pv, [{"dimension": "channel", "when": "own", "effect": "allow", "override": ["geography"]},
                                     {"dimension": "provenance", "when": ["social_signal"], "effect": "route", "route": "hearsay"},
                                     {"dimension": "channel", "when": "own", "effect": "boost", "weight": 0.5}], anc)
    assert ev["visible"] is True and ev["route"] == "hearsay" and ev["boost"] == 0.5   # public-layer pattern

    assert engine.evaluate(story, pv, [{"dimension": "provenance", "when": ["social_signal"], "effect": "deny"}], anc)["visible"] is False
    assert engine.evaluate(story, pv, [{"dimension": "geography", "when": "own", "effect": "require"}], anc)["visible"] is False


def test_retrieve_ranks_by_query_and_trust_and_reports_hidden():
    pv = {"values": {"geography": ["Blackpool"], "role": ["public"], "channel": ["Local press"], "register": "lay", "project": "s1"}}
    units = [
        _unit("GP access in Blackpool is the first barrier", geography=["Blackpool"], register="lay", project="s1", trust_tier="high", channel=["Local press"]),
        _unit("Something unrelated about parking", register="lay", project="s1"),
        _unit("Weeks 6-12 discontinuation methods appendix", register="technical", project="s1"),
    ]
    res = engine.retrieve(units, ONTO, pv, [], "GP access barrier in Blackpool", limit=5)
    assert [r["unit"]["text"][:9] for r in res["visible"]] == ["GP access", "Something"]
    assert res["visible"][0]["route"] == "via Local press"
    assert res["hidden"][0]["failed"][0][0] == "register"
    block = engine.knowledge_block(res["visible"])
    assert block.startswith("Where you know each thing from") and "(via Local press) GP access" in block


# ── profiles ──────────────────────────────────────────────────────────────────

def test_profile_derivation_and_override():
    lay = profiles.profile_for(_Agent(role="Cleaner living with obesity", humanity=65, demographics={"region": "Blackpool, Lancashire"}, segment="IMD 1-2 households"), ONTO)
    v = lay["values"]
    assert v["geography"] == ["Blackpool"] and v["register"] == "lay" and v["role"] == ["patient", "public"]
    assert v["channel"] == ["Local press", "NHS app"]                                # public channels only
    assert v["segment"] == ["IMD 1-2 households"] and "demographics.region" in lay["basis"]["geography"]

    gp = profiles.profile_for(_Agent(role="GP partner", humanity=5, demographics={"region": "Oxford"}), ONTO)
    assert gp["values"]["role"] == ["GP", "public"] and gp["values"]["register"] == "technical"
    assert set(gp["values"]["channel"]) == {"Local press", "Rep visits", "NHS app"}

    over = profiles.profile_for(_Agent(role="GP partner", humanity=5, demographics={"region": "Oxford"}, exposure={"geography": ["Blackpool"], "register": "lay"}), ONTO)
    assert over["values"]["geography"] == ["Blackpool"] and over["values"]["register"] == "lay"
    assert over["basis"]["geography"].startswith("set on the agent")

    nowhere = profiles.profile_for(_Agent(role="Analyst", humanity=0), ONTO)
    assert nowhere["values"]["geography"] == [] and "not applied" in nowhere["basis"]["geography"]


# ── tagger ────────────────────────────────────────────────────────────────────

def test_classify_chunk_maps_headers_to_provenance():
    assert tagger.classify_chunk("[SOURCE quant | ONS | https://ons.gov.uk/x | 2024] 32% adult obesity")[:2] == ("official_statistic", "high")
    assert tagger.classify_chunk("[SOURCE social reddit | r/Blackpool | https://reddit.com/x | 2026 | 41] nobody can get a GP")[:2] == ("social_signal", "low")
    assert tagger.classify_chunk("[SOURCE web | Shah et al | https://pubmed.ncbi.nlm.nih.gov/1 | 2023] 50-68% discontinuation")[:2] == ("peer_reviewed", "high")
    assert tagger.classify_chunk("[SOURCE web | Gazette | https://blackpoolgazette.co.uk/a | 2026] GP access")[:2] == ("grey_literature", "medium")
    assert tagger.classify_chunk("[SOURCE web | NHS leaflet | https://nhs.uk/oral-glp1 | 2026] leaflet")[:2] == ("grey_literature", "medium")
    assert tagger.classify_chunk("[SOURCE web | Fingertips | https://fingertips.phe.org.uk/x | 2024] 34%")[:2] == ("official_statistic", "high")
    assert tagger.classify_chunk("[SOURCE synthetic | model-generated research paper — a prior, NOT evidence] x")[:2] == ("model_inference", "low")
    prov, trust, ref, body = tagger.classify_chunk("[Sandra Holroyd | Retired cleaner]: I waited 3 weeks for a GP")
    assert (prov, trust, ref, body) == ("model_inference", "low", "debate: Sandra Holroyd", "I waited 3 weeks for a GP")


def test_tag_batch_keeps_only_vocabulary(monkeypatch):
    async def fake_analyze(schema, system, user, **kw):
        assert "geography: England, North West, Blackpool, Oxford" in system and "roles: GP, Community pharmacist, patient, public" in system
        return {"units": [
            {"index": 0, "geography": ["Blackpool", "Atlantis"], "roles": ["GP", "wizard"], "channels": ["Local press"], "conditions": ["Obesity"], "stages": [], "segments": [], "register": "professional", "date": "March 2024"},
            {"index": 5, "geography": [], "roles": [], "channels": [], "conditions": [], "stages": [], "segments": [], "register": "lay", "date": ""},
        ]}
    monkeypatch.setattr(tagger, "analyze", fake_analyze)
    out = asyncio.run(tagger.tag_batch(["a", "b"], profiles.nodes_by_class(ONTO), session_id="s", model=None))
    assert out[0]["geography"] == ["Blackpool"] and out[0]["role"] == ["GP"] and out[0]["time"] == "2024"
    assert out[1] == {"register": "lay", "geography": [], "role": [], "channel": [], "condition": [], "stage": [], "segment": []}


def test_validate_rules_rejects_bad_shapes():
    with pytest.raises(ValueError):
        registry.validate_rules([{"dimension": "colour", "effect": "deny"}])
    with pytest.raises(ValueError):
        registry.validate_rules([{"dimension": "role", "effect": "explode"}])
    assert registry.validate_rules([{"dimension": "role", "effect": "deny", "when": ["GP"]}])[0]["when"] == ["GP"]


# ── HTTP ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.core.database as dbm
    from app.core.config import get_settings
    import app.models.report, app.models.preset, app.models.kg, app.models.population, app.models.scoping  # noqa: F401
    from app.services.knowledge_graph import lightrag_service
    from app.services.scoping import service

    monkeypatch.setattr(get_settings(), "app_supabase_url", "")
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/scoping.db")
    Session = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(dbm, "engine", eng)
    monkeypatch.setattr(dbm, "AsyncSessionLocal", Session)
    monkeypatch.setattr(dbm, "_sqlite", True)
    lightrag_service._kg_cache.clear()
    service._bundles.clear()

    async def fake_analyze(schema, system, user, **kw):
        # tag by keyword so the test is deterministic
        out = []
        for line in user.splitlines():
            if not line[:1].isdigit():
                continue
            k, body = line.split(". ", 1)
            b = body.lower()
            out.append({"index": int(k),
                        "geography": [g for g in ("Blackpool", "Oxford", "North West") if g.lower() in b],
                        "roles": (["GP"] if "audit" in b else ["public"]),
                        "channels": (["Local press"] if "gazette" in b or "press" in b else []),
                        "conditions": ["Obesity"] if "obesity" in b else [], "stages": [], "segments": [],
                        "register": "technical" if "audit" in b else "lay", "date": "2026" if "2026" in b else ""})
        return {"units": out}

    monkeypatch.setattr(tagger, "analyze", fake_analyze)

    async def _get_db():
        async with Session() as s:
            yield s

    from fastapi.testclient import TestClient
    from app.main import app
    app.dependency_overrides[dbm.get_db] = _get_db
    with TestClient(app) as client:
        yield client, Session
    app.dependency_overrides.clear()


def test_http_scoping_round_trip(api_client):
    client, Session = api_client
    from app.models.agent import SpawnedAgent, AgentStance
    from app.services.knowledge_graph import ontology as onto_svc
    from app.services.knowledge_graph import lightrag_service
    from app.services.scoping import service

    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "Oral GLP-1 uptake in Blackpool", "auto_research": False}).json()["id"]

    # untagged: state says so, preview is empty, tagging an empty graph is a 400
    assert client.get(f"/api/v1/sessions/{sid}/scoping").json()["tagged"] is False
    assert client.post(f"/api/v1/sessions/{sid}/scoping/tag").status_code == 400

    chunks = [
        "[SOURCE web | Blackpool Gazette | https://blackpoolgazette.co.uk/a | 2026] Gazette: GP access in Blackpool is the first barrier for obesity patients.",
        "[SOURCE web | Clinical audit | https://x.nhs.uk/audit | 2026] Audit: 41% discontinuation at 6 months in Blackpool for obesity therapy.",
        "[SOURCE social reddit | r/Oxford | https://reddit.com/x | 2026 | 30] Oxford press: people say Oxford gets the drug on the NHS.",
    ]
    entities = ["Blackpool", "Oxford", "North West", "GP", "Obesity", "Local press"]
    asyncio.run(lightrag_service._save_kg(sid, {"entities": entities, "relations": [], "chunks": chunks}))
    onto = {**ONTO, "entity_count": len(entities)}
    asyncio.run(onto_svc.save(sid, onto))

    async def seed_agents():
        async with Session() as db:
            db.add(SpawnedAgent(id="pat", session_id=sid, name="Sandra", age=58, role="Retired cleaner living with obesity", background="b", stance=AgentStance.DIRECT,
                                correlation="c", personality=[], debate_style="d", humanity=65, demographics={"region": "Blackpool"}))
            db.add(SpawnedAgent(id="gp", session_id=sid, name="Dr Nandakumar", age=44, role="GP partner", background="b", stance=AgentStance.DIRECT,
                                correlation="c", personality=[], debate_style="d", humanity=5, demographics={"region": "Blackpool"}))
            await db.commit()
    asyncio.run(seed_agents())

    r = client.post(f"/api/v1/sessions/{sid}/scoping/tag")
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["tagged"] and st["unit_count"] == 3 and st["policy"]["version"] == 1 and st["stale"] is False
    assert st["counts"]["provenance"] == {"grey_literature": 2, "social_signal": 1}   # an nhs.uk audit page is grey literature, not a statistic
    assert st["counts"]["geography"]["Blackpool"] == 2

    # the lay Blackpool patient: sees the Gazette story, not the technical audit, not Oxford
    pv = client.get(f"/api/v1/sessions/{sid}/scoping/preview", params={"agent_id": "pat"}).json()
    assert pv["profile"]["values"]["register"] == "lay" and pv["profile"]["values"]["geography"] == ["Blackpool"]
    assert [v["unit"]["text"][:8] for v in pv["visible"]] == ["Gazette:"]
    assert pv["visible"][0]["route"] == "via Local press"
    hidden = {h["unit"]["text"][:6]: [f[0] for f in h["failed"]] for h in pv["hidden"]}
    assert set(hidden["Audit:"]) == {"role", "register"} and hidden["Oxford"] == ["geography"]

    # the GP: sees the audit, still not Oxford
    gp = client.get(f"/api/v1/sessions/{sid}/scoping/preview", params={"agent_id": "gp"}).json()
    assert {v["unit"]["text"][:6] for v in gp["visible"]} == {"Gazett", "Audit:"}

    # a policy rule opens the public layer across places: anything on a channel the twin uses is allowed in
    r = client.put(f"/api/v1/sessions/{sid}/scoping/policy", json={"rules": [
        {"dimension": "channel", "when": "own", "effect": "allow", "override": ["geography"], "note": "public layer"},
        {"dimension": "provenance", "when": ["social_signal"], "effect": "route", "route": "from people talking about it online"},
    ], "note": "public layer"})
    assert r.status_code == 200 and r.json()["version"] == 2
    pv = client.get(f"/api/v1/sessions/{sid}/scoping/preview", params={"agent_id": "pat"}).json()
    assert {v["unit"]["text"][:6] for v in pv["visible"]} == {"Gazett", "Oxford"}
    assert next(v for v in pv["visible"] if v["unit"]["text"].startswith("Oxford"))["route"] == "from people talking about it online"
    assert client.put(f"/api/v1/sessions/{sid}/scoping/policy", json={"rules": [{"dimension": "nope", "effect": "deny"}]}).status_code == 400

    # an exposure override moves the patient to Oxford; the Gazette story is now the foreign one
    r = client.put(f"/api/v1/sessions/{sid}/scoping/agents/pat/exposure", json={"exposure": {"geography": ["Oxford"]}})
    assert r.status_code == 200
    pv = client.get(f"/api/v1/sessions/{sid}/scoping/preview", params={"agent_id": "pat"}).json()
    assert pv["profile"]["values"]["geography"] == ["Oxford"] and pv["profile"]["basis"]["geography"].startswith("set on the agent")

    # the block agents get, and the retrieval log behind it
    async def block():
        async with Session() as db:
            agent = await db.get(SpawnedAgent, "gp")
        text = await service.context_for_agent(sid, agent, "Oral GLP-1 uptake in Blackpool", purpose="post")
        await asyncio.sleep(0.05)
        return text
    text = asyncio.run(block())
    assert text.startswith("Where you know each thing from") and "Audit:" in text
    log = client.get(f"/api/v1/sessions/{sid}/scoping/retrievals", params={"agent_id": "gp"}).json()["retrievals"]
    assert log and log[0]["purpose"] == "post" and log[0]["policy_version"] == 2 and len(log[0]["unit_ids"]) == 3  # v2 opened the public layer, so the GP also sees Oxford

    # the graph grew → stale
    asyncio.run(lightrag_service._save_kg(sid, {"entities": entities, "relations": [], "chunks": chunks + ["[SOURCE web | x | u | 2026] more"]}))
    assert client.get(f"/api/v1/sessions/{sid}/scoping").json()["stale"] is True
