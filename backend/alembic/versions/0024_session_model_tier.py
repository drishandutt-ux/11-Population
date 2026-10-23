"""Model tier per session (2026-10-23): "fast" runs every LLM call on Haiku, "pro" on Sonnet.

Revision ID: 0024_session_model_tier
Revises: 0023_session_trash
Create Date: 2026-10-23
"""
from alembic import op

from app.core.migrations import run_script

revision = "0024_session_model_tier"
down_revision = "0023_session_trash"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
alter table public.analysis_sessions add column if not exists model_tier varchar(8) not null default 'fast';
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("alter table public.analysis_sessions drop column if exists model_tier")
