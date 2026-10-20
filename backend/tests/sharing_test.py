"""Peers, sharing and the shared chat (2026-10-20). Two signed-in users on one domain, a third on
another; the report agent is stubbed.

Run:  cd backend && pytest tests/sharing_test.py -q
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.core.config import get_settings  # noqa: E402
import app.core.auth as auth_mod  # noqa: E402
from tests.auth_test import _token, auth_on, client  # noqa: E402,F401

A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _h(uid, email):
    return {"Authorization": f"Bearer {_token(uid, email=email)}"}


def test_peers_sharing_and_the_shared_chat(auth_on, client, monkeypatch):
    a, b, c = _h(A, "ana@11-london.com"), _h(B, "ben@11-london.com"), _h(C, "cat@elsewhere.com")
    # profiles exist once each has called /me (the first becomes admin; that is irrelevant here)
    for h in (a, b, c):
        assert client.get("/api/v1/me", headers=h).status_code == 200

    # peers: same domain only, never yourself
    peers = client.get("/api/v1/peers", headers=a).json()
    assert [p["email"] for p in peers] == ["ben@11-london.com"]
    assert client.get("/api/v1/peers", headers=c).json() == []

    sid = client.post("/api/v1/sessions", json={"title": "A's", "query": "Would people pay £15 a month?"}, headers=a).json()["id"]

    # nothing shared yet: B cannot see the chat, has no shared sessions
    assert client.get(f"/api/v1/sessions/{sid}/shared-chat", headers=b).status_code == 404
    assert client.get("/api/v1/shared-sessions", headers=b).json() == []

    # only the owner shares; only peers on the domain can be named
    assert client.put(f"/api/v1/sessions/{sid}/shares", json={"user_ids": [B]}, headers=b).status_code == 404
    assert client.put(f"/api/v1/sessions/{sid}/shares", json={"user_ids": [C]}, headers=a).status_code == 400
    r = client.put(f"/api/v1/sessions/{sid}/shares", json={"user_ids": [B, A]}, headers=a)
    assert r.status_code == 200
    members = r.json()["members"]
    assert [(m["email"], m["is_owner"]) for m in members] == [("ana@11-london.com", True), ("ben@11-london.com", False)]

    # B now sees it under shared-with-me, and the chat; C still does not; B's own session list is unchanged
    shared = client.get("/api/v1/shared-sessions", headers=b).json()
    assert len(shared) == 1 and shared[0]["id"] == sid and shared[0]["owner"]["email"] == "ana@11-london.com" and shared[0]["members"] == 2
    assert client.get("/api/v1/sessions", headers=b).json() == []
    assert client.get(f"/api/v1/sessions/{sid}", headers=b).status_code == 404          # sharing is the chat, not the owner's pages
    assert client.get(f"/api/v1/sessions/{sid}/shared-chat", headers=c).status_code == 404
    chat = client.get(f"/api/v1/sessions/{sid}/shared-chat", headers=b).json()
    assert chat["you"]["is_owner"] is False and chat["you"]["can_open"] is False and chat["messages"] == [] and chat["report"] is None
    assert client.get(f"/api/v1/sessions/{sid}/shared-chat", headers=a).json()["you"]["is_owner"] is True

    # people talk; the report agent answers an @report mention in a message of its own
    calls = []

    async def fake_answer(session_id, original_query, question, db, records=None):
        calls.append((session_id, original_query, question))
        return "About a third would, the records say.", "R1"

    import app.services.simulation.report_generator as rg
    monkeypatch.setattr(rg, "answer_report_query", fake_answer)
    assert client.post(f"/api/v1/sessions/{sid}/shared-chat", json={"content": "  "}, headers=b).status_code == 400
    r = client.post(f"/api/v1/sessions/{sid}/shared-chat", json={"content": "Ben here — what did they make of the price?"}, headers=b)
    assert r.status_code == 200 and r.json()["report_pending"] is False and r.json()["message"]["author_name"] == "ben"
    r = client.post(f"/api/v1/sessions/{sid}/shared-chat", json={"content": "@report how many would pay?"}, headers=a)
    assert r.status_code == 200 and r.json()["report_pending"] is True
    first_id = r.json()["message"]["id"]

    async def wait():
        for _ in range(50):
            if not auth_mod.__dict__ and False:
                break
            from app.api.v1 import sharing
            if not sharing._report_tasks:
                return
            await asyncio.sleep(0.05)
    # the agent's turn runs on the app's loop; poll the chat until its reply lands
    import time
    for _ in range(100):
        chat = client.get(f"/api/v1/sessions/{sid}/shared-chat", headers=b).json()
        if any(m["kind"] == "report" for m in chat["messages"]):
            break
        time.sleep(0.05)
    kinds = [(m["kind"], m["author_name"]) for m in chat["messages"]]
    assert kinds == [("user", "ben"), ("user", "ana"), ("report", "Report")]
    reply = chat["messages"][-1]
    assert reply["content"] == "About a third would, the records say." and reply["reply_to"] == first_id and reply["user_id"] is None
    assert calls and calls[0][1] == "Would people pay £15 a month?" and "THE QUESTION: how many would pay?" in calls[0][2] and "ben: Ben here" in calls[0][2]
    assert client.get("/api/v1/shared-sessions", headers=b).json()[0]["messages"] == 3

    # a colleague leaves; the owner can also remove; the chat closes for them
    assert client.delete(f"/api/v1/sessions/{sid}/shares/{B}", headers=b).json()["removed"] == 1
    assert client.get(f"/api/v1/sessions/{sid}/shared-chat", headers=b).status_code == 404
    assert client.get("/api/v1/shared-sessions", headers=b).json() == []


def test_allowed_domains_rule(auth_on, client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "allowed_email_domains", "11-london.com, example.org")
    assert client.get("/api/v1/me", headers=_h(A, "ana@11-london.com")).status_code == 200
    assert client.get("/api/v1/me", headers=_h(B, "ben@Example.org")).status_code == 200
    r = client.get("/api/v1/me", headers=_h(C, "cat@elsewhere.com"))
    assert r.status_code == 403 and "11-london.com" in r.json()["detail"]
    monkeypatch.setattr(s, "allowed_email_domains", "")
    assert client.get("/api/v1/me", headers=_h(C, "cat@elsewhere.com")).status_code == 200
