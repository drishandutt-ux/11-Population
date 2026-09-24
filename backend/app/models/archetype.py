import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Archetype(Base):
    """A hand-authored twin promoted to a mould the Population Studio casts personas from
    (brief L3-02). `profile` is the full authored profile (background, character, dials,
    humanity, debate style, personality, stance, demographics) as the Agent Builder saved it."""
    __tablename__ = "archetypes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(Uuid(as_uuid=False), nullable=True, index=True, default=None)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(150))
    profile: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
