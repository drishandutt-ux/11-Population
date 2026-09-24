"""Archetypes (brief L3-02): twin = template + sampled attributes + local context; the model
writes texture only.

Run:  cd backend && pytest tests/archetypes_test.py -q
"""
import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.agents import agent_factory  # noqa: E402
from app.services.agents import archetypes as ar  # noqa: E402
from app.services.agents.agent_builder import DIAL_KEYS, complete_dials  # noqa: E402


def _full(v=5):
    return {g: {k: v for k in keys} for g, keys in DIAL_KEYS.items()}


ANN = {"id": "a1", "name": "Dr Ann Okafor", "role": "GP partner", "profile": {
    "name": "Dr Ann Okafor", "role": "GP partner", "background": "Runs a list in Blackpool.", "stance": "direct", "humanity": 20,
    "personality": ["blunt", "tired"], "debate_style": "Patient story first.", "correlation": "Prescribes weekly.",
    "demographics": {"region": "Blackpool, UK", "occupation": "GP partner"},
    "character": {"decision_rules": "Guideline first, then formulary.", "failure_modes": "Trusts the rep."},
    "dials": _full(4),
}}
BOLA = {"id": "a2", "name": "Bola Adeyemi", "role": "Community pharmacist", "profile": {"role": "Community pharmacist", "dials": _full(6), "humanity": 60, "character": {}}}

SEG_GP = {"id": "s1", "name": "Coastal GPs", "description": "Family doctors in deprived seaside towns", "stance": "direct", "count": 4,
          "demographics": {"age_min": 35, "age_max": 60, "gender_female_pct": 50, "regions": ["Blackpool", "Grimsby"], "income_band": "middle", "education": "degree", "occupations": ["GP", "salaried doctor"]},
          "sentiment": {"mood": "against"}, "arguments": ["It is rationing"], "humanity_hint": "reactive", "frame_values": {"place": "North West"}}
SEG_PUBLIC = {"id": "s2", "name": "Working-age residents", "description": "People who live in the towns", "stance": "neutral", "count": 3,
              "demographics": {"age_min": 25, "age_max": 55, "gender_female_pct": 67, "regions": ["Grimsby"]}}

FRAME = {"dimensions": [{"key": "place", "label": "Place", "attribute": "region"}, {"key": "age", "label": "Age", "attribute": "age"}],
         "targets": {"place": {"status": "found", "categories": [{"label": "North West", "share_pct": 60}, {"label": "Yorkshire", "share_pct": 40}]},
                     "age": {"status": "found", "categories": [{"label": "35-44", "share_pct": 50}, {"label": "45-64", "share_pct": 50}]}}}


# ── matching ─────────────────────────────────────────────────────────────────

def test_segment_matches_the_archetype_with_the_same_job_and_synonyms_count():
    assert ar.match_archetype(SEG_GP, [BOLA, ANN])["id"] == "a1"          # "GP" / "doctor" both map to gp
    assert ar.match_archetype(SEG_PUBLIC, [ANN, BOLA]) is None             # nobody authored a resident
    seg = {"name": "High-street pharmacists", "description": "", "demographics": {"occupations": []}}
    assert ar.match_archetype(seg, [ANN, BOLA])["id"] == "a2"


def test_assign_keeps_a_manual_choice():
    segs = [dict(SEG_GP, archetype_id="", archetype_name="", archetype_manual=True), dict(SEG_PUBLIC)]
    ar.assign_archetypes(segs, [ANN])
    assert segs[0]["archetype_id"] == "" and segs[1]["archetype_id"] == ""
    segs = [dict(SEG_GP)]
    ar.assign_archetypes(segs, [ANN])
    assert segs[0]["archetype_id"] == "a1" and segs[0]["archetype_name"] == "Dr Ann Okafor"


# ── sampling ─────────────────────────────────────────────────────────────────

