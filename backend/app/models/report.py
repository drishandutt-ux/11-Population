import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

_JSON = JSON().with_variant(JSONB, "postgresql")


class ReportQuery(Base):
    __tablename__ = "report_queries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    sources: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The wired parts of the report proper (brief L6-02): computed confidence band, evidence by
    # class, positions + named dissent, the records' caveats. NULL for Ask-Report follow-ups.
    structure: Mapped[Optional[dict]] = mapped_column(_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
