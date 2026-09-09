import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Integer, Float, Boolean, DateTime, JSON, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

_JSON = JSON().with_variant(JSONB, "postgresql")


class ResearchRun(Base):
    """One auto-research job for a session: frame → plan → search/read/judge rounds → brief."""
    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")   # queued | running | stopping | complete | stopped | interrupted | error
    question: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(_JSON, default=list)          # ["web", "reddit"]
    frame: Mapped[Optional[dict]] = mapped_column(_JSON, nullable=True)
    plan: Mapped[Optional[dict]] = mapped_column(_JSON, nullable=True)
    verdicts: Mapped[list] = mapped_column(_JSON, default=list)         # per round/attempt notes
    covered: Mapped[list] = mapped_column(_JSON, default=list)          # sub-question ids satisfied
    budget: Mapped[dict] = mapped_column(_JSON, default=dict)           # caps + used counters
    brief: Mapped[Optional[dict]] = mapped_column(_JSON, nullable=True) # evidence brief (stakeholders, stances, quotes)
    recommendations: Mapped[Optional[list]] = mapped_column(_JSON, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ResearchQuery(Base):
    """One query executed by a run (web round or Reddit attempt), for the live plan panel."""
    __tablename__ = "research_queries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    source: Mapped[str] = mapped_column(String(16))                    # web | reddit
    query: Mapped[str] = mapped_column(Text)
    round_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | running | done | error
    engine: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    results: Mapped[int] = mapped_column(Integer, default=0)
    read: Mapped[int] = mapped_column(Integer, default=0)
    on_topic: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Evidence(Base):
    """One evidence item: a web page or a social post. One shape for every source."""
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    source_class: Mapped[str] = mapped_column(String(16))               # web | social | personal | synthetic
    source_ref: Mapped[str] = mapped_column(Text)                        # URL or platform post id
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # domain, u/handle, …
    published_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    text: Mapped[str] = mapped_column(Text)                              # excerpt shown in the feed
    full_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    structured: Mapped[dict] = mapped_column(_JSON, default=dict)        # source-specific payload (comments, scores, provider…)
    trust_tier: Mapped[str] = mapped_column(String(16), default="medium")
    relevance: Mapped[float] = mapped_column(Float, default=0.0)
    on_topic: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)       # user removed it from graph/personas
    in_graph: Mapped[bool] = mapped_column(Boolean, default=False)
    query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    sub_questions: Mapped[list] = mapped_column(_JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


Index("ix_evidence_session_on_topic", Evidence.session_id, Evidence.on_topic)
