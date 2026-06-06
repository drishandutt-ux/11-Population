import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.preset import AgentPreset
from app.models.agent import SpawnedAgent

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
async def list_presets(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AgentPreset).order_by(AgentPreset.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=PresetResponse)
async def save_preset(body: SavePresetRequest, db: AsyncSession = Depends(get_db)):
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
        }
        for a in agents
    ]

    preset = AgentPreset(
        id=str(uuid.uuid4()),
        name=body.name.strip(),
        agent_count=len(agents),
        agents=agent_profiles,
    )
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.delete("/{preset_id}", status_code=204)
async def delete_preset(preset_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentPreset).where(AgentPreset.id == preset_id))
    preset = result.scalar_one_or_none()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    await db.delete(preset)
    await db.commit()
