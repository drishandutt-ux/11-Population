"""Evidence gathering: research_runs, research_queries, evidence (+ RLS via session owner).

Revision ID: 0003_evidence
Revises: 0002_profile_roles
Create Date: 2026-09-09
"""
from alembic import op

from app.core.migrations import run_script

revision = "0003_evidence"
down_revision = "0002_profile_roles"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
create table if not exists public.research_runs (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  status varchar(16) not null default 'queued',
  question text not null,
  sources jsonb not null default '[]'::jsonb,
  frame jsonb,
  plan jsonb,
  verdicts jsonb not null default '[]'::jsonb,
  covered jsonb not null default '[]'::jsonb,
  budget jsonb not null default '{}'::jsonb,
  brief jsonb,
  recommendations jsonb,
  note text,
  started_at timestamp not null default now(),
  finished_at timestamp
);
create index if not exists ix_research_runs_session_id on public.research_runs(session_id);

create table if not exists public.research_queries (
  id varchar(36) primary key,
  run_id varchar(36) not null references public.research_runs(id) on delete cascade,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  source varchar(16) not null,
  query text not null,
  round_no integer not null default 1,
  status varchar(16) not null default 'queued',
  engine varchar(32),
  results integer not null default 0,
  read integer not null default 0,
  on_topic integer not null default 0,
  note text,
  created_at timestamp not null default now()
);
create index if not exists ix_research_queries_run_id on public.research_queries(run_id);
create index if not exists ix_research_queries_session_id on public.research_queries(session_id);

create table if not exists public.evidence (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  run_id varchar(36) references public.research_runs(id) on delete set null,
  source_class varchar(16) not null,
  source_ref text not null,
  title text,
  author text,
  published_at varchar(40),
  text text not null,
  full_text text,
  structured jsonb not null default '{}'::jsonb,
  trust_tier varchar(16) not null default 'medium',
  relevance double precision not null default 0,
  on_topic boolean not null default false,
  excluded boolean not null default false,
  in_graph boolean not null default false,
  query text,
  attempt integer not null default 1,
  sub_questions jsonb not null default '[]'::jsonb,
  created_at timestamp not null default now()
);
create index if not exists ix_evidence_session_id on public.evidence(session_id);
create index if not exists ix_evidence_run_id on public.evidence(run_id);
create index if not exists ix_evidence_session_on_topic on public.evidence(session_id, on_topic);

alter table public.research_runs enable row level security;
alter table public.research_queries enable row level security;
alter table public.evidence enable row level security;
drop policy if exists "research_runs: via session owner" on public.research_runs;
create policy "research_runs: via session owner" on public.research_runs for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));
drop policy if exists "research_queries: via session owner" on public.research_queries;
create policy "research_queries: via session owner" on public.research_queries for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));
drop policy if exists "evidence: via session owner" on public.evidence;
create policy "evidence: via session owner" on public.evidence for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));
"""


def upgrade() -> None:
    # One statement at a time: asyncpg rejects a multi-command prepared statement.
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    for t in ("evidence", "research_queries", "research_runs"):
        op.execute(f"drop table if exists public.{t} cascade")
