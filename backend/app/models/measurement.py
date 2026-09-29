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


class Experiment(Base):
    """An A/B/n test: one instrument run once per variant, on the same agents (within-subjects,
    paired) or on a seeded split of the population (between-subjects). The arms are ordinary
    probes carrying this row's id, so every arm is a full probe result in its own right; what
    lives here is the comparison — lift per metric with an interval, who flipped and why, the
    segment map and the verdict."""

    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    design: Mapped[str] = mapped_column(String(16), default="within")  # within | between
    instrument: Mapped[str] = mapped_column(String(48), index=True)
    # [{key, label, spec}] in order; the first is the control.
    variants: Mapped[list] = mapped_column(JSON, default=list)
    # Shared across arms: agent_filter, context policy.
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|running|complete|failed|stopped
    agent_count: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=None)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None)


class CalibrationMapping(Base):
    """A calibration rule (brief L4-02, the minimum of it): what evidence shows a lever does to
    behaviour — which twins it covers, which dials it moves and by how much, the evidence and
    who reviewed it. The lever simulation (L7-04) runs only against a reviewed rule."""
    __tablename__ = "calibration_mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    lever: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    applies_to: Mapped[dict] = mapped_column(JSON, default=dict)        # {segment_key: [values]}; {} = everyone
    deltas: Mapped[dict] = mapped_column(JSON, default=dict)            # {"friction.time_cost": -3}
    bound: Mapped[int] = mapped_column(Integer, default=4)
    evidence: Mapped[list] = mapped_column(JSON, default=list)          # [{ref, note}]
    basis: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)   # draft | reviewed
    reviewed_by: Mapped[str] = mapped_column(String(120), default="")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Commitment(Base):
    """A commitment record (brief L7-08): when a client picks a candidate outcome to pursue, the
    modelled baseline is frozen here — the candidate as it stood, the population build, the frame
    and weights, the evidence on file, every calibration rule, the runs on it, the model and seed
    and the synthetic statement — as a copy, never a pointer, so later work in the session cannot
    change what was promised. Observed results are entered by hand later, with a source, and
    compared against the frozen forecast. A commitment is never edited: it is closed or superseded."""
    __tablename__ = "commitments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    journey_probe_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(160))
    label: Mapped[str] = mapped_column(String(300), default="")
    committed_by: Mapped[str] = mapped_column(String(120), default="")
    committed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    target: Mapped[dict] = mapped_column(JSON, default=dict)             # {value (share 0–1), horizon, note}
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)   # open | closed | superseded
    superseded_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, default=None)
    closed_by: Mapped[str] = mapped_column(String(120), default="")
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None)
    close_note: Mapped[str] = mapped_column(Text, default="")
    baseline: Mapped[dict] = mapped_column(JSON, default=dict)           # the frozen modelled baseline (see commitments.build_baseline)
    observed: Mapped[list] = mapped_column(JSON, default=list)           # [{value, low, high, source, date, entered_by, entered_at, note}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
