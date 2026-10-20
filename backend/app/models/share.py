"""Sharing (2026-10-20): a session shared with colleagues in the same email domain, and the chat
those people hold around it (with the report agent on `@report`).

  session_shares   — one row per (session, user it is shared with); the owner is never a row
  shared_messages  — the chat: a person's message (user_id set) or the report agent's reply
                     (user_id null, kind "report")
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SessionShare(Base):
    __tablename__ = "session_shares"
    __table_args__ = (UniqueConstraint("session_id", "user_id", name="uq_session_share"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), index=True)        # the colleague the session is shared with
    shared_by: Mapped[Optional[str]] = mapped_column(Uuid(as_uuid=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SharedMessage(Base):
    __tablename__ = "shared_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(Uuid(as_uuid=False), nullable=True, index=True)   # null → the report agent
    author_name: Mapped[str] = mapped_column(String(160), default="")
    kind: Mapped[str] = mapped_column(String(16), default="user")                 # user | report
    content: Mapped[str] = mapped_column(Text, default="")
    reply_to: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)   # the message an @report answer replies to
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
