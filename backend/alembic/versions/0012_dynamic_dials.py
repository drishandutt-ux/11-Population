"""Dynamic dials (brief L3-04): the question-specific dials chosen per session.

Revision ID: 0012_dynamic_dials
Revises: 0011_archetypes
Create Date: 2026-09-24
"""
from alembic import op

from app.core.migrations import run_script

revision = "0012_dynamic_dials"
down_revision = "0011_archetypes"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
alter table public.analysis_sessions add column if not exists dynamic_dials jsonb;
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("alter table public.analysis_sessions drop column if exists dynamic_dials")
