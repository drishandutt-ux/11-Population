"""LLM usage ledger (2026-10-22): one row per Anthropic call, for the admin Tokens & cost page.

Revision ID: 0022_llm_usage
Revises: 0021_sharing
Create Date: 2026-10-22
"""
from alembic import op

from app.core.migrations import run_script

revision = "0022_llm_usage"
down_revision = "0021_sharing"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
create table if not exists public.llm_usage (
  id varchar(36) primary key,
  created_at timestamp not null default now(),
  session_id varchar(36),
  label varchar(80) not null default '',
  model varchar(80) not null default 'unknown',
  input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  cache_creation_tokens integer not null default 0,
  cache_read_tokens integer not null default 0,
  web_search_requests integer not null default 0,
  cost_usd double precision not null default 0,
  priced integer not null default 1,
  elapsed_sec double precision not null default 0,
  status varchar(16) not null default 'success'
);
create index if not exists ix_llm_usage_session_id on public.llm_usage(session_id);
create index if not exists ix_llm_usage_created_at on public.llm_usage(created_at);

alter table public.llm_usage enable row level security;
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("drop table if exists public.llm_usage")
