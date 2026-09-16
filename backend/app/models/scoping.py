"""Scoped retrieval (brief L1-04): facet-tagged knowledge, stacked policies, and the log of
what each twin was shown.

  knowledge_units  — one row per unit of knowledge (a graph chunk today, a claim later) with
                     its provenance class, trust tier and a facet map keyed by dimension
                     (geography, role, channel, condition, stage, segment, register, time …).
                     Facet values are ontology node ids, so the ontology is the vocabulary.
  scope_policies   — a versioned list of rules per session layer (project | session | run).
                     The highest version per (session, layer) is the active one.
  retrievals       — which units a twin was served, under which policy version and snapshot,
                     for which purpose. This is the twin_refs / evidence_refs trail the TPO
                     schema needs and the reproducibility L5-05 asks for.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, DateTime, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

_JSON = JSON().with_variant(JSONB, "postgresql")


class KnowledgeUnit(Base):
    __tablename__ = "knowledge_units"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(36), index=True)      # the tagging run this unit belongs to
    text: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str] = mapped_column(String(400), default="")       # the [SOURCE …] header, or "debate: <name>"
    provenance_class: Mapped[str] = mapped_column(String(32), default="grey_literature")
    trust_tier: Mapped[str] = mapped_column(String(8), default="medium")   # high | medium | low
    facets: Mapped[dict] = mapped_column(_JSON, default=dict)               # {dimension: [values] | value}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ScopePolicy(Base):
    __tablename__ = "scope_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    layer: Mapped[str] = mapped_column(String(16), default="session")      # project | session | run
    version: Mapped[int] = mapped_column(Integer, default=1)
    rules: Mapped[list] = mapped_column(_JSON, default=list)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Retrieval(Base):
    __tablename__ = "retrievals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    agent_id: Mapped[str] = mapped_column(String(36), index=True)
    purpose: Mapped[str] = mapped_column(String(16), default="post")       # post | probe | chat | preview
    snapshot_id: Mapped[str] = mapped_column(String(36), default="")
    policy_version: Mapped[int] = mapped_column(Integer, default=0)
    unit_ids: Mapped[list] = mapped_column(_JSON, default=list)
    routes: Mapped[list] = mapped_column(_JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
