"""Public config, the current user, and admin user management."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
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
