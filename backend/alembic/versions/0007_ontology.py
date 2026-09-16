"""Typed ontology over the session knowledge graph: kg_graphs.ontology (brief L1-03).

Revision ID: 0007_ontology
Revises: 0006_population
Create Date: 2026-09-16
"""
from alembic import op

from app.core.migrations import run_script

revision = "0007_ontology"
down_revision = "0006_population"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
alter table public.kg_graphs add column if not exists ontology jsonb;
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("alter table public.kg_graphs drop column if exists ontology")
