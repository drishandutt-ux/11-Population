"""The bin (2026-10-22): a deleted session is stamped, restorable for 30 days, then purged.

Revision ID: 0023_session_trash
Revises: 0022_llm_usage
Create Date: 2026-10-22
"""
from alembic import op

from app.core.migrations import run_script

revision = "0023_session_trash"
down_revision = "0022_llm_usage"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
alter table public.analysis_sessions add column if not exists deleted_at timestamp;
create index if not exists ix_analysis_sessions_deleted_at on public.analysis_sessions(deleted_at);
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("drop index if exists public.ix_analysis_sessions_deleted_at")
    op.execute("alter table public.analysis_sessions drop column if exists deleted_at")
