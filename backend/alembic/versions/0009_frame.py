"""The sampling frame (brief L2-01…L2-05): population_builds.frame and spawned_agents.weight.

Revision ID: 0009_frame
Revises: 0008_scoping
Create Date: 2026-09-16
"""
from alembic import op

from app.core.migrations import run_script

revision = "0009_frame"
down_revision = "0008_scoping"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
alter table public.population_builds add column if not exists frame jsonb;
alter table public.spawned_agents add column if not exists weight double precision default 1.0;
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("alter table public.population_builds drop column if exists frame")
    op.execute("alter table public.spawned_agents drop column if exists weight")
