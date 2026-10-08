"""Segmentation playbooks: the analyst's own method for building a population, as markdown.

Read (parse) a playbook into what the Studio understood, turn an edited one back into markdown,
and keep a shared library. Every signed-in user sees every playbook — there is no
multi-tenancy yet; the author is recorded. A build uses one through `constraints.playbook`."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, get_current_user
from app.core.database import get_db
from app.models.population import Playbook
from app.services.population import playbook as pb_mod

router = APIRouter(prefix="/playbooks", tags=["playbooks"])

MAX_CHARS = 60_000


class ParseRequest(BaseModel):
    markdown: str


class RenderRequest(BaseModel):
    playbook: dict


class SaveRequest(BaseModel):
    markdown: Optional[str] = None
    playbook: Optional[dict] = None     # an edited "what I understood"; wins over markdown


def _row_summary(p: Playbook, user: AuthUser) -> dict:
    parsed = p.parsed or {}
    return {"id": p.id, "title": p.title, "author": p.author, "mine": bool(p.user_id and p.user_id == user.id),
            "approach": (parsed.get("approach") or {}).get("primary"), "population": parsed.get("population") or "",
            "segments": len(parsed.get("segments") or []), "variables": len(parsed.get("variables") or []),
            "created_at": p.created_at, "updated_at": p.updated_at}


def _full(p: Playbook, user: AuthUser) -> dict:
    return {**_row_summary(p, user), "markdown": p.markdown, "playbook": {**(p.parsed or {}), "id": p.id}}


@router.get("/template")
async def get_template(user: AuthUser = Depends(get_current_user)):
    """The blank template and a filled-in example, for the Download buttons."""
    return {"template": pb_mod.template(), "example": pb_mod.example()}


@router.post("/parse")
async def parse(body: ParseRequest, user: AuthUser = Depends(get_current_user)):
    """What the Studio understood from a playbook: approach, segments, variables (with where each
    lives and which standard dials it pushes), rules. Nothing is saved."""
    md = (body.markdown or "").strip()
    if not md:
        raise HTTPException(status_code=400, detail="The playbook is empty")
    if len(md) > MAX_CHARS:
        raise HTTPException(status_code=400, detail=f"The playbook is too long ({len(md):,} characters; the limit is {MAX_CHARS:,})")
    parsed = await pb_mod.parse(md)
    return {"playbook": parsed, "markdown": md, "dial_paths": pb_mod.FIXED_PATHS}


@router.post("/render")
async def render(body: RenderRequest, user: AuthUser = Depends(get_current_user)):
    """An edited playbook back to markdown (for Download after editing what the Studio understood)."""
    pb = pb_mod.normalise(body.playbook)
    return {"playbook": pb, "markdown": pb_mod.to_markdown(pb)}


@router.get("/dials")
async def dial_paths(user: AuthUser = Depends(get_current_user)):
    """Every fixed dial a variable can push, as group.key."""
    return {"dial_paths": pb_mod.FIXED_PATHS}


@router.get("")
async def list_playbooks(user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Playbook).order_by(Playbook.updated_at.desc()))).scalars().all()
    return {"playbooks": [_row_summary(p, user) for p in rows]}


@router.get("/{playbook_id}")
async def get_playbook(playbook_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = (await db.execute(select(Playbook).where(Playbook.id == playbook_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return _full(p, user)


async def _parsed_from(body: SaveRequest) -> tuple[dict, str]:
    if body.playbook:
        pb = pb_mod.normalise(body.playbook)
        pb["parsed_by"] = body.playbook.get("parsed_by") or "edited"
        return pb, pb_mod.to_markdown(pb)
    md = (body.markdown or "").strip()
    if not md:
        raise HTTPException(status_code=400, detail="Send the markdown or the edited playbook")
    if len(md) > MAX_CHARS:
        raise HTTPException(status_code=400, detail="The playbook is too long")
    return await pb_mod.parse(md), md


@router.post("")
async def save_playbook(body: SaveRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    pb, md = await _parsed_from(body)
    p = Playbook(user_id=None if user.is_dev else user.id, author=pb.get("author") or (user.email or ""), title=pb["title"], markdown=md, parsed=pb)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return _full(p, user)


@router.put("/{playbook_id}")
async def update_playbook(playbook_id: str, body: SaveRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = (await db.execute(select(Playbook).where(Playbook.id == playbook_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Playbook not found")
    pb, md = await _parsed_from(body)
    p.title, p.markdown, p.parsed, p.updated_at = pb["title"], md, pb, datetime.utcnow()
    if pb.get("author"):
        p.author = pb["author"]
    await db.commit()
    await db.refresh(p)
    return _full(p, user)


@router.delete("/{playbook_id}")
async def delete_playbook(playbook_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = (await db.execute(select(Playbook).where(Playbook.id == playbook_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Playbook not found")
    await db.delete(p)
    await db.commit()
    return {"deleted": True}
