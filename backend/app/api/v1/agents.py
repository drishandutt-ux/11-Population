from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.agent import SpawnedAgent

router = APIRouter(tags=["agents"])

_agent_conversations: dict = {}


class AgentResponse(BaseModel):
    id: str
    session_id: str
    name: str
    age: int
    role: str
    background: str
    stance: str
    correlation: str
    personality: list
    debate_style: str
    energy: float
    avatar_color: str

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    agent_id: str
    reply: str
    history: list


@router.get("/sessions/{session_id}/agents", response_model=list)
async def list_agents(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SpawnedAgent).where(SpawnedAgent.session_id == session_id)
    )
    agents = result.scalars().all()
    return [
        {
            "id": a.id, "session_id": a.session_id, "name": a.name,
            "age": a.age, "role": a.role, "background": a.background,
            "stance": a.stance, "correlation": a.correlation,
            "personality": a.personality, "debate_style": a.debate_style,
            "energy": a.energy, "avatar_color": a.avatar_color,
            "dials": a.dials or {},
        }
        for a in agents
    ]


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SpawnedAgent).where(SpawnedAgent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {
        "id": agent.id, "session_id": agent.session_id, "name": agent.name,
        "age": agent.age, "role": agent.role, "background": agent.background,
        "stance": agent.stance, "correlation": agent.correlation,
        "personality": agent.personality, "debate_style": agent.debate_style,
        "energy": agent.energy, "avatar_color": agent.avatar_color,
        "dials": agent.dials or {},
    }


@router.post("/agents/{agent_id}/chat")
async def chat_with_agent(
    agent_id: str,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SpawnedAgent).where(SpawnedAgent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    from app.services.agents.agent_runner import chat_as_agent
    from app.services.knowledge_graph.lightrag_service import get_kg_context_string
    kg_context = get_kg_context_string(agent.session_id)
    history = _agent_conversations.setdefault(agent_id, [])
    reply = await chat_as_agent(agent, body.message, history, kg_context)
    history.append({"role": "user", "content": body.message})
    history.append({"role": "assistant", "content": reply})
    return {"agent_id": agent_id, "reply": reply, "history": history}
