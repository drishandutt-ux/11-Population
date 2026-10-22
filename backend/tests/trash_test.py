"""The bin (2026-10-22): delete moves a session to Recently deleted, restore brings it back, delete
forever and the 30-day purge remove it for good.

Run:  cd backend && pytest tests/trash_test.py -q
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from tests.auth_test import _token, auth_on, client  # noqa: E402,F401

A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _h(uid, email):
    return {"Authorization": f"Bearer {_token(uid, email=email)}"}


def _new(client, h, title):
    return client.post("/api/v1/sessions", json={"title": title, "query": "Would people pay?", "auto_research": False}, headers=h).json()["id"]


def test_delete_restore_and_delete_forever(auth_on, client):
    a, b = _h(A, "ana@11-london.com"), _h(B, "ben@11-london.com")
    for h in (a, b):
        assert client.get("/api/v1/me", headers=h).status_code == 200
    sid = _new(client, a, "Keep me")
    assert client.put(f"/api/v1/sessions/{sid}/shares", json={"user_ids": [B]}, headers=a).status_code == 200

    # only the owner can bin it
    assert client.delete(f"/api/v1/sessions/{sid}", headers=b).status_code == 404
    assert client.delete(f"/api/v1/sessions/{sid}", headers=a).status_code == 204

    # gone from every list and page, for the owner and the colleague alike
    assert client.get("/api/v1/sessions", headers=a).json() == []
    assert client.get(f"/api/v1/sessions/{sid}", headers=a).status_code == 404
    assert client.get(f"/api/v1/sessions/{sid}", headers=b).status_code == 404
    assert client.get("/api/v1/shared-sessions", headers=b).json() == []

    # … but in the owner's bin, with the date it goes for good
    trash = client.get("/api/v1/sessions?scope=trash", headers=a).json()
    assert [t["id"] for t in trash] == [sid]
    gap = datetime.fromisoformat(trash[0]["purge_at"]) - datetime.fromisoformat(trash[0]["deleted_at"])
    assert gap == timedelta(days=30)
    assert client.get("/api/v1/sessions?scope=trash", headers=b).json() == []
    assert client.post(f"/api/v1/sessions/{sid}/restore", headers=b).status_code == 404

    # restore: back as it was, shares included
    r = client.post(f"/api/v1/sessions/{sid}/restore", headers=a)
    assert r.status_code == 200 and r.json()["title"] == "Keep me"
    assert [s["id"] for s in client.get("/api/v1/sessions", headers=a).json()] == [sid]
    assert [s["id"] for s in client.get("/api/v1/shared-sessions", headers=b).json()] == [sid]
    assert client.get("/api/v1/sessions?scope=trash", headers=a).json() == []
    # a live session cannot be deleted forever without going through the bin first
    assert client.delete(f"/api/v1/sessions/{sid}/permanent", headers=a).status_code == 404

    # delete forever
    assert client.delete(f"/api/v1/sessions/{sid}", headers=a).status_code == 204
    assert client.delete(f"/api/v1/sessions/{sid}/permanent", headers=a).status_code == 204
    assert client.get("/api/v1/sessions?scope=trash", headers=a).json() == []
    assert client.post(f"/api/v1/sessions/{sid}/restore", headers=a).status_code == 404


def test_purge_removes_only_sessions_binned_more_than_30_days_ago(auth_on, client):
    a = _h(A, "ana@11-london.com")
    assert client.get("/api/v1/me", headers=a).status_code == 200
    old, recent = _new(client, a, "Old"), _new(client, a, "Recent")
    assert client.delete(f"/api/v1/sessions/{old}", headers=a).status_code == 204
    assert client.delete(f"/api/v1/sessions/{recent}", headers=a).status_code == 204

    import app.core.database as dbm
    from app.core.trash import purge_expired
    from app.models.session import AnalysisSession

    async def backdate():
        async with dbm.AsyncSessionLocal() as db:
            s = await db.get(AnalysisSession, old)
            s.deleted_at = datetime.utcnow() - timedelta(days=31)
            await db.commit()

    asyncio.run(backdate())
    assert asyncio.run(purge_expired()) == 1
    assert [t["id"] for t in client.get("/api/v1/sessions?scope=trash", headers=a).json()] == [recent]
