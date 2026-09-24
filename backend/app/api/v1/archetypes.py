"""Archetypes (brief L3-02): the hand-authored moulds the Population Studio casts personas from.
Created from the Agent Builder (`as_archetype` on a lineup save); listed here for the Studio's
segment picker and deleted here."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import AuthUser, get_current_user, owns
from app.models.archetype import Archetype
from app.services.agents.archetypes import archetype_summary

router = APIRouter(prefix="/archetypes", tags=["archetypes"])


class ArchetypeResponse(BaseModel):
    id: str
    name: str
    role: str
    summary: str
    created_at: datetime


@router.get("", response_model=list[ArchetypeResponse])
async def list_archetypes(user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    q = select(Archetype).order_by(Archetype.created_at.desc())
    if not user.is_dev:
        q = q.where(Archetype.user_id == user.id)
    rows = (await db.execute(q)).scalars().all()
    return [ArchetypeResponse(id=a.id, name=a.name, role=a.role, summary=archetype_summary(a.profile or {}), created_at=a.created_at) for a in rows]


@router.get("/{archetype_id}")
async def get_archetype(archetype_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    a = (await db.execute(select(Archetype).where(Archetype.id == archetype_id))).scalar_one_or_none()
    if not a or not owns(a, user):
        raise HTTPException(status_code=404, detail="Archetype not found")
    return {"id": a.id, "name": a.name, "role": a.role, "summary": archetype_summary(a.profile or {}), "profile": a.profile, "created_at": a.created_at}


@router.delete("/{archetype_id}", status_code=204)
async def delete_archetype(archetype_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    a = (await db.execute(select(Archetype).where(Archetype.id == archetype_id))).scalar_one_or_none()
    if not a or not owns(a, user):
        raise HTTPException(status_code=404, detail="Archetype not found")
    await db.delete(a)
    await db.commit()
