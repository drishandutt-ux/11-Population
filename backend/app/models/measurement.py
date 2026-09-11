import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Integer, Float, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Probe(Base):
    """One run of one instrument against one set of agents.

    Everything needed to reproduce the run is stored on the row — seed, model, schema id and a
    hash of the rendered prompt — so the same spec on the same population reproduces to the
    model's own variance, and that variance can be measured rather than assumed."""

    __tablename__ = "probes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    instrument: Mapped[str] = mapped_column(String(48), index=True)
    schema_id: Mapped[str] = mapped_column(String(64), default="")
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    # Set when the probe is one arm of an A/B experiment; None for a standalone run.
    experiment_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    variant_key: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_hash: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|running|complete|failed|stopped
    agent_count: Mapped[int] = mapped_column(Integer, default=0)
    answer_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    aggregates: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=None)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None)


class ProbeAnswer(Base):
    """One typed answer from one agent. The unit the whole Lab aggregates over."""

    __tablename__ = "probe_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    probe_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    agent_id: Mapped[str] = mapped_column(String(36), index=True)
    answer: Mapped[dict] = mapped_column(JSON, default=dict)
    # Denormalised out of `answer` so the reasoning can be searched and quoted cheaply.
    reasoning: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
