from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"


class Profile(Base):
    """One row per auth user (created by the `on_auth_user_created` trigger on Postgres;
    created lazily by the backend on SQLite dev). `role` is 'admin' for the first account
    that registers and 'member' for everyone after; admins can change roles."""
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(16), default=ROLE_MEMBER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
