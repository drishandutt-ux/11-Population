"""Scoping wired end to end (brief L1-04): what each twin was written from and can see.

Revision ID: 0015_agent_knowledge
Revises: 0014_report_structure
Create Date: 2026-09-28
"""
from alembic import op

from app.core.migrations import run_script

revision = "0015_agent_knowledge"
down_revision = "0014_report_structure"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
alter table public.spawned_agents add column if not exists knowledge jsonb;
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("alter table public.spawned_agents drop column if exists knowledge")
