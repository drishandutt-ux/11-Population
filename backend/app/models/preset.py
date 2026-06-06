import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class AgentPreset(Base):
    __tablename__ = "agent_presets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100))
    agent_count: Mapped[int] = mapped_column(Integer, default=0)
    # JSON array of agent profile dicts (all fields except id/session_id/created_at)
    agents: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
