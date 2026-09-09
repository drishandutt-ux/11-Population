"""Profile roles: the first account to register becomes admin.

Applied to the Supabase project on 2026-09-09 as `profile_roles_first_user_admin`.

Revision ID: 0002_profile_roles
Revises: 0001_initial
Create Date: 2026-09-09
"""
from alembic import op

revision = "0002_profile_roles"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
alter table public.profiles add column if not exists role text not null default 'member';
do $$ begin
  alter table public.profiles add constraint profiles_role_check check (role in ('admin','member'));
exception when duplicate_object then null; end $$;

create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  first_user boolean;
begin
  lock table public.profiles in share row exclusive mode;
  select not exists (select 1 from public.profiles) into first_user;
  insert into public.profiles (id, email, display_name, role)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data->>'display_name', split_part(coalesce(new.email,''),'@',1)),
    case when first_user then 'admin' else 'member' end
  )
  on conflict (id) do nothing;
  return new;
end;
$$;
revoke execute on function public.handle_new_user() from public, anon, authenticated;

update public.profiles p set role = 'admin'
where not exists (select 1 from public.profiles where role = 'admin')
  and p.id = (select id from public.profiles order by created_at asc limit 1);
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("alter table public.profiles drop column if exists role")
