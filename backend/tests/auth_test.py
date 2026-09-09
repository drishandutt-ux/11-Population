"""Auth + ownership tests.

Run:  cd backend && pytest tests/auth_test.py -q
No network: JWTs are signed with a throwaway ES256 key and the JWKS client is stubbed.
"""
import asyncio
import os
import sys
import time
import types

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.core import auth as auth_mod  # noqa: E402
from app.core.config import get_settings  # noqa: E402

PROJECT = "https://example-ref.supabase.co"
ISSUER = PROJECT + "/auth/v1"

_KEY = ec.generate_private_key(ec.SECP256R1())
_OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def _token(sub="11111111-1111-1111-1111-111111111111", *, key=_KEY, aud="authenticated", iss=ISSUER, exp_delta=3600, email="a@x.com"):
    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "aud": aud, "iss": iss, "iat": now, "exp": now + exp_delta, "email": email, "role": "authenticated"},
        key, algorithm="ES256", headers={"kid": "test-kid"},
    )


@pytest.fixture
def auth_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "app_supabase_url", PROJECT)
    monkeypatch.setattr(s, "app_supabase_anon_key", "anon")
    # Stub the JWKS client: always returns our test public key.
    fake = types.SimpleNamespace(get_signing_key_from_jwt=lambda tok: types.SimpleNamespace(key=_KEY.public_key()))
    monkeypatch.setattr(auth_mod, "_jwks", lambda: fake)
    yield s


@pytest.fixture
def auth_off(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "app_supabase_url", "")
    yield s


# ── verify_token ─────────────────────────────────────────────────────────────

def test_valid_token_resolves_user(auth_on):
    u = asyncio.run(auth_mod.verify_token(_token()))
    assert u.id == "11111111-1111-1111-1111-111111111111" and u.email == "a@x.com" and not u.is_dev


def test_expired_token_rejected(auth_on):
    with pytest.raises(auth_mod.AuthError) as e:
        asyncio.run(auth_mod.verify_token(_token(exp_delta=-10)))
    assert "expired" in e.value.detail.lower()


def test_wrong_signing_key_rejected(auth_on):
    with pytest.raises(auth_mod.AuthError):
        asyncio.run(auth_mod.verify_token(_token(key=_OTHER_KEY)))


def test_wrong_audience_or_issuer_rejected(auth_on):
    with pytest.raises(auth_mod.AuthError):
        asyncio.run(auth_mod.verify_token(_token(aud="anon")))
    with pytest.raises(auth_mod.AuthError):
        asyncio.run(auth_mod.verify_token(_token(iss="https://evil.example/auth/v1")))


def test_garbage_token_rejected(auth_on):
    with pytest.raises(auth_mod.AuthError):
        asyncio.run(auth_mod.verify_token("not-a-jwt"))


def test_dev_mode_without_project(auth_off):
    async def run():
        req = types.SimpleNamespace(headers={})
        return await auth_mod.get_current_user(req)
    u = asyncio.run(run())
    assert u.is_dev and u.id == auth_mod.DEV_USER_ID


def test_env_value_is_sanitised(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "app_supabase_url", '  "https://example-ref.supabase.co/"\n')
    assert auth_mod.project_url() == "https://example-ref.supabase.co"
    assert auth_mod._issuer() == ISSUER
    assert auth_mod.auth_enabled()


# ── API ownership isolation ──────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient on a fresh SQLite DB (tables created via the app's own create_tables)."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.core.database as dbm
    import app.models.session, app.models.agent, app.models.post, app.models.report, app.models.preset, app.models.kg  # noqa: F401

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setattr(dbm, "engine", eng)
    monkeypatch.setattr(dbm, "AsyncSessionLocal", async_sessionmaker(eng, expire_on_commit=False))
    monkeypatch.setattr(dbm, "_sqlite", True)
    monkeypatch.setattr(auth_mod, "_role_cache", {})   # roles are per-DB; never leak between tests

    async def _get_db():
        async with dbm.AsyncSessionLocal() as s:
            yield s

    from fastapi.testclient import TestClient
    from app.main import app
    app.dependency_overrides[dbm.get_db] = _get_db
    with TestClient(app) as c:   # lifespan runs create_tables on the patched engine
        yield c
    app.dependency_overrides.clear()


def test_api_requires_token_when_auth_on(auth_on, client):
    assert client.get("/api/v1/sessions").status_code == 401
    assert client.post("/api/v1/sessions", json={"title": "t", "query": "q"}).status_code == 401
    assert client.get("/health").status_code == 200   # health stays public


def test_sessions_are_private_per_user(auth_on, client):
    a = {"Authorization": f"Bearer {_token('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')}"}
    b = {"Authorization": f"Bearer {_token('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', email='b@x.com')}"}

    r = client.post("/api/v1/sessions", json={"title": "A's", "query": "q"}, headers=a)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    assert [s["id"] for s in client.get("/api/v1/sessions", headers=a).json()] == [sid]
    assert client.get("/api/v1/sessions", headers=b).json() == []
    assert client.get(f"/api/v1/sessions/{sid}", headers=a).status_code == 200
    # Every session-scoped route 404s for the other user (no existence leak)
    for path in (f"/sessions/{sid}", f"/sessions/{sid}/agents", f"/sessions/{sid}/posts", f"/sessions/{sid}/kg", f"/sessions/{sid}/report/history"):
        assert client.get(f"/api/v1{path}", headers=b).status_code == 404, path
    assert client.post(f"/api/v1/sessions/{sid}/opinions", json={}, headers=b).status_code == 404
    assert client.delete(f"/api/v1/sessions/{sid}", headers=b).status_code == 404
    assert client.delete(f"/api/v1/sessions/{sid}", headers=a).status_code == 204


