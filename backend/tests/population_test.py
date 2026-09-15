"""Population Studio: the parts that decide who ends up in the roster.

Run:  cd backend && pytest tests/population_test.py -q
No network. Covers share/count normalisation (the plan's arithmetic), the model→plan shape,
the dials as prompt text, the per-segment persona prompt, the quant fact chunk, and the HTTP
surface with the model stubbed (start → questions → answer → plan → reject/accept → approve).
"""
import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.population import builder, sources  # noqa: E402
from app.services.agents import agent_factory  # noqa: E402


def _seg(id, share, decision="proposed", **kw):
    d = {"id": id, "name": f"Segment {id}", "share_pct": share, "stance": "neutral", "decision": decision,
         "demographics": {"age_min": 20, "age_max": 60, "gender_female_pct": 50}, "sentiment": {"mood": "mixed", "temperature": 5, "top_emotions": []}}
    d.update(kw)
    return d


# ── normalisation ─────────────────────────────────────────────────────────────

def test_counts_sum_to_total_and_shares_to_100():
    out = builder.normalise_segments([_seg("a", 50), _seg("b", 30), _seg("c", 20)], 33)
    assert sum(s["count"] for s in out) == 33
    assert round(sum(s["share_pct"] for s in out)) == 100
    assert [s["count"] for s in out] == [17, 10, 6] or sum(s["count"] for s in out) == 33


def test_rejected_segment_gets_nothing_and_the_rest_absorb_its_share():
    out = builder.normalise_segments([_seg("a", 50), _seg("b", 30, decision="rejected"), _seg("c", 20)], 40)
    by = {s["id"]: s for s in out}
    assert by["b"]["count"] == 0 and by["b"]["share_pct"] == 30  # the rejected share is left as the model wrote it
    assert by["a"]["count"] + by["c"]["count"] == 40
    assert round(by["a"]["share_pct"] + by["c"]["share_pct"]) == 100
    assert by["a"]["share_pct"] > by["c"]["share_pct"]


def test_rejecting_keeps_the_slot_share_for_its_replacement():
    """Without this, the neighbours absorb the rejected share and the replacement's own share
    is then squeezed on top of a 100% plan (seen as 16.7% for a 20% slot)."""
    out = builder.normalise_segments([_seg("a", 50), _seg("b", 30, decision="rejected"), _seg("c", 20)], 40, rescale_shares=False)
    by = {s["id"]: s for s in out}
    assert (by["a"]["share_pct"], by["c"]["share_pct"]) == (50, 20)
    assert by["a"]["count"] + by["c"]["count"] == 40 and by["a"]["count"] > by["c"]["count"]
    replaced = builder.normalise_segments([by["a"], dict(_seg("b", 30)), by["c"]], 40)
    assert [s["share_pct"] for s in replaced] == [50, 30, 20]


def test_every_kept_segment_gets_at_least_one_agent_when_possible():
    out = builder.normalise_segments([_seg("a", 96), _seg("b", 2), _seg("c", 2)], 10)
    assert all(s["count"] >= 1 for s in out) and sum(s["count"] for s in out) == 10


def test_ages_are_clamped_to_the_population_dial():
    out = builder.normalise_segments([_seg("a", 100, demographics={"age_min": 12, "age_max": 90, "gender_female_pct": 140})], 5,
                                     constraints={"demographics": {"age_min": 25, "age_max": 45}})
    d = out[0]["demographics"]
    assert (d["age_min"], d["age_max"]) == (25, 45)
    assert d["gender_female_pct"] == 100


def test_zero_shares_fall_back_to_an_even_split():
    out = builder.normalise_segments([_seg("a", 0), _seg("b", 0)], 10)
    assert [s["count"] for s in out] == [5, 5]


# ── shapes & prompts ──────────────────────────────────────────────────────────

