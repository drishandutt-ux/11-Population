"""Report structure (brief L6-02): the wired parts of a report stored beside its prose.

Revision ID: 0014_report_structure
Revises: 0013_validation
Create Date: 2026-09-28
"""
from alembic import op

from app.core.migrations import run_script

revision = "0014_report_structure"
down_revision = "0013_validation"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
alter table public.report_queries add column if not exists structure jsonb;
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("alter table public.report_queries drop column if exists structure")
