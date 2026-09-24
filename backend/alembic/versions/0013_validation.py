"""Behavioural validation (brief L3-05): the battery's score per twin.

Revision ID: 0013_validation
Revises: 0012_dynamic_dials
Create Date: 2026-09-24
"""
from alembic import op

from app.core.migrations import run_script

revision = "0013_validation"
down_revision = "0012_dynamic_dials"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
alter table public.spawned_agents add column if not exists validation jsonb;
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("alter table public.spawned_agents drop column if exists validation")
