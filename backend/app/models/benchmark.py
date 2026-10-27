"""Public benchmark runs (2026-10-27): one row per attempt at a published test — SimBench grouped first.

The row is the durable record of a run that takes hours and survives redeploys: which cases it
covers, which session holds each subgroup's lineup, which probe answered each case, every score,
and the summary. A restart marks a running row `interrupted`; resume continues from the state."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

_JSON = JSON().with_variant(JSONB, "postgresql")


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True, default=None)
    benchmark: Mapped[str] = mapped_column(String(40), default="simbench_grouped", index=True)
    # queued | running | stopping | stopped | interrupted | complete | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    config: Mapped[dict] = mapped_column(_JSON, default=dict)      # cases, twins, mode, seed, parallel_groups, bare
    state: Mapped[dict] = mapped_column(_JSON, default=dict)       # groups {gid: {...}}, cases {cid: {...}}
    progress: Mapped[dict] = mapped_column(_JSON, default=dict)    # counts for the page
    summary: Mapped[Optional[dict]] = mapped_column(_JSON, nullable=True, default=None)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None)
