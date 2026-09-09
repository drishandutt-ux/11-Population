"""Supabase Auth for the API.

The frontend signs users in with Supabase Auth (email + password / magic link) and sends
the user's access token as `Authorization: Bearer <jwt>`. This module verifies that token
and resolves the caller to an `AuthUser`.

Verification path (in order):
  1. Asymmetric keys (ES256 / RS256): verified locally against the project's JWKS
     (`{APP_SUPABASE_URL}/auth/v1/.well-known/jwks.json`, cached by PyJWT). This is what
     the "11 Minds Population" project uses. Issuer and audience are checked.
  2. Shared-secret tokens (HS256, legacy projects): asked of the Auth server directly
     (`GET /auth/v1/user`), with a short in-memory cache so a busy UI doesn't hammer it.

Dev mode: when `APP_SUPABASE_URL` is unset, auth is OFF and every request runs as a fixed
local user (`DEV_USER_ID`). That keeps `./start.sh` and the tests working without a Supabase
project, and makes the production rollout safe (deploy first, set env vars, auth turns on).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt import PyJWKClient

from app.core.config import get_settings

DEV_USER_ID = "00000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: Optional[str] = None
    is_dev: bool = False


class AuthError(HTTPException):
    def __init__(self, detail: str = "Not authenticated"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


_jwks_client: Optional[PyJWKClient] = None
_user_cache: dict[str, tuple[float, AuthUser]] = {}   # token -> (expires_at, user); HS256 path only
_USER_CACHE_TTL = 60.0


def _clean(v: str) -> str:
    """Env values pasted into a dashboard often carry quotes, spaces or a newline; any of those
    makes urllib raise InvalidURL on the JWKS fetch. Strip them."""
    return (v or "").strip().strip('"').strip("'").strip()


def project_url() -> str:
    return _clean(get_settings().app_supabase_url).rstrip("/")


def auth_enabled() -> bool:
    return bool(project_url())


def _issuer() -> str:
    return project_url() + "/auth/v1"


def _jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        # PyJWKClient caches keys (lifespan 5 min by default) and refetches on unknown kid.
        _jwks_client = PyJWKClient(_issuer() + "/.well-known/jwks.json", cache_keys=True, lifespan=600)
    return _jwks_client


async def _verify_with_auth_server(token: str) -> AuthUser:
    """HS256 fallback: only the Auth server can validate a shared-secret token safely."""
    now = time.time()
    hit = _user_cache.get(token)
    if hit and hit[0] > now:
        return hit[1]
    s = get_settings()
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(
            _issuer() + "/user",
            headers={"apikey": _clean(s.app_supabase_anon_key), "Authorization": f"Bearer {token}"},
        )
    if r.status_code != 200:
        raise AuthError("Invalid or expired session")
    data = r.json()
    user = AuthUser(id=str(data.get("id")), email=data.get("email"))
    _user_cache[token] = (now + _USER_CACHE_TTL, user)
    if len(_user_cache) > 2000:   # keep the cache bounded
        for k in [k for k, (exp, _) in _user_cache.items() if exp <= now][:1000]:
            _user_cache.pop(k, None)
    return user


async def verify_token(token: str) -> AuthUser:
    """Resolve a Supabase access token to an AuthUser or raise AuthError."""
    if not token:
        raise AuthError()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise AuthError("Malformed token")

    alg = header.get("alg", "")
    if alg == "HS256":
        return await _verify_with_auth_server(token)

    try:
        signing_key = _jwks().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            issuer=_issuer(),
            options={"require": ["exp", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise AuthError("Session expired")
    except jwt.PyJWTError as e:
        raise AuthError(f"Invalid token: {type(e).__name__}")
    except Exception as e:  # noqa: BLE001 — JWKS fetch failures etc.
        raise HTTPException(status_code=503, detail=f"Auth keys unavailable: {type(e).__name__}")
    return AuthUser(id=str(claims["sub"]), email=claims.get("email"))


def _bearer(request: Request) -> Optional[str]:
    h = request.headers.get("authorization") or ""
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return None


async def get_current_user(request: Request) -> AuthUser:
    """FastAPI dependency: the signed-in user, or the fixed dev user when auth is off."""
    if not auth_enabled():
        return AuthUser(id=DEV_USER_ID, email="dev@localhost", is_dev=True)
    token = _bearer(request)
    if not token:
        raise AuthError()
    return await verify_token(token)


async def user_from_ws_token(token: Optional[str]) -> Optional[AuthUser]:
    """WebSocket variant: the token arrives as a `?token=` query param. Returns None when rejected."""
    if not auth_enabled():
        return AuthUser(id=DEV_USER_ID, email="dev@localhost", is_dev=True)
    if not token:
        return None
    try:
        return await verify_token(token)
    except HTTPException:
        return None


# ── Ownership helpers ────────────────────────────────────────────────────────

async def get_owned_session(session_id: str, user: AuthUser, db):
    """Load a session the caller owns, or 404 (never reveal other users' ids)."""
    from sqlalchemy import select
    from app.models.session import AnalysisSession

    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session or not owns(session, user):
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def owns(session, user: AuthUser) -> bool:
    """A row with no owner (created before auth existed, or in dev mode) belongs to whoever is signed in
    only when auth is off; with auth on, ownerless rows are invisible."""
    owner = getattr(session, "user_id", None)
    if owner is None:
        return not auth_enabled()
    return str(owner).replace("-", "") == str(user.id).replace("-", "")


CurrentUser = Depends(get_current_user)
