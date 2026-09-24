from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.agent import SpawnedAgent
from app.models.session import AnalysisSession
from app.core.auth import AuthUser, get_current_user, get_owned_session, owns

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


async def _owned_agent(agent_id: str, user: AuthUser, db: AsyncSession) -> SpawnedAgent:
    result = await db.execute(select(SpawnedAgent).where(SpawnedAgent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    sess = (await db.execute(select(AnalysisSession).where(AnalysisSession.id == agent.session_id))).scalar_one_or_none()
    if not sess or not owns(sess, user):
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("/sessions/{session_id}/agents", response_model=list)
async def list_agents(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
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
            "humanity": getattr(a, "humanity", 0) or 0,
            "verdict": getattr(a, "verdict", None),
            "segment": getattr(a, "segment", None),
            "demographics": getattr(a, "demographics", None) or {},
            "weight": getattr(a, "weight", None) or 1.0,
            "character": getattr(a, "character", None),
        }
        for a in agents
    ]


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    agent = await _owned_agent(agent_id, user, db)
    return {
        "id": agent.id, "session_id": agent.session_id, "name": agent.name,
        "age": agent.age, "role": agent.role, "background": agent.background,
        "stance": agent.stance, "correlation": agent.correlation,
        "personality": agent.personality, "debate_style": agent.debate_style,
        "energy": agent.energy, "avatar_color": agent.avatar_color,
        "dials": agent.dials or {},
        "humanity": getattr(agent, "humanity", 0) or 0,
        "verdict": getattr(agent, "verdict", None),
        "segment": getattr(agent, "segment", None),
        "demographics": getattr(agent, "demographics", None) or {},
        "character": getattr(agent, "character", None),
    }


class BuildProfileRequest(BaseModel):
    """The Agent Builder draft: text fields plus `dials` holding only the values the analyst fixed."""
    agent: dict


@router.post("/sessions/{session_id}/agent-builder/profile")
async def build_agent_profile(session_id: str, body: BuildProfileRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Build sentiment profile: read what the analyst wrote and tune every dial they left to the
    system, relative to this session's query. Fixed dials come back unchanged."""
    from app.services.agents.agent_builder import build_profile
    from app.services.evidence.llm import LlmError

    session = await get_owned_session(session_id, user, db)
    try:
        return await build_profile(session_id, session.query, body.agent or {})
    except LlmError as e:
        raise HTTPException(status_code=502, detail=f"The model could not build the profile: {e}")


@router.post("/agents/{agent_id}/chat")
async def chat_with_agent(
    agent_id: str,
    body: ChatRequest,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await _owned_agent(agent_id, user, db)

    from app.services.agents.agent_runner import chat_as_agent
    from app.services.knowledge_graph.lightrag_service import get_kg_context_string, get_lightrag
    await get_lightrag(agent.session_id)  # warm the KG cache (DB-backed)
    kg_context = get_kg_context_string(agent.session_id)
    from app.services.scoping import service as scoping
    if await scoping.is_scoped(agent.session_id):
        session_row = await db.get(AnalysisSession, agent.session_id)
        kg_context = (await scoping.context_for_agent(agent.session_id, agent, session_row.query if session_row else "", purpose="chat")) or kg_context
    history = _agent_conversations.setdefault(agent_id, [])
    reply = await chat_as_agent(agent, body.message, history, kg_context)
    history.append({"role": "user", "content": body.message})
    history.append({"role": "assistant", "content": reply})
    return {"agent_id": agent_id, "reply": reply, "history": history}
