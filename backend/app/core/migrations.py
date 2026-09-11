"""Helpers for Alembic migrations.

asyncpg refuses a multi-statement string ("cannot insert multiple commands into a prepared
statement"), so a migration cannot hand Alembic one big SQL script the way it can under
psycopg2. `run_script` splits the script and executes each statement on its own.
"""
from __future__ import annotations

from alembic import op


def split_statements(sql: str) -> list[str]:
    """Split a SQL script on top-level semicolons.

    Quote-, dollar-quote- and comment-aware, so a semicolon inside a string literal, a
    `$$ … $$` body or a comment does not end a statement."""
    out: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    in_single = in_double = False
    in_line_comment = in_block_comment = False
    dollar_tag: str | None = None

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            buf.append(ch); i += 1; continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                buf.append("*/"); i += 2; continue
            buf.append(ch); i += 1; continue
        if dollar_tag:
            if sql.startswith(dollar_tag, i):
                buf.append(dollar_tag); i += len(dollar_tag); dollar_tag = None; continue
            buf.append(ch); i += 1; continue
        if in_single:
            buf.append(ch); i += 1
            if ch == "'":
                if nxt == "'":           # '' is an escaped quote, not the end
                    buf.append("'"); i += 1
                else:
                    in_single = False
            continue
        if in_double:
            buf.append(ch); i += 1
            if ch == '"':
                in_double = False
            continue

        if ch == "-" and nxt == "-":
            in_line_comment = True; buf.append("--"); i += 2; continue
        if ch == "/" and nxt == "*":
            in_block_comment = True; buf.append("/*"); i += 2; continue
        if ch == "'":
            in_single = True; buf.append(ch); i += 1; continue
        if ch == '"':
            in_double = True; buf.append(ch); i += 1; continue
        if ch == "$":
            end = sql.find("$", i + 1)
            tag_body = sql[i + 1:end] if end != -1 else ""
            # A dollar-quote tag is empty ($$) or a plain identifier ($fn$) — never an
            # expression, so `$1` style placeholders are left alone.
            if end != -1 and (tag_body == "" or tag_body.replace("_", "").isalnum() and not tag_body[0].isdigit()):
                dollar_tag = sql[i:end + 1]
                buf.append(dollar_tag); i = end + 1; continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []; i += 1; continue

        buf.append(ch); i += 1

    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def run_script(sql: str) -> None:
    """Execute a multi-statement SQL script one statement at a time."""
    for stmt in split_statements(sql):
        op.execute(stmt)
