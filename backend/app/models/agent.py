import uuid
from datetime import datetime
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
