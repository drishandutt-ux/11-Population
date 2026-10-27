"""Benchmark runs (2026-10-27): the SimBench grouped subset run — its state, scores and summary —
and a `kind` on sessions so the hundreds of subgroup lineups a run builds stay out of the session list.

Revision ID: 0026_benchmark_runs
Revises: 0025_session_images
Create Date: 2026-10-27
"""
from alembic import op

from app.core.migrations import run_script

revision = "0026_benchmark_runs"
down_revision = "0025_session_images"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
create table if not exists public.benchmark_runs (
  id varchar(36) primary key,
  user_id varchar(36),
  benchmark varchar(40) not null default 'simbench_grouped',
  status varchar(16) not null default 'queued',
  config jsonb not null default '{}'::jsonb,
  state jsonb not null default '{}'::jsonb,
  progress jsonb not null default '{}'::jsonb,
  summary jsonb,
  error text,
  created_at timestamp not null default now(),
  updated_at timestamp not null default now(),
  completed_at timestamp
);
create index if not exists ix_benchmark_runs_user_id on public.benchmark_runs (user_id);
create index if not exists ix_benchmark_runs_benchmark on public.benchmark_runs (benchmark);
create index if not exists ix_benchmark_runs_status on public.benchmark_runs (status);
alter table public.analysis_sessions add column if not exists kind varchar(16) not null default 'session';
create index if not exists ix_analysis_sessions_kind on public.analysis_sessions (kind);
"""

DOWNGRADE_SQL = r"""
drop index if exists public.ix_analysis_sessions_kind;
alter table public.analysis_sessions drop column if exists kind;
drop table if exists public.benchmark_runs;
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    run_script(DOWNGRADE_SQL)
