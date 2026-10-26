"""Session images (2026-10-26): the Visual Lab's image store — uploaded, generated and remade images,
each with its layout, brief, keep-list and check.

Revision ID: 0025_session_images
Revises: 0024_session_model_tier
Create Date: 2026-10-26
"""
from alembic import op

from app.core.migrations import run_script

revision = "0025_session_images"
down_revision = "0024_session_model_tier"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
create table if not exists public.session_images (
  id varchar(36) primary key,
  session_id varchar(36) not null,
  label varchar(200) not null default '',
  filename varchar(300) not null default '',
  media_type varchar(40) not null default 'image/jpeg',
  width integer not null default 0,
  height integer not null default 0,
  size_bytes integer not null default 0,
  sha256 varchar(64) not null default '',
  source varchar(16) not null default 'upload',
  status varchar(16) not null default 'ready',
  error text,
  parent_id varchar(36),
  brief json,
  layout json,
  change_note text not null default '',
  keep_list json not null default '[]'::json,
  check_result json,
  data bytea not null,
  created_at timestamp not null default now()
);
-- Added in steps 2-3 (same day); harmless where the table was created with them.
alter table public.session_images add column if not exists status varchar(16) not null default 'ready';
alter table public.session_images add column if not exists error text;
alter table public.session_images add column if not exists layout json;
alter table public.session_images add column if not exists change_note text not null default '';
create index if not exists ix_session_images_session_id on public.session_images(session_id);
create index if not exists ix_session_images_status on public.session_images(status);
create index if not exists ix_session_images_parent_id on public.session_images(parent_id);
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("drop index if exists public.ix_session_images_parent_id")
    op.execute("drop index if exists public.ix_session_images_status")
    op.execute("drop table if exists public.session_images")
