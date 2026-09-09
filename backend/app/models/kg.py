from datetime import datetime
from sqlalchemy import String, DateTime, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

# Portable JSON: jsonb on Postgres, plain JSON text on SQLite.
_JSON = JSON().with_variant(JSONB, "postgresql")


class KnowledgeGraph(Base):
    """One knowledge graph per session: entities, [head, verb, tail] relations, and the
    last ~200 source chunks. Replaces the per-session kg.json files that lived on the
    (ephemeral) filesystem."""
    __tablename__ = "kg_graphs"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entities: Mapped[list] = mapped_column(_JSON, default=list)
    relations: Mapped[list] = mapped_column(_JSON, default=list)
    chunks: Mapped[list] = mapped_column(_JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