def test_segment_from_model_nests_demographics_and_sentiment():
    m = {"id": "s1", "name": "Renters", "share_pct": 40, "stance": "direct", "description": "d", "age_min": 22, "age_max": 39,
         "gender_female_pct": 55, "regions": ["Leeds", ""], "income_band": "low", "education": "degree", "occupations": ["nurse"],
         "mood": "against", "temperature": 12, "top_emotions": ["anger"], "arguments": ["too dear"], "evidence": ["42% rent (ONS)"],
         "rationale": "because", "humanity_hint": "defensive"}
    seg = builder.segment_from_model(m)
    assert seg["demographics"]["regions"] == ["Leeds"]
    assert seg["sentiment"]["temperature"] == 10  # clamped
    assert seg["decision"] == "proposed" and seg["stance"] == "direct"
    assert builder.segment_from_model({"stance": "bogus"})["stance"] == "neutral"


def test_constraints_summary_only_states_moved_dials():
    quiet = builder.constraints_summary({"sentiment": {"follow_evidence": True, "temperature": 5}, "stance": {"direct": 33, "indirect": 33, "neutral": 34, "follow_plan": True}})
    assert "Population dials" not in quiet and "follow the evidence" in quiet
    loud = builder.constraints_summary({"demographics": {"age_min": 30, "age_max": 50, "regions": ["Wales"], "income": "low"},
                                        "sentiment": {"follow_evidence": False, "mood": {"for": 20, "against": 70, "mixed": 10}, "price_sensitivity": 9}})
    assert "ages 30-50" in loud and "Wales" in loud and "income: low" in loud
    assert "70% against" in loud and "price sensitivity 9/10" in loud


def test_plan_prompt_pins_the_segment_and_the_dials():
    seg = {"name": "Commuting parents", "description": "who", "stance": "direct", "share_pct": 40,
           "demographics": {"age_min": 28, "age_max": 45, "gender_female_pct": 60, "regions": ["Greater Manchester"], "income_band": "middle", "education": "mixed", "occupations": ["teacher"]},
           "sentiment": {"mood": "for", "temperature": 7, "top_emotions": ["hope", "anxiety"]}, "arguments": ["the bus never comes"], "evidence": ["61% aged 25-44 (ONS)"], "rationale": "r"}
    cons = {"demographics": {"regions": ["Greater Manchester"], "age_min": 25, "age_max": 50}, "sentiment": {"price_sensitivity": 8}, "humanity": 60}
    p = agent_factory._plan_prompt("Will they use a new tram line?", seg, 10, 4, 60, cons, "KG", "EVIDENCE", [{"name": "A B", "role": "x", "age": 30}])
    assert "Commuting parents" in p and "Ages: 28 to 45" in p and "roughly 60% women" in p
    assert "exactly 4 of the 10 personas are high-humanity" in p
    assert "Everyone lives in: Greater Manchester" in p and "price sensitivity: 8/10" in p
    assert '"stance": "direct"' in p and "ALREADY IN THIS POPULATION" in p and "A B" in p
    assert '"gender"' in p and '"region"' in p and "DIALS INSTRUCTIONS" in p


def test_profile_from_dict_keeps_demographics_and_segment():
    d = {"name": "Priya Nair", "age": 34, "gender": "female", "region": "Salford", "income_band": "middle", "education": "degree",
         "occupation": "nurse", "role": "NHS Nurse", "background": "b", "stance": "direct", "correlation": "c", "personality": ["warm"],
         "debate_style": "d", "humanity": 60, "dials": {"sentiment": {"hope": 8}}}
    p = agent_factory.profile_from_dict(d, "sess", "#fff", segment="Commuting parents")
    assert p.segment == "Commuting parents" and p.demographics["region"] == "Salford" and p.demographics["gender"] == "female"
    assert p.humanity == 60 and p.stance == "direct"
    assert agent_factory.profile_from_dict({"role": "no name"}, "s", "#fff") is None


