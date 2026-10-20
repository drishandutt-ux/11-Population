"""Sharing (2026-10-20): sessions shared with colleagues in the same email domain, and the chat
held around a shared session (people and the report agent).

Revision ID: 0021_sharing
Revises: 0020_standing_footprint
Create Date: 2026-10-20
"""
from alembic import op

from app.core.migrations import run_script

revision = "0021_sharing"
down_revision = "0020_standing_footprint"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
create table if not exists public.session_shares (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  user_id uuid not null,
  shared_by uuid,
  created_at timestamp not null default now(),
  constraint uq_session_share unique (session_id, user_id)
);
create index if not exists ix_session_shares_session_id on public.session_shares(session_id);
create index if not exists ix_session_shares_user_id on public.session_shares(user_id);

create table if not exists public.shared_messages (
  id varchar(36) primary key,
  session_id varchar(36) not null references public.analysis_sessions(id) on delete cascade,
  user_id uuid,
  author_name varchar(160) not null default '',
  kind varchar(16) not null default 'user',
  content text not null default '',
  reply_to varchar(36),
  created_at timestamp not null default now()
);
create index if not exists ix_shared_messages_session_id on public.shared_messages(session_id);
create index if not exists ix_shared_messages_user_id on public.shared_messages(user_id);

alter table public.session_shares enable row level security;
alter table public.shared_messages enable row level security;
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("drop table if exists public.shared_messages")
    op.execute("drop table if exists public.session_shares")
