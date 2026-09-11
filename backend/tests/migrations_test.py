"""Guards for the Alembic SQL splitter.

Run:  cd backend && pytest tests/migrations_test.py -q

Regression test for the production failure on 2026-09-11: `op.execute(UPGRADE_SQL)` with a
multi-statement script died under asyncpg with "cannot insert multiple commands into a
prepared statement", so the `probes` / `probe_answers` tables were never created and the
startup error was only a printed warning. Migrations 0003 and 0004 now run statement by
statement — these tests keep every shipped script splittable.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.migrations import split_statements  # noqa: E402

VERSIONS = os.path.join(os.path.dirname(__file__), "..", "alembic", "versions")


def test_splits_on_top_level_semicolons():
    assert split_statements("create table a (x int); create index i on a(x);") == [
        "create table a (x int)",
        "create index i on a(x)",
    ]


def test_trailing_statement_without_semicolon_is_kept():
    assert split_statements("select 1;\nselect 2") == ["select 1", "select 2"]


def test_empty_and_whitespace_only_statements_are_dropped():
    assert split_statements(";\n\n ;  select 1;;") == ["select 1"]


def test_semicolon_inside_a_string_literal_does_not_split():
    out = split_statements("insert into t values ('a;b'); select 1;")
    assert out == ["insert into t values ('a;b')", "select 1"]


def test_escaped_quote_inside_a_string_literal():
    out = split_statements("insert into t values ('it''s; fine'); select 1;")
    assert out == ["insert into t values ('it''s; fine')", "select 1"]


def test_semicolon_inside_a_quoted_identifier_does_not_split():
    out = split_statements('drop policy if exists "a; b" on t; select 1;')
    assert out == ['drop policy if exists "a; b" on t', "select 1"]


def test_do_block_with_inner_semicolons_stays_one_statement():
    sql = "do $$ begin create type t as enum ('a'); exception when duplicate_object then null; end $$;\nselect 1;"
    out = split_statements(sql)
    assert len(out) == 2 and out[0].startswith("do $$") and out[0].endswith("end $$")
    assert split_statements(out[0]) == [out[0]]


def test_dollar_quoted_body_is_one_statement():
    sql = "create function f() returns int as $$ begin; return 1; end; $$ language plpgsql; select 1;"
    out = split_statements(sql)
    assert len(out) == 2 and out[0].startswith("create function") and out[0].endswith("language plpgsql")


def test_comments_do_not_split():
    out = split_statements("-- a; comment\nselect 1;\n/* block; comment */ select 2;")
    assert out == ["-- a; comment\nselect 1", "/* block; comment */ select 2"]


def _scripts() -> list[tuple[str, str]]:
    found = []
    for name in sorted(os.listdir(VERSIONS)):
        if not name.endswith(".py"):
            continue
        src = open(os.path.join(VERSIONS, name)).read()
        m = re.search(r'UPGRADE_SQL\s*=\s*r?"""(.*?)"""', src, re.S)
        if m:
            found.append((name, m.group(1)))
    return found


def test_every_shipped_script_splits_into_single_commands():
    """Splitting is idempotent: re-splitting a statement returns it unchanged.

    Not "contains no semicolon" — a `do $$ … ; … $$` block is a single command that
    legitimately holds them inside its body."""
    scripts = _scripts()
    assert scripts, "expected at least one migration with an UPGRADE_SQL script"
    for name, sql in scripts:
        stmts = split_statements(sql)
        assert stmts, f"{name}: split to nothing"
        for stmt in stmts:
            assert split_statements(stmt) == [stmt], f"{name}: statement is still multi-command:\n{stmt[:160]}"


def test_scripts_with_multiple_statements_use_run_script():
    """A migration whose script holds more than one command must not call op.execute() on it."""
    for name in sorted(os.listdir(VERSIONS)):
        if not name.endswith(".py"):
            continue
        src = open(os.path.join(VERSIONS, name)).read()
        m = re.search(r'UPGRADE_SQL\s*=\s*r?"""(.*?)"""', src, re.S)
        if not m or len(split_statements(m.group(1))) < 2:
            continue
        assert "run_script(UPGRADE_SQL)" in src, f"{name}: multi-statement script must use run_script()"
        assert "op.execute(UPGRADE_SQL)" not in src, f"{name}: op.execute() on a multi-statement script fails under asyncpg"


def test_measurement_migration_creates_both_tables():
    sql = dict(_scripts())["0004_measurement.py"]
    stmts = split_statements(sql)
    created = [s for s in stmts if s.lower().startswith("create table")]
    assert any("public.probes" in s for s in created)
    assert any("public.probe_answers" in s for s in created)


# ── the failure is visible ────────────────────────────────────────────────────

def test_health_reports_a_failed_migration():
    """A broken migration must degrade /health, not just print a warning.

    The 2026-09-11 failure was invisible: create_tables() raised, startup logged a warning,
    and /health still answered `status: ok, database_ok: true` while `probes` did not exist."""
    import app.main as main_mod
    from fastapi.testclient import TestClient

    # Simulate the failed startup without touching the real lifespan.
    original = main_mod.SCHEMA_ERROR
    try:
        main_mod.SCHEMA_ERROR = "ProgrammingError: cannot insert multiple commands"
        with TestClient(main_mod.app) as c:
            main_mod.SCHEMA_ERROR = "ProgrammingError: cannot insert multiple commands"
            body = c.get("/health").json()
        assert body["status"] == "degraded"
        assert body["schema_ok"] is False
        assert "multiple commands" in body["schema_error"]
    finally:
        main_mod.SCHEMA_ERROR = original


def test_health_is_ok_when_the_schema_is_current():
    import app.main as main_mod
    from fastapi.testclient import TestClient

    original = main_mod.SCHEMA_ERROR
    try:
        with TestClient(main_mod.app) as c:
            main_mod.SCHEMA_ERROR = None
            body = c.get("/health").json()
        assert body["schema_ok"] is True and body["schema_error"] is None
    finally:
        main_mod.SCHEMA_ERROR = original
