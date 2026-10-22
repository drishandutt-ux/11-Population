"""Public config, the current user, and admin user management."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, get_current_user, require_admin, auth_enabled, project_url, ensure_profile
from app.core.config import get_settings
from app.core.database import get_db
from app.models.profile import Profile, ROLE_ADMIN, ROLE_MEMBER
from app.models.session import AnalysisSession

router = APIRouter(tags=["users"])


@router.get("/config")
async def public_config():
    """Public, unauthenticated: what the frontend needs to sign users in. Lets the app work
    wherever it is hosted, without baking the Supabase project into the build."""
    s = get_settings()
    return {
        "auth": {
            "enabled": auth_enabled(),
            "supabase_url": project_url() if auth_enabled() else None,
            "anon_key": (s.app_supabase_anon_key or "").strip().strip('"').strip("'") if auth_enabled() else None,
        }
    }


@router.get("/me")
async def me(user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await ensure_profile(user, db)
    from app.core.auth import with_role
    user = await with_role(user)   # re-read: ensure_profile may have just created it (first user → admin)
    return {"id": user.id, "email": user.email, "role": user.role, "is_admin": user.is_admin}


# ── Admin ────────────────────────────────────────────────────────────────────

class RoleUpdate(BaseModel):
    role: str


@router.get("/admin/users")
async def admin_list_users(admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    counts = dict(
        (await db.execute(
            select(AnalysisSession.user_id, func.count(AnalysisSession.id)).group_by(AnalysisSession.user_id)
        )).all()
    )
    rows = (await db.execute(select(Profile).order_by(Profile.created_at.asc()))).scalars().all()
    return [
        {
            "id": p.id, "email": p.email, "display_name": p.display_name, "role": p.role,
            "created_at": p.created_at, "sessions": int(counts.get(p.id, 0) or 0),
            "is_you": str(p.id).replace("-", "") == str(admin.id).replace("-", ""),
        }
        for p in rows
    ]


@router.patch("/admin/users/{user_id}/role")
async def admin_set_role(user_id: str, body: RoleUpdate, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    if body.role not in (ROLE_ADMIN, ROLE_MEMBER):
        raise HTTPException(status_code=400, detail="role must be 'admin' or 'member'")
    row = (await db.execute(select(Profile).where(Profile.id == user_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    if body.role == ROLE_MEMBER:
        admins = (await db.execute(select(func.count()).select_from(Profile).where(Profile.role == ROLE_ADMIN))).scalar_one()
        if row.role == ROLE_ADMIN and admins <= 1:
            raise HTTPException(status_code=400, detail="You cannot demote the last admin")
    row.role = body.role
    await db.commit()
    from app.core.auth import forget_role
    forget_role(user_id)
    return {"id": row.id, "role": row.role}


# ── Admin · Tokens & cost ────────────────────────────────────────────────────
# Reads the local `llm_usage` ledger (one row per Anthropic call). `session_id = "none"` is the
# bucket of calls not tied to a session (global search, kit builds, startup recovery…).

def _usage_cols():
    from app.models.usage import LlmUsage as U
    return U, [
        func.count(U.id).label("calls"),
        func.coalesce(func.sum(U.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(U.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(U.cache_creation_tokens), 0).label("cache_creation_tokens"),
        func.coalesce(func.sum(U.cache_read_tokens), 0).label("cache_read_tokens"),
        func.coalesce(func.sum(U.web_search_requests), 0).label("web_search_requests"),
        func.coalesce(func.sum(U.cost_usd), 0.0).label("cost_usd"),
        func.sum(case((U.status != "success", 1), else_=0)).label("errors"),
        func.sum(case((U.priced == 0, 1), else_=0)).label("unpriced"),
        func.min(U.created_at).label("first_at"),
        func.max(U.created_at).label("last_at"),
    ]


def _agg(row) -> dict:
    d = {k: row._mapping[k] for k in ("calls", "input_tokens", "output_tokens", "cache_creation_tokens",
                                      "cache_read_tokens", "web_search_requests", "errors", "unpriced")}
    d = {k: int(v or 0) for k, v in d.items()}
    d["total_tokens"] = d["input_tokens"] + d["output_tokens"] + d["cache_creation_tokens"] + d["cache_read_tokens"]
    d["cost_usd"] = round(float(row._mapping["cost_usd"] or 0), 4)
    d["first_at"] = row._mapping["first_at"]
    d["last_at"] = row._mapping["last_at"]
    return d


def _since(days: int):
    from datetime import datetime, timedelta
    return datetime.utcnow() - timedelta(days=days) if days and days > 0 else None


@router.get("/admin/usage")
async def admin_usage(days: int = 0, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Every session's LLM spend: tokens, models and cost. `days=0` → all time."""
    U, cols = _usage_cols()
    since = _since(days)
    where = [U.created_at >= since] if since else []

    by_session_model = (await db.execute(
        select(U.session_id, U.model, *cols).where(*where).group_by(U.session_id, U.model)
    )).all()

    sessions: dict = {}
    models: dict = {}
    for r in by_session_model:
        sid = r.session_id or "none"
        a = _agg(r)
        s = sessions.setdefault(sid, {"session_id": sid, "models": [], **{k: 0 for k in a if k not in ("first_at", "last_at")}, "first_at": None, "last_at": None})
        for k, v in a.items():
            if k == "first_at":
                s[k] = v if s[k] is None or (v and v < s[k]) else s[k]
            elif k == "last_at":
                s[k] = v if s[k] is None or (v and v > s[k]) else s[k]
            else:
                s[k] = round(s[k] + v, 4) if k == "cost_usd" else s[k] + v
        s["models"].append({"model": r.model, "calls": a["calls"], "total_tokens": a["total_tokens"], "cost_usd": a["cost_usd"]})
        m = models.setdefault(r.model, {"model": r.model, "calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0})
        for k in ("calls", "input_tokens", "output_tokens", "total_tokens"):
            m[k] += a[k]
        m["cost_usd"] = round(m["cost_usd"] + a["cost_usd"], 4)

    ids = [sid for sid in sessions if sid != "none"]
    meta = {}
    if ids:
        meta = {r.id: r for r in (await db.execute(
            select(AnalysisSession.id, AnalysisSession.title, AnalysisSession.user_id, AnalysisSession.created_at)
            .where(AnalysisSession.id.in_(ids))
        )).all()}
    owners = {}
    uids = {str(m.user_id) for m in meta.values() if m.user_id}
    if uids:
        owners = {str(p.id): p.email for p in (await db.execute(select(Profile.id, Profile.email).where(Profile.id.in_(uids)))).all()}

    out = []
    for sid, s in sessions.items():
        m = meta.get(sid)
        s["models"].sort(key=lambda x: -x["cost_usd"])
        s["title"] = m.title if m else ("Not tied to a session" if sid == "none" else "Deleted session")
        s["exists"] = bool(m)
        s["owner_email"] = owners.get(str(m.user_id)) if m and m.user_id else None
        s["session_created_at"] = m.created_at if m else None
        out.append(s)
    out.sort(key=lambda x: -(x["cost_usd"] or 0))

    totals = {k: sum(s[k] for s in out) for k in ("calls", "input_tokens", "output_tokens", "cache_creation_tokens",
                                                  "cache_read_tokens", "web_search_requests", "total_tokens", "errors", "unpriced")}
    totals["cost_usd"] = round(sum(s["cost_usd"] for s in out), 4)
    totals["sessions"] = len([s for s in out if s["session_id"] != "none"])
    return {
        "days": days,
        "totals": totals,
        "models": sorted(models.values(), key=lambda x: -x["cost_usd"]),
        "sessions": out,
    }


@router.get("/admin/usage/sessions/{session_id}")
async def admin_usage_session(session_id: str, days: int = 0, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """One session's spend broken down by execution (label) and model, plus its most recent calls."""
    U, cols = _usage_cols()
    where = [U.session_id.is_(None)] if session_id == "none" else [U.session_id == session_id]
    since = _since(days)
    if since:
        where.append(U.created_at >= since)

    rows = (await db.execute(select(U.label, U.model, *cols).where(*where).group_by(U.label, U.model))).all()
    executions = [{"label": r.label or "(unlabelled)", "model": r.model, **_agg(r)} for r in rows]
    executions.sort(key=lambda x: -x["cost_usd"])

    recent = (await db.execute(select(U).where(*where).order_by(U.created_at.desc()).limit(200))).scalars().all()
    return {
        "session_id": session_id,
        "executions": executions,
        "recent": [
            {
                "created_at": c.created_at, "label": c.label, "model": c.model,
                "input_tokens": c.input_tokens, "output_tokens": c.output_tokens,
                "cache_creation_tokens": c.cache_creation_tokens, "cache_read_tokens": c.cache_read_tokens,
                "web_search_requests": c.web_search_requests, "cost_usd": round(c.cost_usd or 0, 6),
                "elapsed_sec": c.elapsed_sec, "status": c.status, "priced": bool(c.priced),
            }
            for c in recent
        ],
    }
