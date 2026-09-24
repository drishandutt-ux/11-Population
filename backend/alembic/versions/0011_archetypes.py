"""Archetypes (brief L3-02): hand-authored twins the Studio casts personas from.

Revision ID: 0011_archetypes
Revises: 0010_character
Create Date: 2026-09-24
"""
from alembic import op

from app.core.migrations import run_script

revision = "0011_archetypes"
down_revision = "0010_character"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
create table if not exists public.archetypes (
  id varchar(36) primary key,
  user_id uuid,
  name varchar(100) not null,
  role varchar(150) not null,
  profile jsonb not null default '{}'::jsonb,
  created_at timestamp not null default now()
);
create index if not exists ix_archetypes_user_id on public.archetypes(user_id);

alter table public.archetypes enable row level security;
drop policy if exists "archetypes: owner" on public.archetypes;
create policy "archetypes: owner" on public.archetypes for all to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("drop table if exists public.archetypes cascade")
