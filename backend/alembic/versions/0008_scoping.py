"""Scoped retrieval (brief L1-04): knowledge_units, scope_policies, retrievals, and the
per-agent exposure override.

Revision ID: 0008_scoping
Revises: 0007_ontology
Create Date: 2026-09-16
"""
from alembic import op

from app.core.migrations import run_script

revision = "0008_scoping"
down_revision = "0007_ontology"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
create table if not exists public.knowledge_units (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  snapshot_id varchar(36) not null,
  text text not null,
  source_ref varchar(400) not null default '',
  provenance_class varchar(32) not null default 'grey_literature',
  trust_tier varchar(8) not null default 'medium',
  facets jsonb not null default '{}'::jsonb,
  created_at timestamp not null default now()
);
create index if not exists ix_knowledge_units_session_id on public.knowledge_units(session_id);
create index if not exists ix_knowledge_units_snapshot_id on public.knowledge_units(snapshot_id);
create index if not exists ix_knowledge_units_facets on public.knowledge_units using gin (facets);

create table if not exists public.scope_policies (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  layer varchar(16) not null default 'session',
  version integer not null default 1,
  rules jsonb not null default '[]'::jsonb,
  note varchar(200) not null default '',
  created_at timestamp not null default now()
);
create index if not exists ix_scope_policies_session_id on public.scope_policies(session_id);

create table if not exists public.retrievals (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  agent_id varchar(36) not null,
  purpose varchar(16) not null default 'post',
  snapshot_id varchar(36) not null default '',
  policy_version integer not null default 0,
  unit_ids jsonb not null default '[]'::jsonb,
  routes jsonb not null default '[]'::jsonb,
  created_at timestamp not null default now()
);
create index if not exists ix_retrievals_session_id on public.retrievals(session_id);
create index if not exists ix_retrievals_agent_id on public.retrievals(agent_id);

alter table public.knowledge_units enable row level security;
drop policy if exists "knowledge_units: via session owner" on public.knowledge_units;
create policy "knowledge_units: via session owner" on public.knowledge_units for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));

alter table public.scope_policies enable row level security;
drop policy if exists "scope_policies: via session owner" on public.scope_policies;
create policy "scope_policies: via session owner" on public.scope_policies for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));

alter table public.retrievals enable row level security;
drop policy if exists "retrievals: via session owner" on public.retrievals;
create policy "retrievals: via session owner" on public.retrievals for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));

alter table public.spawned_agents add column if not exists exposure jsonb;
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("drop table if exists public.retrievals cascade")
    op.execute("drop table if exists public.scope_policies cascade")
    op.execute("drop table if exists public.knowledge_units cascade")
    op.execute("alter table public.spawned_agents drop column if exists exposure")
