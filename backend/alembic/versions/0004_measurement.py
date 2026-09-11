"""Behaviour Lab: probes + probe_answers (+ RLS via session owner).

Revision ID: 0004_measurement
Revises: 0003_evidence
Create Date: 2026-09-11
"""
from alembic import op

revision = "0004_measurement"
down_revision = "0003_evidence"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
create table if not exists public.probes (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  instrument varchar(48) not null,
  schema_id varchar(64) not null default '',
  spec jsonb not null default '{}'::jsonb,
  experiment_id varchar(36),
  variant_key varchar(48),
  seed integer not null default 0,
  model varchar(64) not null default '',
  prompt_hash varchar(32) not null default '',
  status varchar(16) not null default 'queued',
  agent_count integer not null default 0,
  answer_count integer not null default 0,
  failed_count integer not null default 0,
  aggregates jsonb,
  error text,
  created_at timestamp not null default now(),
  completed_at timestamp
);
create index if not exists ix_probes_session_id on public.probes(session_id);
create index if not exists ix_probes_instrument on public.probes(instrument);
create index if not exists ix_probes_status on public.probes(status);
create index if not exists ix_probes_experiment_id on public.probes(experiment_id);

create table if not exists public.probe_answers (
  id varchar(36) primary key,
  probe_id varchar(36) not null references public.probes(id) on delete cascade,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  agent_id varchar(36) not null,
  answer jsonb not null default '{}'::jsonb,
  reasoning text not null default '',
  latency_ms integer not null default 0,
  created_at timestamp not null default now()
);
create index if not exists ix_probe_answers_probe_id on public.probe_answers(probe_id);
create index if not exists ix_probe_answers_session_id on public.probe_answers(session_id);
create index if not exists ix_probe_answers_agent_id on public.probe_answers(agent_id);

alter table public.probes enable row level security;
alter table public.probe_answers enable row level security;
drop policy if exists "probes: via session owner" on public.probes;
create policy "probes: via session owner" on public.probes for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));
drop policy if exists "probe_answers: via session owner" on public.probe_answers;
create policy "probe_answers: via session owner" on public.probe_answers for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    for t in ("probe_answers", "probes"):
        op.execute(f"drop table if exists public.{t} cascade")
