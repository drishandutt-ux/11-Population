"""Segmentation playbooks: an analyst's own method for building a population, as markdown,
shared across all signed-in users (no multi-tenancy yet).

Revision ID: 0019_playbooks
Revises: 0018_lab_briefs
Create Date: 2026-10-08
"""
from alembic import op

from app.core.migrations import run_script

revision = "0019_playbooks"
down_revision = "0018_lab_briefs"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
create table if not exists public.playbooks (
  id varchar(36) primary key,
  user_id varchar(36),
  author varchar(120) not null default '',
  title varchar(160) not null default '',
  markdown text not null default '',
  parsed jsonb not null default '{}'::jsonb,
  created_at timestamp not null default now(),
  updated_at timestamp not null default now()
);
create index if not exists ix_playbooks_user_id on public.playbooks(user_id);

alter table public.playbooks enable row level security;
drop policy if exists "playbooks: shared" on public.playbooks;
create policy "playbooks: shared" on public.playbooks for all to authenticated
  using (true)
  with check (true);
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("drop table if exists public.playbooks cascade")
