"""Calibration rules (brief L4-02, the minimum of it) for the lever simulation (brief L7-04).

Revision ID: 0016_calibration_mappings
Revises: 0015_agent_knowledge
Create Date: 2026-09-29
"""
from alembic import op

from app.core.migrations import run_script

revision = "0016_calibration_mappings"
down_revision = "0015_agent_knowledge"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
create table if not exists public.calibration_mappings (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  lever varchar(160) not null,
  description text not null default '',
  applies_to jsonb not null default '{}'::jsonb,
  deltas jsonb not null default '{}'::jsonb,
  bound integer not null default 4,
  evidence jsonb not null default '[]'::jsonb,
  basis text not null default '',
  author varchar(120) not null default '',
  status varchar(16) not null default 'draft',
  reviewed_by varchar(120) not null default '',
  reviewed_at timestamp,
  created_at timestamp not null default now(),
  updated_at timestamp not null default now()
);
create index if not exists ix_calibration_mappings_session_id on public.calibration_mappings(session_id);
create index if not exists ix_calibration_mappings_status on public.calibration_mappings(status);

alter table public.calibration_mappings enable row level security;
drop policy if exists "calibration_mappings: via session owner" on public.calibration_mappings;
create policy "calibration_mappings: via session owner" on public.calibration_mappings for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("drop table if exists public.calibration_mappings cascade")