def test_attributes_are_drawn_before_the_model_and_honour_the_segment():
    slots = ar.sample_attributes(SEG_GP, FRAME, 40)
    assert len(slots) == 40 and [s["slot"] for s in slots] == list(range(1, 41))
    assert all(35 <= s["age"] <= 60 for s in slots)
    assert sum(1 for s in slots if s["gender"] == "female") == 20
    assert {s["region"] for s in slots} == {"Blackpool", "Grimsby"}
    places = [s["frame"]["place"] for s in slots]
    assert places.count("North West") >= 28          # the segment's own cell most of the time, the rest from the shares
    assert all(s["frame"]["age"] in ("35-44", "45-64") for s in slots)
    assert all((35 <= s["age"] <= 44) == (s["frame"]["age"] == "35-44") for s in slots)  # the age follows the drawn age cell
    assert ar.sample_attributes(SEG_GP, FRAME, 40) == slots  # deterministic per segment


def test_sampling_without_a_frame_still_gives_facts():
    slots = ar.sample_attributes(SEG_PUBLIC, None, 3)
    assert [s["gender"] for s in slots].count("female") == 2 and all(s["region"] == "Grimsby" for s in slots) and all(s["frame"] == {} for s in slots)


# ── enforcement ──────────────────────────────────────────────────────────────

def test_enforce_keeps_the_facts_the_rules_and_bounds_the_drift():
    slot = {"slot": 1, "age": 51, "gender": "female", "region": "Grimsby", "income_band": "low", "education": "degree", "frame": {"place": "Yorkshire"}}
    written = {"slot": 1, "name": "Dr Helen Marsh", "age": 30, "region": "Leeds", "background": "b", "humanity": 90,
               "dials": {"sentiment": {"anger": 10, "joy": 0}, "friction": {"money_pain": 9}}, "personality": []}
    d = ar.enforce_archetype(ANN, slot, written)
    assert d["age"] == 51 and d["region"] == "Grimsby" and d["income_band"] == "low" and d["frame"] == {"place": "Yorkshire"}
    assert d["humanity"] == 30                                    # 20 + HUMANITY_DRIFT
    assert d["dials"]["sentiment"]["anger"] == 6 and d["dials"]["sentiment"]["joy"] == 2   # 4 ± 2
    assert d["dials"]["friction"]["money_pain"] == 6 and d["dials"]["trust"]["authority"] == 4  # unmentioned → the prior
    assert complete_dials(d["dials"])
    assert d["character"]["decision_rules"] == "Guideline first, then formulary." and d["character"]["archetype"] == {"id": "a1", "name": "Dr Ann Okafor"}
    assert d["personality"] == ["blunt", "tired"] and d["role"] == "GP partner" and d["_cast"] is True


def test_pair_slots_by_number_then_by_order():
    slots = [{"slot": 1}, {"slot": 2}, {"slot": 3}]
    pairs = ar.pair_slots(slots, [{"slot": 2, "name": "B"}, {"name": "X"}, {"slot": "1", "name": "A"}])
    assert [(s["slot"], d["name"]) for s, d in pairs] == [(1, "A"), (2, "B"), (3, "X")]


def test_a_batch_numbered_from_one_again_is_not_lost():
    """The second batch of a 20-persona segment asks for slots 11-20; a model that counts 1-10
    again must still fill them (seen in the stub run: half the segment vanished)."""
    slots = [{"slot": 11}, {"slot": 12}]
    pairs = ar.pair_slots(slots, [{"slot": 1, "name": "A"}, {"slot": 2, "name": "B"}])
    assert [(s["slot"], d["name"]) for s, d in pairs] == [(11, "A"), (12, "B")]


def test_prompt_states_the_rules_the_facts_and_texture_only():
    slots = ar.sample_attributes(SEG_GP, FRAME, 2)
    text = ar.cast_prompt("GLP-1 on the NHS?", SEG_GP, ANN, slots, {"Blackpool": "KNOWLEDGE GRAPH ENTITIES: Blackpool deprivation"}, "", "")
    assert "Guideline first, then formulary." in text and "TEXTURE ONLY" in text and "SLOT 2:" in text
    assert "frame cells: place = " in text and "Blackpool deprivation" in text


# ── the build: cast segments and invented segments side by side ──────────────