def test_quant_chunk_and_prompt_carry_the_source():
    class E:
        session_id = "s"; source_ref = "https://ons.gov.uk/x"; author = "ons.gov.uk"; published_at = "2025-03-01"; title = "Cycling in England"
        full_text = None; text = "t"
        structured = {"source_label": "ONS", "facts": [{"statistic": "adults who cycle weekly", "value": "11%", "group": "adults 16+", "geography": "England", "year": "2024", "quote": "q"}], "demographic_signals": ["most are men"]}
    chunk = sources.quant_chunk(E())
    assert chunk.startswith("[SOURCE quant | ONS | https://ons.gov.uk/x | 2025-03-01]")
    assert "adults who cycle weekly: 11%" in chunk
    txt = sources.facts_for_prompt([E()])
    assert "QUANTITATIVE FACTS" in txt and "(ONS)" in txt and "most are men" in txt


def test_default_sources_follow_geography():
    assert "ons" in sources.default_sources("United Kingdom") and "census" in sources.default_sources("United States")
    assert "statista" in sources.default_sources("")


# ── HTTP surface with the model stubbed ───────────────────────────────────────

@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.core.database as dbm
    from app.core.config import get_settings
    import app.models.report, app.models.preset, app.models.kg, app.models.population  # noqa: F401

    monkeypatch.setattr(get_settings(), "app_supabase_url", "")
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/studio.db")
    Session = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(dbm, "engine", eng)
    monkeypatch.setattr(dbm, "AsyncSessionLocal", Session)
    monkeypatch.setattr(dbm, "_sqlite", True)

    calls: list[str] = []

    async def fake_analyze(schema, system, user, **kw):
        label = kw.get("label", "")
        calls.append(label)
        props = schema.get("properties", {})
        if "target_population" in props:
            return {"topic": "tram line", "decision": "use it", "geography": "United Kingdom", "target_population": "Greater Manchester residents",
                    "population_kind": "citizens", "segments_hinted": ["commuters", "retirees"], "demographic_signals": [{"attribute": "region", "value": "GM", "source": "query"}],
                    "sentiment_signals": ["mostly for"], "gaps": ["fares"], "confidence": 70}
        if "questions" in props:
            return {"questions": [{"id": "q1", "text": "Which boroughs?", "why": "changes the regions", "suggested": ["all ten", "Salford only"], "default": "all ten"}], "note": "can proceed"}
        if "segments" in props:
            return {"segments": [
                {"id": "s1", "name": "Commuters", "share_pct": 60, "stance": "direct", "description": "d", "age_min": 22, "age_max": 55, "gender_female_pct": 50, "regions": ["Manchester"],
                 "income_band": "middle", "education": "mixed", "occupations": ["clerk"], "mood": "for", "temperature": 6, "top_emotions": ["hope"], "arguments": ["a"], "evidence": ["e"], "rationale": "r", "humanity_hint": "tempered"},
                {"id": "s2", "name": "Retirees", "share_pct": 40, "stance": "neutral", "description": "d", "age_min": 65, "age_max": 85, "gender_female_pct": 55, "regions": ["Stockport"],
                 "income_band": "low", "education": "secondary", "occupations": ["retired"], "mood": "mixed", "temperature": 3, "top_emotions": ["nostalgia"], "arguments": ["b"], "evidence": [], "rationale": "r2", "humanity_hint": "balanced"},
            ], "rationale": "two groups", "assumptions": ["fares unknown"], "evidence_coverage": "half evidence"}
        if "humanity_hint" in props:  # single replacement segment
            return {"id": "x", "name": "Students", "share_pct": 40, "stance": "indirect", "description": "d", "age_min": 18, "age_max": 24, "gender_female_pct": 52, "regions": ["Fallowfield"],
                    "income_band": "low", "education": "some college", "occupations": ["student"], "mood": "for", "temperature": 5, "top_emotions": ["curiosity"], "arguments": [], "evidence": [], "rationale": "replaced", "humanity_hint": "reactive"}
        return {}

    monkeypatch.setattr(builder, "analyze", fake_analyze)

    async def fake_generate(session_id, query, segments, constraints, *, mode="fast", evidence_text="", on_progress=None):
        from app.services.agents.profiles import AgentProfile
        out = []
        for seg in segments:
            for k in range(int(seg["count"])):
                out.append(AgentProfile(id=f"{seg['id']}-{k}", session_id=session_id, name=f"{seg['name']} {k}", age=30 + k, role="r", background="b", stance=seg["stance"],
                                        correlation="c", personality=[], debate_style="d", dials={}, humanity=0, segment=seg["name"], demographics={"gender": "female", "region": "Manchester"}))
            if on_progress:
                await on_progress(seg["name"], int(seg["count"]), int(seg["count"]), len(out))
        return out

    monkeypatch.setattr("app.services.agents.agent_factory.generate_agents_from_plan", fake_generate)

    async def _get_db():
        async with Session() as s:
            yield s

    from fastapi.testclient import TestClient
    from app.main import app
    app.dependency_overrides[dbm.get_db] = _get_db
    with TestClient(app) as c:
        yield c, Session, calls
    app.dependency_overrides.clear()


