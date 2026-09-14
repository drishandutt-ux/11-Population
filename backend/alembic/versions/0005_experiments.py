"""Behaviour Lab: experiments (A/B/n container; arms are probes carrying experiment_id).

Revision ID: 0005_experiments
Revises: 0004_measurement
Create Date: 2026-09-14
"""
from alembic import op

from app.core.migrations import run_script

revision = "0005_experiments"
down_revision = "0004_measurement"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
create table if not exists public.experiments (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  name varchar(160) not null default '',
  design varchar(16) not null default 'within',
  instrument varchar(48) not null,
  variants jsonb not null default '[]'::jsonb,
  spec jsonb not null default '{}'::jsonb,
  seed integer not null default 0,
  model varchar(64) not null default '',
  status varchar(16) not null default 'queued',
  agent_count integer not null default 0,
  results jsonb,
  error text,
  created_at timestamp not null default now(),
  completed_at timestamp
);
create index if not exists ix_experiments_session_id on public.experiments(session_id);
create index if not exists ix_experiments_instrument on public.experiments(instrument);
create index if not exists ix_experiments_status on public.experiments(status);

alter table public.experiments enable row level security;
drop policy if exists "experiments: via session owner" on public.experiments;
create policy "experiments: via session owner" on public.experiments for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));
"""


def upgrade() -> None:
    # One statement at a time: asyncpg rejects a multi-command prepared statement.
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("drop table if exists public.experiments cascade")
