"""Commitment records (brief L7-08): the frozen modelled baseline for a candidate outcome a client
has chosen to pursue, with observed results entered later against it.

Revision ID: 0017_commitments
Revises: 0016_calibration_mappings
Create Date: 2026-09-29
"""
from alembic import op

from app.core.migrations import run_script

revision = "0017_commitments"
down_revision = "0016_calibration_mappings"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
create table if not exists public.commitments (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  journey_probe_id varchar(36) not null,
  candidate_id varchar(160) not null,
  label varchar(300) not null default '',
  committed_by varchar(120) not null default '',
  committed_at timestamp not null default now(),
  target jsonb not null default '{}'::jsonb,
  status varchar(16) not null default 'open',
  superseded_by varchar(36),
  closed_by varchar(120) not null default '',
  closed_at timestamp,
  close_note text not null default '',
  baseline jsonb not null default '{}'::jsonb,
  observed jsonb not null default '[]'::jsonb,
  created_at timestamp not null default now(),
  updated_at timestamp not null default now()
);
create index if not exists ix_commitments_session_id on public.commitments(session_id);
create index if not exists ix_commitments_journey_probe_id on public.commitments(journey_probe_id);
create index if not exists ix_commitments_status on public.commitments(status);

alter table public.commitments enable row level security;
drop policy if exists "commitments: via session owner" on public.commitments;
create policy "commitments: via session owner" on public.commitments for all to authenticated
  using (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())))
  with check (exists (select 1 from public.analysis_sessions s where s.id = session_id and s.user_id = (select auth.uid())));
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("drop table if exists public.commitments cascade")
