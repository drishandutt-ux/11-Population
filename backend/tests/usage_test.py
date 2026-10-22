"""Token & cost ledger tests (2026-10-22).

Run:  cd backend && pytest tests/usage_test.py -q
No network: the Anthropic client is a stub returning a fixed `usage`. Rows are written to the
local SQLite DB under throwaway session ids and deleted afterwards.
"""
import asyncio
import os
import sys
import types
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from sqlalchemy import delete  # noqa: E402

from app.core import monitoring  # noqa: E402
from app.core.database import AsyncSessionLocal, create_tables  # noqa: E402
from app.core.pricing import cost_usd, family  # noqa: E402
from app.models.usage import LlmUsage  # noqa: E402


def test_family_strips_date_suffix_and_prefers_longest_match():
    assert family("claude-haiku-4-5-20251001") == "claude-haiku-4-5"
    assert family("claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert family("claude-opus-4-5-20251101") == "claude-opus-4-5"
    assert family("claude-opus-5") == "claude-opus-5"
    assert family("claude-opus-5-5") == "claude-opus-5-5"
    assert family("gpt-4o") is None


def test_cost_includes_cache_and_web_search():
    usd, priced = cost_usd("claude-haiku-4-5-20251001", input_tokens=1_000_000, output_tokens=1_000_000)
    assert priced and usd == 6.0
    usd, _ = cost_usd("claude-sonnet-4-6", cache_creation_tokens=1_000_000, cache_read_tokens=1_000_000, web_search_requests=10)
    assert usd == round(3.75 + 0.30 + 0.10, 6)


def test_unknown_model_is_priced_as_estimate():
    usd, priced = cost_usd("some-new-model", input_tokens=1_000_000)
    assert not priced and usd > 0


class _StubMessages:
    def __init__(self, usage):
        self._usage = usage

    async def create(self, **kw):
        return types.SimpleNamespace(usage=self._usage, content=[])


def _client(inp=100, out=50, cw=0, cr=0, searches=0):
    u = types.SimpleNamespace(
        input_tokens=inp, output_tokens=out, cache_creation_input_tokens=cw, cache_read_input_tokens=cr,
        server_tool_use=types.SimpleNamespace(web_search_requests=searches),
    )
    return types.SimpleNamespace(messages=_StubMessages(u))


def test_calls_land_in_the_ledger_tagged_by_context_session():
    sid_ctx, sid_explicit = str(uuid.uuid4()), str(uuid.uuid4())

    async def run():
        await create_tables()
        monitoring._buffer.clear()
        token = monitoring.current_session_id.set(sid_ctx)
        try:
            await monitoring.tracked_messages_create(_client(), label="post", model="claude-haiku-4-5-20251001", max_tokens=10, messages=[])
            # a background task spawned inside the request inherits the session
            await asyncio.create_task(monitoring.tracked_messages_create(_client(searches=2), label="search", model="claude-sonnet-4-6", max_tokens=10, messages=[]))
            # an explicit session_id wins over the context
            await monitoring.tracked_messages_create(_client(), session_id=sid_explicit, label="chat", model="claude-haiku-4-5", max_tokens=10, messages=[])
        finally:
            monitoring.current_session_id.reset(token)
        await monitoring.tracked_messages_create(_client(), label="kit", model="claude-haiku-4-5", max_tokens=10, messages=[])
        assert monitoring._buffer[-1]["session_id"] is None

        # only persist our own rows
        mine = [r for r in monitoring._buffer if r["session_id"] in (sid_ctx, sid_explicit)]
        monitoring._buffer.clear()
        monitoring._buffer.extend(mine)
        assert await monitoring.flush_usage() == 3

        from app.api.v1.users import admin_usage, admin_usage_session
        async with AsyncSessionLocal() as db:
            data = await admin_usage(days=0, admin=None, db=db)
            row = next(s for s in data["sessions"] if s["session_id"] == sid_ctx)
            assert row["calls"] == 2 and row["web_search_requests"] == 2
            assert {m["model"] for m in row["models"]} == {"claude-haiku-4-5-20251001", "claude-sonnet-4-6"}
            assert row["title"] == "Deleted session"
            detail = await admin_usage_session(sid_ctx, days=0, admin=None, db=db)
            assert {e["label"] for e in detail["executions"]} == {"post", "search"}
            assert len(detail["recent"]) == 2
            await db.execute(delete(LlmUsage).where(LlmUsage.session_id.in_([sid_ctx, sid_explicit])))
            await db.commit()

    asyncio.run(run())


def test_middleware_reads_session_from_path():
    seen = {}

    async def app(scope, receive, send):
        seen["sid"] = monitoring.current_session_id.get()

    sid = str(uuid.uuid4())
    mw = monitoring.SessionContextMiddleware(app)
    asyncio.run(mw({"type": "http", "path": f"/api/v1/sessions/{sid}/simulate"}, None, None))
    assert seen["sid"] == sid
    asyncio.run(mw({"type": "http", "path": "/api/v1/kits"}, None, None))
    assert seen["sid"] is None
