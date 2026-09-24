import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, Enum as SAEnum, Uuid, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
import enum


class SessionStatus(str, enum.Enum):
    CREATED = "created"
    INGESTING = "ingesting"
    READY = "ready"
    SIMULATING = "simulating"
    PAUSED = "paused"
    COMPLETE = "complete"
    ERROR = "error"


class AnalysisSession(Base):
    __tablename__ = "analysis_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Owner (Supabase auth user id). Nullable for rows created before auth / in dev mode.
    user_id: Mapped[Optional[str]] = mapped_column(Uuid(as_uuid=False), nullable=True, index=True, default=None)
    title: Mapped[str] = mapped_column(String(255))
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[SessionStatus] = mapped_column(SAEnum(SessionStatus), default=SessionStatus.CREATED)
    agent_count: Mapped[int] = mapped_column(default=0)
    # Dynamic dials (brief L3-04): the question-specific dials the model chose for this session —
    # [{key, label, why, low, high}]. Every twin carries a 0-10 value per dial under dials["dynamic"].
    dynamic_dials: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
