"""LLM usage ledger (2026-10-22): one row per Anthropic call, read by the admin Tokens & cost page.

Tokens come straight off the SDK response (exact, not estimated); cost is priced at write time
from `app.core.pricing`. `session_id` is deliberately not a foreign key, so spend stays on the
books after a session is deleted.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LlmUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)  # null → not tied to a session
    label: Mapped[str] = mapped_column(String(80), default="")          # what the call was for: post, opinions, kg_extract …
    model: Mapped[str] = mapped_column(String(80), default="unknown")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    web_search_requests: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    priced: Mapped[int] = mapped_column(Integer, default=1)             # 0 → model not in the price table, cost is an estimate
    elapsed_sec: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="success")  # success | error