def test_generate_from_plan_casts_from_the_archetype(monkeypatch):
    calls = []

    async def fake_rag(session_id):
        return "rag"

    async def fake_query(rag, q, mode="hybrid"):
        return "summary"

    async def fake_create(client, *, session_id=None, label="", **kw):
        prompt = kw["messages"][0]["content"]
        calls.append((label, prompt))
        import json, re
        if label == "spawn:cast":
            n = int(re.search(r"Cast (\d+) personas", prompt).group(1))
            out = [{"slot": k + 1, "name": f"Cast {k + 1}", "role": "GP partner", "background": "b", "age": 99, "humanity": 95,
                    "dials": {"sentiment": {"anger": 10}}, "personality": ["blunt"], "debate_style": "d", "geo_behavior": "g", "correlation": "c"} for k in range(n)]
        else:
            n = int(re.search(r"Create (\d+) distinct personas", prompt).group(1))
            out = [{"name": f"Res {k + 1}", "age": 30 + k, "role": f"Job {k}", "background": "b", "stance": "neutral", "humanity": 55, "dials": _full(5),
                    "region": "Grimsby", "gender": "female", "income_band": "low", "education": "secondary", "occupation": f"Job {k}"} for k in range(n)]

        class R:  # noqa: D401
            content = [type("T", (), {"text": json.dumps(out)})()]
        return R()

    monkeypatch.setattr(agent_factory, "get_lightrag", fake_rag)
    monkeypatch.setattr(agent_factory, "query_rag", fake_query)
    monkeypatch.setattr(agent_factory, "tracked_messages_create", fake_create)
    monkeypatch.setattr(ar, "local_context", lambda *a, **k: "")

    segs = [dict(SEG_GP, archetype_id="a1", archetype_name="Dr Ann Okafor"), dict(SEG_PUBLIC)]
    profiles = asyncio.new_event_loop().run_until_complete(
        agent_factory.generate_agents_from_plan("s", "GLP-1?", segs, {"archetypes": {"a1": ANN}, "frame": FRAME}, mode="fast"))
    cast = [p for p in profiles if p.segment == "Coastal GPs"]
    free = [p for p in profiles if p.segment == "Working-age residents"]
    assert len(cast) == 4 and len(free) == 3
    assert {c for c, _ in calls} == {"spawn:cast", "spawn:plan"}
    for p in cast:
        assert 35 <= p.age <= 60                       # the drawn facts won over the model's 99
        assert p.humanity == 30                        # bounded to the archetype's 20 + 10, not the segment's reactive band
        assert p.dials["sentiment"]["anger"] == 6 and p.dials["trust"]["authority"] == 4
        assert p.character["decision_rules"] == "Guideline first, then formulary." and p.character["archetype"]["name"] == "Dr Ann Okafor"
        assert p.demographics["frame"]["place"] in ("North West", "Yorkshire") and p.stance == "direct"
    assert len({p.name for p in cast}) == 4            # four GP partners of similar age are siblings, not clones
    assert all(p.character is None for p in free)


