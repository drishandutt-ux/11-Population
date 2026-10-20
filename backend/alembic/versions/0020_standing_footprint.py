"""Standing-based scoping (2026-10-20): who each twin is to the topic, and what every post was
spoken from.

Revision ID: 0020_standing_footprint
Revises: 0019_playbooks
Create Date: 2026-10-20
"""
from alembic import op

from app.core.migrations import run_script

revision = "0020_standing_footprint"
down_revision = "0019_playbooks"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
alter table public.spawned_agents add column if not exists standing jsonb;
alter table public.simulation_posts add column if not exists footprint jsonb;
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("alter table public.simulation_posts drop column if exists footprint")
    op.execute("alter table public.spawned_agents drop column if exists standing")
