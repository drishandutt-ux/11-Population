"""Lab briefs (Forms, 2026-10-06): the standing per-session brief the form writer and the
brainstorm chat read — one row per session, refreshed when the session moves on.

Revision ID: 0018_lab_briefs
Revises: 0017_commitments
Create Date: 2026-10-06
"""
from alembic import op

from app.core.migrations import run_script

revision = "0018_lab_briefs"
down_revision = "0017_commitments"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
create table if not exists public.lab_briefs (
  id varchar(36) primary key,
  session_id varchar(36) not null unique references public.analysis_sessions(id) on delete cascade,
  status varchar(16) not null default 'ready',
  fingerprint varchar(64) not null default '',
  inputs jsonb not null default '{}'::jsonb,
  brief jsonb,
  model varchar(64) not null default '',
  error text,
  built_at timestamp,
  created_at timestamp not null default now(),
  updated_at timestamp not null default now()
);
create index if not exists ix_lab_briefs_session_id on public.lab_briefs(session_id);
create index if not exists ix_lab_briefs_status on public.lab_briefs(status);

alter table public.lab_briefs enable row level security;
drop policy if exists "lab_briefs: via session owner" on public.lab_briefs;
create policy "lab_briefs: via session owner" on public.lab_briefs for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("drop table if exists public.lab_briefs cascade")
