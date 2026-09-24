import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from typing import Any, Optional
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.preset import AgentPreset
from app.models.agent import SpawnedAgent
from app.core.auth import AuthUser, get_current_user, get_owned_session, owns
from app.services.agents.agent_builder import AuthoredAgentError, normalise_authored_agent

router = APIRouter(prefix="/presets", tags=["presets"])


class SavePresetRequest(BaseModel):
    session_id: str
    name: str


class PresetResponse(BaseModel):
    id: str
    name: str
    agent_count: int
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=list[PresetResponse])
async def list_presets(user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    q = select(AgentPreset).order_by(AgentPreset.created_at.desc())
    if not user.is_dev:
        q = q.where(AgentPreset.user_id == user.id)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("", response_model=PresetResponse)
async def save_preset(body: SavePresetRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(body.session_id, user, db)
    result = await db.execute(
        select(SpawnedAgent).where(SpawnedAgent.session_id == body.session_id)
    )
    agents = result.scalars().all()
    if not agents:
        raise HTTPException(status_code=400, detail="No agents in session to save")

    agent_profiles = [
        {
            "name": a.name,
            "age": a.age,
            "role": a.role,
            "background": a.background,
            "stance": a.stance.value if hasattr(a.stance, "value") else str(a.stance),
            "correlation": a.correlation,
            "personality": a.personality,
            "debate_style": a.debate_style,
            "energy": a.energy,
            "avatar_color": a.avatar_color,
            "dials": a.dials,
            "humanity": getattr(a, "humanity", 0) or 0,
            "segment": getattr(a, "segment", None),
            "demographics": getattr(a, "demographics", None) or {},
            "character": getattr(a, "character", None),
        }
        for a in agents
    ]

    preset = AgentPreset(
        id=str(uuid.uuid4()),
        user_id=None if user.is_dev else user.id,
        name=body.name.strip(),
        agent_count=len(agents),
        agents=agent_profiles,
    )
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.delete("/{preset_id}", status_code=204)
async def delete_preset(preset_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentPreset).where(AgentPreset.id == preset_id))
    preset = result.scalar_one_or_none()
    if not preset or not owns(preset, user):
        raise HTTPException(status_code=404, detail="Preset not found")
    await db.delete(preset)
    await db.commit()


# ── Hand-authored agents (Agent Builder) ─────────────────────────────────────
# An authored twin is never stored loose: it joins a lineup, new or existing.

class AuthoredAgentsRequest(BaseModel):
    agents: list[dict[str, Any]]
    name: Optional[str] = None  # new lineup only


def _normalise_all(raw: list[dict], taken_colors: list[str]) -> list[dict]:
    if not raw:
        raise HTTPException(status_code=400, detail="No agents to save")
    if len(raw) > 100:
        raise HTTPException(status_code=400, detail="Save at most 100 agents at a time")
    out: list[dict] = []
    for d in raw:
        try:
            prof = normalise_authored_agent(d, taken_colors=taken_colors)
        except AuthoredAgentError as e:
            raise HTTPException(status_code=400, detail=str(e))
        taken_colors = taken_colors + [prof["avatar_color"]]
        out.append(prof)
    return out


@router.get("/{preset_id}")
async def get_preset(preset_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """One lineup with the agents in it (the list endpoint carries only the header)."""
    result = await db.execute(select(AgentPreset).where(AgentPreset.id == preset_id))
    preset = result.scalar_one_or_none()
    if not preset or not owns(preset, user):
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"id": preset.id, "name": preset.name, "agent_count": preset.agent_count, "created_at": preset.created_at, "agents": list(preset.agents or [])}


@router.post("/custom", response_model=PresetResponse)
async def create_custom_preset(body: AuthoredAgentsRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """A new lineup made only of hand-authored agents."""
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name the new lineup")
    profiles = _normalise_all(body.agents, [])
    preset = AgentPreset(id=str(uuid.uuid4()), user_id=None if user.is_dev else user.id, name=name[:100], agent_count=len(profiles), agents=profiles)
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.post("/{preset_id}/agents", response_model=PresetResponse)
async def add_agents_to_preset(preset_id: str, body: AuthoredAgentsRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Append hand-authored agents to an existing lineup. Names already in the lineup are refused
    so a twin stays one person (brief L3-03)."""
    result = await db.execute(select(AgentPreset).where(AgentPreset.id == preset_id))
    preset = result.scalar_one_or_none()
    if not preset or not owns(preset, user):
        raise HTTPException(status_code=404, detail="Preset not found")
    existing = list(preset.agents or [])
    taken_names = {str(a.get("name", "")).strip().lower() for a in existing}
    profiles = _normalise_all(body.agents, [str(a.get("avatar_color", "")) for a in existing])
    for prof in profiles:
        if prof["name"].lower() in taken_names:
            raise HTTPException(status_code=409, detail=f"{prof['name']} is already in this lineup — give the new agent a different name")
        taken_names.add(prof["name"].lower())
    preset.agents = existing + profiles
    preset.agent_count = len(preset.agents)
    await db.commit()
    await db.refresh(preset)
    return preset
