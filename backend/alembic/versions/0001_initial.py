"""Initial schema: sessions, agents, posts, reports, presets, knowledge graphs, profiles, RLS.

This is the same DDL that was applied to the "11 Minds Population" Supabase project on
2026-09-09 (migration `initial_schema_sessions_agents_posts_reports_presets_kg_auth`), and the
project is stamped at this revision, so `alembic upgrade head` is a no-op there. It exists so a
fresh Postgres (a second environment, a branch database) can be built from the repo.

Revision ID: 0001_initial
Revises: None
Create Date: 2026-09-09
"""
from alembic import op

from app.core.migrations import run_script

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

_TABLES = ["profiles", "analysis_sessions", "spawned_agents", "simulation_posts", "report_queries", "agent_presets", "kg_graphs"]

UPGRADE_SQL = r"""
do $$ begin
  create type sessionstatus as enum ('CREATED','INGESTING','READY','SIMULATING','PAUSED','COMPLETE','ERROR');
exception when duplicate_object then null; end $$;
do $$ begin
  create type agentstance as enum ('DIRECT','INDIRECT','NEUTRAL');
exception when duplicate_object then null; end $$;
do $$ begin
  create type posttype as enum ('COMMENT','REPLY','LIKE','DEBATE');
exception when duplicate_object then null; end $$;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  display_name text,
  created_at timestamptz not null default now()
);
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email, display_name)
  values (new.id, new.email, coalesce(new.raw_user_meta_data->>'display_name', split_part(coalesce(new.email,''),'@',1)))
  on conflict (id) do nothing;
  return new;
end;
$$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users for each row execute function public.handle_new_user();
-- Trigger-only: never callable through PostgREST rpc.
revoke execute on function public.handle_new_user() from public, anon, authenticated;

create table if not exists public.analysis_sessions (
  id varchar(36) primary key,
  user_id uuid references auth.users(id) on delete cascade,
  title varchar(255) not null,
  query text not null,
  status sessionstatus not null default 'CREATED',
  agent_count integer not null default 0,
  created_at timestamp not null default now(),
  updated_at timestamp not null default now()
);
create index if not exists ix_analysis_sessions_user_id on public.analysis_sessions(user_id);
create index if not exists ix_analysis_sessions_created_at on public.analysis_sessions(created_at desc);

create table if not exists public.spawned_agents (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  name varchar(100) not null,
  age integer not null default 30,
  role varchar(150) not null,
  background text not null,
  stance agentstance not null,
  correlation text not null,
  personality json not null,
  debate_style text not null,
  energy double precision not null default 0.5,
  avatar_color varchar(7) not null default '#6366f1',
  dials json,
  humanity integer not null default 0,
  verdict text,
  created_at timestamp not null default now()
);
create index if not exists ix_spawned_agents_session_id on public.spawned_agents(session_id);

create table if not exists public.simulation_posts (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  agent_id varchar(36) not null,
  type posttype not null,
  content text,
  parent_id varchar(36),
  likes integer not null default 0,
  round_num integer not null default 0,
  created_at timestamp not null default now()
);
create index if not exists ix_simulation_posts_session_id on public.simulation_posts(session_id);
create index if not exists ix_simulation_posts_agent_id on public.simulation_posts(agent_id);
create index if not exists ix_simulation_posts_parent_id on public.simulation_posts(parent_id);

create table if not exists public.report_queries (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  question text not null,
  answer text not null,
  sources text,
  created_at timestamp not null default now()
);
create index if not exists ix_report_queries_session_id on public.report_queries(session_id);

create table if not exists public.agent_presets (
  id varchar(36) primary key,
  user_id uuid references auth.users(id) on delete cascade,
  name varchar(100) not null,
  agent_count integer not null default 0,
  agents json not null,
  created_at timestamp not null default now()
);
create index if not exists ix_agent_presets_user_id on public.agent_presets(user_id);

create table if not exists public.kg_graphs (
  session_id varchar(36) primary key references public.analysis_sessions(id) on delete cascade,
  entities jsonb not null default '[]'::jsonb,
  relations jsonb not null default '[]'::jsonb,
  chunks jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.profiles enable row level security;
alter table public.analysis_sessions enable row level security;
alter table public.spawned_agents enable row level security;
alter table public.simulation_posts enable row level security;
alter table public.report_queries enable row level security;
alter table public.agent_presets enable row level security;
alter table public.kg_graphs enable row level security;
-- Alembic's bookkeeping table is in the exposed schema; RLS with no policies hides it from PostgREST.
alter table if exists public.alembic_version enable row level security;

drop policy if exists "profiles: read own" on public.profiles;
create policy "profiles: read own" on public.profiles for select to authenticated using (id = (select auth.uid()));
drop policy if exists "profiles: update own" on public.profiles;
create policy "profiles: update own" on public.profiles for update to authenticated using (id = (select auth.uid())) with check (id = (select auth.uid()));
drop policy if exists "sessions: owner all" on public.analysis_sessions;
create policy "sessions: owner all" on public.analysis_sessions for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
drop policy if exists "presets: owner all" on public.agent_presets;
create policy "presets: owner all" on public.agent_presets for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
drop policy if exists "agents: via session owner" on public.spawned_agents;
create policy "agents: via session owner" on public.spawned_agents for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));
drop policy if exists "posts: via session owner" on public.simulation_posts;
create policy "posts: via session owner" on public.simulation_posts for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));
drop policy if exists "reports: via session owner" on public.report_queries;
create policy "reports: via session owner" on public.report_queries for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));
drop policy if exists "kg: via session owner" on public.kg_graphs;
create policy "kg: via session owner" on public.kg_graphs for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));
"""


def upgrade() -> None:
    # One statement at a time: asyncpg rejects a multi-command prepared statement.
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    for t in reversed(_TABLES):
        op.execute(f"drop table if exists public.{t} cascade")
    op.execute("drop trigger if exists on_auth_user_created on auth.users")
    op.execute("drop function if exists public.handle_new_user()")
    for ty in ("posttype", "agentstance", "sessionstatus"):
        op.execute(f"drop type if exists {ty}")