# ── HTTP: author with as_archetype, list, pick on a segment, delete ───────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.core.database as dbm
    from app.core.config import get_settings
    import app.models.report, app.models.preset, app.models.kg, app.models.population, app.models.archetype  # noqa: F401
    from app.services.population import builder

    monkeypatch.setattr(get_settings(), "app_supabase_url", "")
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/arch.db")
    Session = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(dbm, "engine", eng)
    monkeypatch.setattr(dbm, "AsyncSessionLocal", Session)
    monkeypatch.setattr(dbm, "_sqlite", True)

    async def fake_analyze(schema, system, user, **kw):
        props = schema.get("properties", {})
        if "target_population" in props:
            return {"topic": "t", "decision": "d", "geography": "UK", "target_population": "coastal towns", "population_kind": "citizens", "segments_hinted": [],
                    "demographic_signals": [], "sentiment_signals": [], "gaps": [], "confidence": 70, "dials": {}}
        if "questions" in props:
            return {"questions": [], "note": "ok"}
        if "segments" in props:
            return {"segments": [
                {"id": "s1", "name": "Coastal GPs", "share_pct": 50, "stance": "direct", "description": "family doctors", "age_min": 35, "age_max": 60, "gender_female_pct": 50,
                 "regions": ["Blackpool"], "income_band": "middle", "education": "degree", "occupations": ["GP"], "mood": "against", "temperature": 6, "top_emotions": [], "arguments": [], "evidence": [], "rationale": "r", "humanity_hint": "tempered"},
                {"id": "s2", "name": "Residents", "share_pct": 50, "stance": "neutral", "description": "people", "age_min": 25, "age_max": 55, "gender_female_pct": 50,
                 "regions": ["Blackpool"], "income_band": "low", "education": "secondary", "occupations": ["various"], "mood": "mixed", "temperature": 4, "top_emotions": [], "arguments": [], "evidence": [], "rationale": "r", "humanity_hint": "balanced"},
            ], "rationale": "two", "assumptions": [], "evidence_coverage": "c"}
        return {}

    monkeypatch.setattr(builder, "analyze", fake_analyze)

    async def fake_pick(*a, **k):
        return []

    monkeypatch.setattr(builder.facets_mod, "pick_facets", fake_pick)

    async def fake_ab(schema, system, user, **kw):
        return {"dials": _full(4), "humanity": 20, "reading": "r"}

    from app.services.agents import agent_builder as ab
    monkeypatch.setattr(ab, "analyze", fake_ab)

    async def _get_db():
        async with Session() as s:
            yield s

    from fastapi.testclient import TestClient
    from app.main import app
    app.dependency_overrides[dbm.get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _wait(client, sid, until, timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        b = client.get(f"/api/v1/sessions/{sid}/population/builds/latest").json()["build"]
        if b and until(b):
            return b
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_archetype_round_trip(client):
    draft = {"name": "Dr Ann Okafor", "role": "GP partner", "background": "Runs a list in Blackpool.", "stance": "direct", "humanity": 20,
             "demographics": {"region": "Blackpool, UK"}, "character": {"decision_rules": "Guideline first."}, "dials": _full(4)}
    r = client.post("/api/v1/presets/custom", json={"name": "GPs", "agents": [draft], "as_archetype": True})
    assert r.status_code == 200, r.text
    arches = client.get("/api/v1/archetypes").json()
    assert len(arches) == 1 and arches[0]["name"] == "Dr Ann Okafor" and "Guideline first." in arches[0]["summary"]
    aid = arches[0]["id"]

    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "GLP-1 on the NHS?", "auto_research": False}).json()["id"]
    r = client.post(f"/api/v1/sessions/{sid}/population/builds", json={"mode": "fast", "count": 10, "constraints": {"skip_questions": True}, "sources": {"quant": False, "quant_sources": []}})
    assert r.status_code == 200, r.text
    b = _wait(client, sid, lambda b: b["status"] == "awaiting_review")
    segs = {s["name"]: s for s in b["plan"]["segments"]}
    assert segs["Coastal GPs"]["archetype_id"] == aid and segs["Coastal GPs"]["archetype_name"] == "Dr Ann Okafor"
    assert segs["Residents"]["archetype_id"] == ""
    assert any("Cast from archetypes: 1 of 2" in e["message"] for e in b["log"])

    # the analyst points the residents at Ann too, then clears the GPs
    r = client.post(f"/api/v1/sessions/{sid}/population/builds/{b['id']}/segments/s2", json={"decision": "edit", "edits": {"archetype_id": aid}})
    assert r.status_code == 200
    r = client.post(f"/api/v1/sessions/{sid}/population/builds/{b['id']}/segments/s1", json={"decision": "edit", "edits": {"archetype_id": ""}})
    segs = {s["name"]: s for s in r.json()["plan"]["segments"]}
    assert segs["Residents"]["archetype_id"] == aid and segs["Coastal GPs"]["archetype_id"] == "" and segs["Coastal GPs"]["archetype_manual"] is True

    assert client.delete(f"/api/v1/archetypes/{aid}").status_code == 204
    assert client.get("/api/v1/archetypes").json() == []