def _wait(client, sid, until, timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        b = client.get(f"/api/v1/sessions/{sid}/population/builds/latest").json()["build"]
        if b and until(b):
            return b
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting; last status {b and b['status']}")


def test_http_studio_round_trip(api_client):
    client, Session, calls = api_client
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "Will Greater Manchester use a new tram line?", "auto_research": False}).json()["id"]

    # start → detect → clarify (waits for the analyst)
    r = client.post(f"/api/v1/sessions/{sid}/population/builds", json={"mode": "fast", "count": 20, "constraints": {"humanity": 50}, "sources": {"quant": False}})
    assert r.status_code == 200
    b = _wait(client, sid, lambda b: b["status"] == "clarifying")
    assert b["detected"]["geography"] == "United Kingdom"
    assert b["questions"][0]["text"] == "Which boroughs?"
    assert any(e["level"] == "question" for e in b["log"])
    assert "population_detect" in calls and "population_questions" in calls

    # a segment decision before the plan exists is refused
    assert client.post(f"/api/v1/sessions/{sid}/population/builds/{b['id']}/segments/s1", json={"decision": "accept"}).status_code == 409

    # answer → plan → awaiting_review with counts summing to the target
    r = client.post(f"/api/v1/sessions/{sid}/population/builds/{b['id']}/answers", json={"answers": {"q1": "Salford only"}})
    assert r.status_code == 200
    b = _wait(client, sid, lambda b: b["status"] == "awaiting_review")
    segs = b["plan"]["segments"]
    assert [s["count"] for s in segs] == [12, 8]
    assert b["questions"][0]["answer"] == "Salford only"
    assert any("You answered" in e["message"] for e in b["log"])

    # reject one with a reason → a replacement arrives in its slot; accept the other
    r = client.post(f"/api/v1/sessions/{sid}/population/builds/{b['id']}/segments/s2", json={"decision": "reject", "reason": "no retirees near Salford"})
    assert r.status_code == 200
    b = _wait(client, sid, lambda b: any(s.get("replaced") for s in b["plan"]["segments"]))
    new = next(s for s in b["plan"]["segments"] if s["id"] == "s2")
    assert new["name"] == "Students" and new["replaced"] == "Retirees" and new["decision"] == "proposed"
    assert sum(s["count"] for s in b["plan"]["segments"]) == 20
    assert any("no retirees near Salford" in (e.get("detail") or "") for e in b["log"])
    r = client.post(f"/api/v1/sessions/{sid}/population/builds/{b['id']}/segments/s1", json={"decision": "edit", "edits": {"share_pct": 75, "demographics": {"age_max": 40}}})
    s1 = next(s for s in r.json()["plan"]["segments"] if s["id"] == "s1")
    assert s1["decision"] == "edited" and s1["demographics"]["age_max"] == 40 and s1["count"] == 15

    # approve → agents are written from the kept segments, carrying segment + demographics
    r = client.post(f"/api/v1/sessions/{sid}/population/builds/{b['id']}/approve", json={"count": 20})
    assert r.status_code == 200 and r.json()["status"] == "spawning"
    b = _wait(client, sid, lambda b: b["status"] == "complete")
    agents = client.get(f"/api/v1/sessions/{sid}/agents").json()
    assert len(agents) == 20
    assert {a["segment"] for a in agents} == {"Commuters", "Students"}
    assert agents[0]["demographics"]["region"] == "Manchester"
    assert sum(1 for a in agents if a["segment"] == "Commuters") == 15
    assert client.get(f"/api/v1/sessions/{sid}").json()["agent_count"] == 20
    assert any("Population built: 20 agents" in e["message"] for e in b["log"])


