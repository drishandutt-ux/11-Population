"""Population Studio: population_builds (detect → clarify → plan → review → spawn runs) and the
segment / demographics an agent was built from.

Revision ID: 0006_population
Revises: 0005_experiments
Create Date: 2026-09-15
"""
from alembic import op

from app.core.migrations import run_script

revision = "0006_population"
down_revision = "0005_experiments"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
create table if not exists public.population_builds (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  status varchar(24) not null default 'queued',
  mode varchar(8) not null default 'fast',
  target_count integer not null default 50,
  constraints jsonb not null default '{}'::jsonb,
  sources jsonb not null default '{}'::jsonb,
  detected jsonb,
  questions jsonb not null default '[]'::jsonb,
  plan jsonb,
  log jsonb not null default '[]'::jsonb,
  error text,
  created_at timestamp not null default now(),
  updated_at timestamp not null default now()
);
create index if not exists ix_population_builds_session_id on public.population_builds(session_id);
create index if not exists ix_population_builds_status on public.population_builds(status);

alter table public.population_builds enable row level security;
drop policy if exists "population_builds: via session owner" on public.population_builds;
create policy "population_builds: via session owner" on public.population_builds for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));

alter table public.spawned_agents add column if not exists segment varchar(120);
alter table public.spawned_agents add column if not exists demographics jsonb;
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("drop table if exists public.population_builds cascade")
    op.execute("alter table public.spawned_agents drop column if exists segment")
    op.execute("alter table public.spawned_agents drop column if exists demographics")
