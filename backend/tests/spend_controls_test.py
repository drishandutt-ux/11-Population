"""Spend controls (2026-11-13): the per-session web-search cap and the live cost readout.

Run:  cd backend && pytest tests/spend_controls_test.py -q
No network: search engines are stubs; ledger rows go to the local SQLite DB under throwaway
session ids and are deleted afterwards.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")

from sqlalchemy import delete  # noqa: E402

from app.core import monitoring  # noqa: E402
from app.core.auth import AuthUser  # noqa: E402
from app.core.database import AsyncSessionLocal, create_tables  # noqa: E402
from app.models.session import AnalysisSession  # noqa: E402
from app.models.usage import LlmUsage  # noqa: E402
from app.services.evidence.search import provider as prov  # noqa: E402


def test_search_cap_stops_a_session_and_leaves_others_alone(monkeypatch):
    monkeypatch.setattr(prov, "SEARCH_CAP_PER_BUILD", 3)
    sent: list[str] = []

    async def engine(q, opts):
        sent.append(q)
        return [prov.SearchResult(title=f"{q} result", url=f"https://x.org/{len(sent)}", domain="x.org", snippet=q)]

    chain = prov.chain_of([prov.SearchProvider("anthropic", engine)])
    a, b = str(uuid.uuid4()), str(uuid.uuid4())

    async def run(sid, n):
        token = monitoring.current_session_id.set(sid)
        out = []
        try:
            for i in range(n):
                try:
                    await chain.search(f"housing costs {i}", {})
                    out.append("ok")
                except prov.SearchBudgetSpent:
                    out.append("capped")
        finally:
            monitoring.current_session_id.reset(token)
        return out

    assert asyncio.run(run(a, 5)) == ["ok", "ok", "ok", "capped", "capped"]
    assert len(sent) == 3                      # nothing reached an engine past the cap
    assert prov.searches_used(a) == 3
    assert asyncio.run(run(b, 2)) == ["ok", "ok"]   # another session has its own budget


def test_search_cap_window_expires(monkeypatch):
    monkeypatch.setattr(prov, "SEARCH_CAP_PER_BUILD", 1)
    sid = str(uuid.uuid4())
    prov._searches_by_session[sid] = [0.0]     # a search long outside the window
    token = monitoring.current_session_id.set(sid)
    try:
        prov._take_search()                    # allowed: the old one has aged out
        try:
            prov._take_search()
            assert False, "second search in the window should be refused"
        except prov.SearchBudgetSpent:
            pass
    finally:
        monitoring.current_session_id.reset(token)


def test_cost_endpoint_adds_unflushed_calls():
    from app.api.v1.sessions import get_session_cost
    sid, uid = str(uuid.uuid4()), str(uuid.uuid4())

    async def run():
        await create_tables()
        async with AsyncSessionLocal() as db:
            db.add(AnalysisSession(id=sid, title="cost test", query="q", user_id=uid))
            db.add(LlmUsage(session_id=sid, label="search", model="claude-haiku-4-5", cost_usd=1.25, web_search_requests=1, created_at=datetime(2026, 1, 1)))
            db.add(LlmUsage(session_id=sid, label="probe", model="claude-sonnet-4-6", cost_usd=2.0))
            await db.commit()
        monitoring._buffer.clear()
        monitoring._buffer.append({"session_id": sid, "model": "claude-sonnet-4-6", "cost_usd": 0.5, "web_search_requests": 0, "created_at": datetime.utcnow()})
        monitoring._buffer.append({"session_id": "someone-else", "model": "claude-sonnet-4-6", "cost_usd": 9.0, "created_at": datetime.utcnow()})
        try:
            async with AsyncSessionLocal() as db:
                return await get_session_cost(sid, AuthUser(id=uid), db)
        finally:
            monitoring._buffer.clear()
            async with AsyncSessionLocal() as db:
                await db.execute(delete(LlmUsage).where(LlmUsage.session_id == sid))
                await db.execute(delete(AnalysisSession).where(AnalysisSession.id == sid))
                await db.commit()

    c = asyncio.run(run())
    assert c["cost_usd"] == 3.75
    assert c["calls"] == 3
    assert c["web_searches"] == 1
    assert c["last_minute_usd"] == 2.5         # the 2026-01-01 row is not "now"
    assert c["by_model"][0] == {"model": "claude-sonnet-4-6", "cost_usd": 2.5}
    assert c["search_cap"]["limit"] == prov.SEARCH_CAP_PER_BUILD
