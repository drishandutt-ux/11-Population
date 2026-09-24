"""Hand-authored character on a twin (Agent Builder): spawned_agents.character.

Revision ID: 0010_character
Revises: 0009_frame
Create Date: 2026-09-24
"""
from alembic import op

from app.core.migrations import run_script

revision = "0010_character"
down_revision = "0009_frame"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
alter table public.spawned_agents add column if not exists character jsonb;
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("alter table public.spawned_agents drop column if exists character")
