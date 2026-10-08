import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Integer, DateTime, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

_JSON = JSON().with_variant(JSONB, "postgresql")


class PopulationBuild(Base):
    """One run of the Population Studio: detect → gather → clarify → plan → review → spawn.

    Everything the user saw while it ran is on the row — the inputs that were detected, the
    questions that were asked and answered, the segment plan with each segment's accept /
    reject / edit decision, and the log — so a reload rebuilds the page and the plan that
    produced a population can always be read back."""

    __tablename__ = "population_builds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    # queued | detecting | gathering | clarifying | planning | awaiting_review | spawning | complete | stopped | error
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    mode: Mapped[str] = mapped_column(String(8), default="fast")          # fast (Haiku) | pro (Sonnet)
    target_count: Mapped[int] = mapped_column(Integer, default=50)
    constraints: Mapped[dict] = mapped_column(_JSON, default=dict)       # the dials
    sources: Mapped[dict] = mapped_column(_JSON, default=dict)           # {quant: bool, quant_sources: [...], quant_query: str}
    detected: Mapped[Optional[dict]] = mapped_column(_JSON, nullable=True)
    questions: Mapped[list] = mapped_column(_JSON, default=list)         # [{id, text, why, suggested, default, answer}]
    plan: Mapped[Optional[dict]] = mapped_column(_JSON, nullable=True)   # {segments: [...], rationale, assumptions, evidence_coverage}
    # The sampling frame (services/population/frame.py): {dimensions[], targets{key: {status, categories, source, …}}, report, geography}
    frame: Mapped[Optional[dict]] = mapped_column(_JSON, nullable=True)
    log: Mapped[list] = mapped_column(_JSON, default=list)               # [{ts, stage, level, message, detail}]
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Playbook(Base):
    """A segmentation playbook (services/population/playbook.py): an analyst's own method for
    cutting a population — approach, segments, extra variables, rules — written as markdown.
    Shared: every signed-in user sees and can use every playbook (no multi-tenancy yet);
    `user_id` / `author` record who wrote it."""

    __tablename__ = "playbooks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True, default=None)
    author: Mapped[str] = mapped_column(String(120), default="")
    title: Mapped[str] = mapped_column(String(160), default="")
    markdown: Mapped[str] = mapped_column(Text, default="")
    parsed: Mapped[dict] = mapped_column(_JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
