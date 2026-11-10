"""Row-level security on session_images and benchmark_runs (2026-11-10).

0025 and 0026 created these tables without RLS, so Supabase's public API (anon key) could read
and write them. The backend connects as the table owner and is unaffected; no policies are added,
so the API sees nothing.

Revision ID: 0027_rls_images_benchmarks
Revises: 0026_benchmark_runs
Create Date: 2026-11-10
"""
from app.core.migrations import run_script

revision = "0027_rls_images_benchmarks"
down_revision = "0026_benchmark_runs"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
alter table public.session_images enable row level security;
alter table public.benchmark_runs enable row level security;
"""

DOWNGRADE_SQL = r"""
alter table public.benchmark_runs disable row level security;
alter table public.session_images disable row level security;
"""


def upgrade() -> None:
    run_script(UPGRADE_SQL)


def downgrade() -> None:
    run_script(DOWNGRADE_SQL)