def test_http_quant_search_requires_a_query(api_client):
    client, _, _ = api_client
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "q", "auto_research": False}).json()["id"]
    assert client.post(f"/api/v1/sessions/{sid}/population/quant-search", json={"query": "  ", "sources": ["ons"]}).status_code == 400
    cat = client.get("/api/v1/population/sources?geography=United%20Kingdom").json()
    assert "ons" in cat["default"] and any(s["key"] == "statista" for s in cat["sources"])


def test_facts_without_a_number_are_dropped():
    """Seen on prod: Statista's paywalled teaser gave '<redacted>' as the value."""
    kept = sources.usable_facts([
        {"statistic": "e-bike access, men", "value": "<redacted>"},
        {"statistic": "e-bike access, women", "value": "not shown"},
        {"statistic": "car club members", "value": "752,560"},
        {"statistic": "unaware of subscriptions", "value": "78%"},
        {"statistic": "blank", "value": ""},
        "junk",
    ])
    assert [f["value"] for f in kept] == ["752,560", "78%"]


def test_plan_generation_runs_segments_concurrently_and_tags_them(monkeypatch):
    """Segments are independent slices, so they must not queue behind each other: on prod a
    50-agent, 8-segment build took ~1.5 min per segment when they ran one at a time."""
    import time as _t
    from app.core.config import get_settings

    async def fake_rag(session_id):
        return session_id

    async def fake_query(rag, query, mode="hybrid"):
        return "kg"

    monkeypatch.setattr(agent_factory, "get_lightrag", fake_rag)
    monkeypatch.setattr(agent_factory, "query_rag", fake_query)
    monkeypatch.setattr(get_settings(), "spawn_concurrency", 8)
    calls = []

    class _Resp:
        def __init__(self, text): self.content = [type("B", (), {"text": text})()]

    async def fake_create(client, **kw):
        user = kw["messages"][0]["content"]
        seg = "A" if "Name: Seg A" in user else "B"
        n = int(user.split("Create ")[1].split(" ")[0])
        calls.append((seg, _t.monotonic()))
        await asyncio.sleep(0.2)
        import json as _j
        return _Resp(_j.dumps([{"name": f"{seg} person {k} {len(calls)}", "age": 30 + k, "role": f"{seg} role {k} batch {len(calls)}", "background": "b", "stance": "neutral",
                               "correlation": "c", "personality": [], "debate_style": "d", "humanity": 0, "gender": "female", "region": "Bristol", "dials": {}} for k in range(n)]))

    monkeypatch.setattr(agent_factory, "tracked_messages_create", fake_create)
    progress = []

    async def on_progress(name, done_seg, seg_count, done_total):
        progress.append((name, done_seg, seg_count))

    segs = [{"id": "a", "name": "Seg A", "count": 12, "stance": "direct", "demographics": {}, "sentiment": {}},
            {"id": "b", "name": "Seg B", "count": 5, "stance": "neutral", "demographics": {}, "sentiment": {}}]
    t0 = _t.monotonic()
    profiles = asyncio.new_event_loop().run_until_complete(
        agent_factory.generate_agents_from_plan("s", "q", segs, {"humanity": 50, "humanity_coverage": 60}, on_progress=on_progress))
    elapsed = _t.monotonic() - t0
    assert len(profiles) == 17
    assert sum(1 for p in profiles if p.segment == "Seg A") == 12 and all(p.stance == "direct" for p in profiles if p.segment == "Seg A")
    assert profiles[0].demographics["region"] == "Bristol"
    # Two segments' first batches overlap in time: three calls total, two rounds, not three.
    assert elapsed < 0.55, elapsed
    assert ("Seg A", 12, 12) in progress and ("Seg B", 5, 5) in progress
