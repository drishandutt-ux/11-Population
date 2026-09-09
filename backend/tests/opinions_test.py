"""Tests for the per-agent verdict pipeline (`app.services.simulation.opinions`).

Run:  cd backend && pytest tests/opinions_test.py -q
Uses an in-memory SQLite DB and a mocked Anthropic client — no API key needed.

Regression guard for the production bug where one 1200-token call for all agents
was always truncated → unparsable JSON → `{}` → the sidebar showed "summarising…" forever.
"""
import asyncio
import json
import os
import sys
import types
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.simulation.opinions import parse_verdict_json, generate_opinions, BATCH  # noqa: E402
from app.services.simulation import opinions as opinions_mod  # noqa: E402
# Import every model BEFORE any create_all so all tables are registered on Base.metadata
from app.models.session import AnalysisSession, SessionStatus  # noqa: E402,F401
from app.models.agent import SpawnedAgent, AgentStance  # noqa: E402,F401
from app.models.post import SimulationPost, PostType  # noqa: E402,F401


# ── parse_verdict_json ────────────────────────────────────────────────────────

def test_parse_plain_json():
    assert parse_verdict_json('{"1": "Buy at 180", "2": "Sell; overvalued"}') == {"1": "Buy at 180", "2": "Sell; overvalued"}


def test_parse_strips_code_fences():
    raw = '```json\n{"1": "A", "2": "B"}\n```'
    assert parse_verdict_json(raw) == {"1": "A", "2": "B"}


def test_parse_salvages_truncated_output():
    # Exactly what a max_tokens cut looks like: the last pair is never closed.
    raw = '{"1": "First verdict with \\"quotes\\"", "2": "Second verdict", "3": "Third verd'
    out = parse_verdict_json(raw)
    assert out == {"1": 'First verdict with "quotes"', "2": "Second verdict"}


def test_parse_garbage_returns_empty():
    assert parse_verdict_json("Sorry, I cannot do that.") == {}
    assert parse_verdict_json("") == {}


# ── generate_opinions end-to-end (SQLite + mocked Claude) ────────────────────

class _Resp:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [types.SimpleNamespace(text=text)]
        self.stop_reason = stop_reason
        self.usage = types.SimpleNamespace(input_tokens=10, output_tokens=10)


async def _seed(db, n_agents, posts_per_agent=2):
    sid = str(uuid.uuid4())
    db.add(AnalysisSession(id=sid, title="t", query="Should we do X?", status=SessionStatus.COMPLETE))
    agents = []
    for i in range(n_agents):
        a = SpawnedAgent(
            id=str(uuid.uuid4()), session_id=sid, name=f"Agent {i}", age=30, role="Analyst",
            background="bg", stance=AgentStance.NEUTRAL, correlation="c", personality=["x"],
            debate_style="d", energy=0.5, avatar_color="#000000", dials={},
        )
        agents.append(a)
        db.add(a)
    await db.flush()
    for a in agents:
        for k in range(posts_per_agent):
            db.add(SimulationPost(
                id=str(uuid.uuid4()), session_id=sid, agent_id=a.id, type=PostType.COMMENT,
                content=f"{a.name} post {k}: I believe X is a bad idea because reasons.",
                parent_id=None, likes=0, round_num=k,
            ))
    await db.commit()
    return sid, agents


@pytest.fixture
def db_env(tmp_path):
    """Async factory: builds a fresh SQLite engine + tables INSIDE the running loop
    (creating them on a different loop than the test's makes aiosqlite lose the tables)."""
    async def make():
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from app.core.database import Base
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)
    return make


def _install_fake_client(monkeypatch, handler):
    """Route tracked_messages_create to `handler(kwargs) -> _Resp`."""
    calls = []

    async def fake_create(client, *, session_id=None, label="", **kwargs):
        calls.append(kwargs)
        r = handler(kwargs)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(opinions_mod, "tracked_messages_create", fake_create)
    return calls


def _answer_all(kwargs):
    """Return a verdict for every '#n' block in the prompt."""
    prompt = kwargs["messages"][0]["content"]
    n = prompt.count("\n#") + (1 if "\nAGENTS:\n#" in prompt else 0)
    n = max(n, prompt.count("| stance:"))
    return _Resp(json.dumps({str(i + 1): f"Verdict {i + 1}: reject X" for i in range(n)}))


def test_generate_batches_and_persists(db_env, monkeypatch):
    calls = _install_fake_client(monkeypatch, _answer_all)

    async def run():
        Session = await db_env()
        async with Session() as db:
            sid, agents = await _seed(db, BATCH * 2 + 3)      # 3 batches
            res = await generate_opinions(db, sid, "Should we do X?")
            assert res["error"] is None
            assert res["generated"] == len(agents) == res["total"]
            assert set(res["opinions"]) == {a.id for a in agents}
            assert all(v.startswith("Verdict") for v in res["opinions"].values())
            # max_tokens scales with the batch, not a flat 1200
            assert all(k["max_tokens"] >= 200 + 70 * 3 for k in calls)
            assert len(calls) == 3
        # persisted → visible in a fresh session without another LLM call
        async with Session() as db:
            from sqlalchemy import select
            from app.models.agent import SpawnedAgent
            rows = (await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == sid))).scalars().all()
            assert all(r.verdict for r in rows)
    asyncio.run(run())


def test_truncated_batch_salvages_partial(db_env, monkeypatch):
    def handler(kwargs):
        # Simulate a max_tokens cut after two complete pairs
        return _Resp('{"1": "Only one", "2": "And two", "3": "Thr', stop_reason="max_tokens")
    _install_fake_client(monkeypatch, handler)

    async def run():
        Session = await db_env()
        async with Session() as db:
            sid, agents = await _seed(db, 5)
            res = await generate_opinions(db, sid, "q")
            assert res["generated"] == 2
            assert res["total"] == 5
            assert res["error"] is None
            assert res["opinions"][agents[0].id] == "Only one"
            assert res["opinions"][agents[1].id] == "And two"
    asyncio.run(run())


def test_llm_failure_reports_error_not_empty_success(db_env, monkeypatch):
    class AuthenticationError(Exception):
        pass
    _install_fake_client(monkeypatch, lambda kw: AuthenticationError("401 invalid x-api-key"))

    async def run():
        Session = await db_env()
        async with Session() as db:
            sid, _ = await _seed(db, 4)
            res = await generate_opinions(db, sid, "q")
            assert res["generated"] == 0
            assert res["opinions"] == {}
            assert res["error"] and "ANTHROPIC_API_KEY" in res["error"]
    asyncio.run(run())


def test_existing_verdicts_survive_partial_regeneration(db_env, monkeypatch):
    _install_fake_client(monkeypatch, _answer_all)

    async def run():
        Session = await db_env()
        async with Session() as db:
            sid, agents = await _seed(db, 4)
            first = await generate_opinions(db, sid, "q")
            assert first["generated"] == 4
            # Regenerate only one agent: others keep their persisted verdict in the response
            only = await generate_opinions(db, sid, "q", agent_ids=[agents[0].id])
            assert only["generated"] == 1
            assert set(only["opinions"]) == {a.id for a in agents}
    asyncio.run(run())


def test_agents_without_posts_are_skipped(db_env, monkeypatch):
    calls = _install_fake_client(monkeypatch, _answer_all)

    async def run():
        Session = await db_env()
        async with Session() as db:
            sid, agents = await _seed(db, 3, posts_per_agent=0)
            res = await generate_opinions(db, sid, "q")
            assert res == {"opinions": {}, "generated": 0, "total": 0, "error": None}
            assert calls == []
    asyncio.run(run())