def test_presets_are_private_per_user(auth_on, client):
    a = {"Authorization": f"Bearer {_token('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')}"}
    b = {"Authorization": f"Bearer {_token('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')}"}
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "q"}, headers=a).json()["id"]
    # Saving a preset needs agents; without them it's a 400 for the owner and a 404 for a stranger
    assert client.post("/api/v1/presets", json={"session_id": sid, "name": "x"}, headers=a).status_code == 400
    assert client.post("/api/v1/presets", json={"session_id": sid, "name": "x"}, headers=b).status_code == 404
    assert client.get("/api/v1/presets", headers=b).json() == []


def test_websocket_rejects_bad_token_and_foreign_session(auth_on, client):
    from starlette.websockets import WebSocketDisconnect
    a = {"Authorization": f"Bearer {_token('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')}"}
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "q"}, headers=a).json()["id"]
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(f"/ws/{sid}?token=garbage"):
            pass
    assert e.value.code == 4401
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(f"/ws/{sid}?token={_token('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')}"):
            pass
    assert e.value.code == 4404
    # Owner connects fine and receives the keepalive/ping loop (we just check accept)
    with client.websocket_connect(f"/ws/{sid}?token={_token('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')}") as ws:
        assert ws is not None


def test_public_config_and_me(auth_on, client):
    cfg = client.get("/api/v1/config").json()
    assert cfg["auth"]["enabled"] is True and cfg["auth"]["supabase_url"] == PROJECT and cfg["auth"]["anon_key"] == "anon"
    assert client.get("/api/v1/me").status_code == 401
    a = {"Authorization": f"Bearer {_token('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')}"}
    me = client.get("/api/v1/me", headers=a).json()
    assert me["email"] == "a@x.com"


def test_first_user_is_admin_and_admin_sees_everything(auth_on, client):
    a = {"Authorization": f"Bearer {_token('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')}"}
    b = {"Authorization": f"Bearer {_token('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', email='b@x.com')}"}
    # First /me creates the first profile → admin; the second user is a member
    assert client.get("/api/v1/me", headers=a).json()["role"] == "admin"
    assert client.get("/api/v1/me", headers=b).json()["role"] == "member"
    sid_b = client.post("/api/v1/sessions", json={"title": "B's", "query": "q"}, headers=b).json()["id"]
    # Member cannot use admin routes; admin can, and can read the member's session
    assert client.get("/api/v1/admin/users", headers=b).status_code == 403
    users = client.get("/api/v1/admin/users", headers=a).json()
    assert {u["email"]: u["role"] for u in users} == {"a@x.com": "admin", "b@x.com": "member"}
    assert client.get(f"/api/v1/sessions/{sid_b}", headers=a).status_code == 200
    everyone = client.get("/api/v1/sessions?scope=all", headers=a).json()
    assert [s["owner_email"] for s in everyone] == ["b@x.com"]
    assert client.get("/api/v1/sessions", headers=a).json() == []          # own list stays own
    assert client.get("/api/v1/sessions?scope=all", headers=b).json()[0]["id"] == sid_b  # member: scope ignored, still own
    # Promote / demote with last-admin protection
    bid = [u["id"] for u in users if u["email"] == "b@x.com"][0]
    aid = [u["id"] for u in users if u["email"] == "a@x.com"][0]
    assert client.patch(f"/api/v1/admin/users/{aid}/role", json={"role": "member"}, headers=a).status_code == 400
    assert client.patch(f"/api/v1/admin/users/{bid}/role", json={"role": "admin"}, headers=a).json()["role"] == "admin"
    assert client.get("/api/v1/me", headers=b).json()["role"] == "admin"


def test_dev_mode_api_needs_no_token(auth_off, client):
    r = client.post("/api/v1/sessions", json={"title": "t", "query": "q"})
    assert r.status_code == 200
    assert client.get("/api/v1/sessions").status_code == 200
    assert client.get(f"/api/v1/sessions/{r.json()['id']}/kg").json() == {"entities": [], "relations": []}


def test_kg_persists_in_database(auth_off, client, monkeypatch):
    """The knowledge graph now lives in kg_graphs, not on disk: save → forget cache → reload from DB."""
    from app.services.knowledge_graph import lightrag_service as kg
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "q"}).json()["id"]

    async def run():
        await kg.get_lightrag(sid)
        await kg._save_kg(sid, {"entities": ["Wind"], "relations": [["Wind", "powers", "Homes"]], "chunks": ["c1"]})
        kg.forget(sid)
        await kg.get_lightrag(sid)
        return kg.get_kg_data(sid)
    data = asyncio.run(run())
    assert data == {"entities": ["Wind"], "relations": [["Wind", "powers", "Homes"]]}
