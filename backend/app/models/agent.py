import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Float, DateTime, Enum as SAEnum, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
import enum


class AgentStance(str, enum.Enum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    NEUTRAL = "neutral"


class SpawnedAgent(Base):
    __tablename__ = "spawned_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(100))
    age: Mapped[int] = mapped_column(default=30)
    role: Mapped[str] = mapped_column(String(150))
    background: Mapped[str] = mapped_column(Text)
    stance: Mapped[AgentStance] = mapped_column(SAEnum(AgentStance))
    correlation: Mapped[str] = mapped_column(Text)
    personality: Mapped[list] = mapped_column(JSON)
    debate_style: Mapped[str] = mapped_column(Text)
    energy: Mapped[float] = mapped_column(Float, default=0.5)
    avatar_color: Mapped[str] = mapped_column(String(7), default="#6366f1")
    dials: Mapped[dict] = mapped_column(JSON, nullable=True, default=None)
    # 0 = pure expert/analytical; higher = more human, emotional, gut-driven, less logical.
    humanity: Mapped[int] = mapped_column(default=0)
    # One-line Claude-generated verdict on the session query (Agent Opinions sidebar); None until generated.
    verdict: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    # Population Studio: the plan segment this agent was built from, and the demographics the
    # segment fixed (gender, region, income_band, education, occupation). None for other spawns.
    segment: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, default=None)
    demographics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=None)
    # Scoped retrieval (L1-04): an optional override of the twin's derived exposure profile —
    # any subset of {geography, role, channel, register, condition, stage, segment, time, arm}.
    exposure: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=None)
    # Raking weight to the Studio's sampling frame (1.0 = counts as one person); the Lab's weighted headline reads it.
    weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
