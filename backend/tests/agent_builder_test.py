"""Agent Builder: hand-authored twins that join a lineup.

Run:  cd backend && pytest tests/agent_builder_test.py -q
The dial rules are pure; the HTTP round trip stubs the model.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.agents import agent_builder as ab  # noqa: E402
from app.services.agents.agent_builder import (  # noqa: E402
    DIAL_COUNT, DIAL_KEYS, AuthoredAgentError, clean_fixed_dials, complete_dials,
    merge_fixed_dials, normalise_authored_agent,
)


def _full(value=5):
    return {g: {k: value for k in keys} for g, keys in DIAL_KEYS.items()}


# ── dial rules ────────────────────────────────────────────────────────────────

def test_schema_has_the_112_dials():
    assert DIAL_COUNT == 112
    assert set(DIAL_KEYS) == {"sentiment", "motivation", "habit", "trust", "friction", "identity", "commercial", "product", "composite"}


def test_fixed_dials_keep_only_real_keys_and_clamp():
    fixed = clean_fixed_dials({"sentiment": {"joy": 14, "made_up": 3, "anger": None, "fear": ""}, "nope": {"x": 1}, "trust": "bad"})
    assert fixed == {"sentiment": {"joy": 10}}


def test_fixed_values_win_over_the_model_and_gaps_default_to_five():
    generated = _full(8)
    generated["sentiment"]["joy"] = 1
    del generated["composite"]["adoption_readiness"]
    merged = merge_fixed_dials(generated, {"sentiment": {"joy": 9}, "friction": {"money_pain": 0}})
    assert merged["sentiment"]["joy"] == 9
    assert merged["friction"]["money_pain"] == 0
    assert merged["sentiment"]["anger"] == 8
    assert merged["composite"]["adoption_readiness"] == 5
    assert complete_dials(merged)


# ── the draft → lineup profile ────────────────────────────────────────────────

def test_a_draft_needs_name_role_description_and_a_full_profile():
    with pytest.raises(AuthoredAgentError, match="name"):
        normalise_authored_agent({"role": "GP", "background": "x", "dials": _full()})
    with pytest.raises(AuthoredAgentError, match="job or role"):
        normalise_authored_agent({"name": "Ann", "background": "x", "dials": _full()})
    with pytest.raises(AuthoredAgentError, match="description"):
        normalise_authored_agent({"name": "Ann", "role": "GP", "dials": _full()})
    with pytest.raises(AuthoredAgentError, match="incomplete"):
        normalise_authored_agent({"name": "Ann", "role": "GP", "background": "x", "dials": {"sentiment": {"joy": 3}}})


def test_a_complete_draft_becomes_a_lineup_profile_with_character_and_demographics():
    prof = normalise_authored_agent({
        "name": "  Dr Ann Okafor ", "age": "47", "role": "GP partner", "background": "Runs a list in Blackpool.",
        "stance": "weird", "personality": "blunt, tired, loyal", "humanity": 130,
        "demographics": {"gender": "woman", "region": "Blackpool, UK", "income_band": "middle", "geo_behavior": "You see the deprivation daily.", "junk": "x"},
        "character": {"decision_rules": "Guideline first, then the formulary.", "behaviour": "", "failure_modes": "Defers to the prescribing lead."},
        "dials": _full(7),
    })
    assert prof["name"] == "Dr Ann Okafor" and prof["age"] == 47 and prof["stance"] == "neutral"
    assert prof["personality"] == ["blunt", "tired", "loyal"]
    assert prof["humanity"] == 100
    assert prof["demographics"]["region"] == "Blackpool, UK" and "junk" not in prof["demographics"]
    assert prof["demographics"]["occupation"] == "GP partner"
    assert prof["character"] == {"decision_rules": "Guideline first, then the formulary.", "failure_modes": "Defers to the prescribing lead."}
    assert prof["authored"] is True
    assert 0.3 <= prof["energy"] <= 1.0 and prof["avatar_color"].startswith("#")
    assert complete_dials(prof["dials"])


def test_describe_draft_lists_only_what_was_written():
    text = ab.describe_draft({"name": "Ann", "role": "GP", "humanity": 20, "character": {"decision_rules": "Guideline first."}, "demographics": {"region": "Leeds"}})
    assert "Name: Ann" in text and "Lives in: Leeds" in text and "How they decide: Guideline first." in text
    assert "Expert" not in text  # humanity only reaches the model when the analyst fixed it


def test_build_profile_keeps_fixed_dials_and_fixed_humanity(monkeypatch):
    import asyncio
    seen = {}

    async def fake_analyze(schema, system, user, **kw):
        seen["user"] = user
        return {"dials": _full(2), "humanity": 80, "reading": "Cold and tired."}

    monkeypatch.setattr(ab, "analyze", fake_analyze)
    out = asyncio.new_event_loop().run_until_complete(ab.build_profile("s1", "e-bike subsidies", {
        "name": "Ann", "role": "GP", "background": "x", "humanity": 15, "humanity_fixed": True,
        "dials": {"sentiment": {"anger": 9}},
    }))
    assert out["dials"]["sentiment"]["anger"] == 9 and out["dials"]["sentiment"]["joy"] == 2
    assert out["humanity"] == 15 and out["reading"] == "Cold and tired."
    assert "sentiment.anger = 9" in seen["user"] and "e-bike subsidies" in seen["user"]


# ── the persona prompt carries the character ─────────────────────────────────

def test_runner_injects_the_authored_character():
    from types import SimpleNamespace
    from app.services.agents.agent_runner import _character_block

    agent = SimpleNamespace(character={"decision_rules": "Guideline first.", "vocabulary": "", "failure_modes": "Trusts the rep."})
    block = _character_block(agent)
    assert "HOW YOU DECIDE:\nGuideline first." in block and "WHERE YOU GO WRONG:\nTrusts the rep." in block
    assert "HOW YOU TALK" not in block
    assert _character_block(SimpleNamespace(character=None)) == ""


# ── HTTP: new lineup, add to lineup, load into a session ─────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.core.database as dbm
    from app.core.config import get_settings
    import app.models.report, app.models.preset, app.models.kg, app.models.population  # noqa: F401

    monkeypatch.setattr(get_settings(), "app_supabase_url", "")
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/builder.db")
    Session = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(dbm, "engine", eng)
    monkeypatch.setattr(dbm, "AsyncSessionLocal", Session)
    monkeypatch.setattr(dbm, "_sqlite", True)

    async def fake_analyze(schema, system, user, **kw):
        return {"dials": _full(6), "humanity": 40, "reading": "Warm but wary."}

    monkeypatch.setattr(ab, "analyze", fake_analyze)

    async def _get_db():
        async with Session() as s:
            yield s

    from fastapi.testclient import TestClient
    from app.main import app
    app.dependency_overrides[dbm.get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _draft(name="Ann Okafor", dials=None):
    return {"name": name, "age": 47, "role": "GP partner", "background": "Runs a list in Blackpool.", "stance": "direct",
            "demographics": {"region": "Blackpool, UK"}, "character": {"decision_rules": "Guideline first."}, "dials": dials or _full(7), "humanity": 20}


def test_lineup_round_trip(client):
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "Should GPs prescribe e-bikes?", "auto_research": False}).json()["id"]

    # Build sentiment profile: fixed dial kept, the rest from the model
    r = client.post(f"/api/v1/sessions/{sid}/agent-builder/profile", json={"agent": {"name": "Ann", "role": "GP", "dials": {"friction": {"money_pain": 1}}}})
    assert r.status_code == 200, r.text
    prof = r.json()
    assert prof["dials"]["friction"]["money_pain"] == 1 and prof["dials"]["sentiment"]["joy"] == 6 and prof["humanity"] == 40

    # An incomplete draft cannot be saved
    r = client.post("/api/v1/presets/custom", json={"name": "Hand-built GPs", "agents": [_draft(dials={"sentiment": {"joy": 1}})]})
    assert r.status_code == 400 and "incomplete" in r.text

    # New lineup
    r = client.post("/api/v1/presets/custom", json={"name": "Hand-built GPs", "agents": [_draft()]})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert r.json()["agent_count"] == 1

    # Add to it; a repeated name is refused
    r = client.post(f"/api/v1/presets/{pid}/agents", json={"agents": [_draft("Ann Okafor")]})
    assert r.status_code == 409
    r = client.post(f"/api/v1/presets/{pid}/agents", json={"agents": [_draft("Bola Adeyemi")]})
    assert r.status_code == 200 and r.json()["agent_count"] == 2
    got = client.get(f"/api/v1/presets/{pid}").json()
    assert [a["name"] for a in got["agents"]] == ["Ann Okafor", "Bola Adeyemi"]
    assert got["agents"][0]["character"] == {"decision_rules": "Guideline first."}
    assert got["agents"][0]["authored"] is True

    # Load the lineup into the session: the character rides along
    r = client.post(f"/api/v1/sessions/{sid}/apply-preset", json={"preset_id": pid})
    assert r.status_code == 200
    import time
    for _ in range(40):
        agents = client.get(f"/api/v1/sessions/{sid}/agents").json()
        if len(agents) == 2:
            break
        time.sleep(0.1)
    assert len(agents) == 2
    ann = next(a for a in agents if a["name"] == "Ann Okafor")
    assert ann["character"] == {"decision_rules": "Guideline first."}
    assert ann["demographics"]["region"] == "Blackpool, UK" and ann["humanity"] == 20
