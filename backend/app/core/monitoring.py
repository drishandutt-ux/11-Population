"""AI Agent Pulse — direct-to-Supabase usage logging (no n8n).

11 Minds calls the Anthropic SDK directly, so the standard Pulse onboarding (an n8n
"Token Logger" workflow that scrapes token *estimates* from the n8n execution API) does
not apply. Instead, every Anthropic call routes through `tracked_messages_create` (async)
or is recorded via `record_usage_sync` (the two synchronous Vision calls). We read the
EXACT token usage straight off the SDK response (`response.usage.input_tokens` /
`output_tokens` — not an estimate) and POST a row into the Supabase `execution_logs`
table over its REST API. Cost is filled in by the table's `calculate_cost()` trigger
from `llm_pricing`, so we never send it.

The Pulse POST is a **no-op** unless `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` and
`PULSE_PROJECT_ID` are configured. Every failure is swallowed: monitoring must never break a
request.

Local ledger (2026-10-22): independently of Pulse, every call is ALSO written to the app's own
`llm_usage` table (tokens incl. cache + web search, model, label, priced cost) for the admin
Tokens & cost page. Rows are buffered in memory and bulk-inserted by one background writer
(`start_usage_writer`), so a burst of parallel agent calls costs one short DB connection every
few seconds rather than one per call. The session is the explicit `session_id` argument, else
`current_session_id` — set per request by `SessionContextMiddleware` from the
`/sessions/{id}/…` path and inherited by any background task the request spawns.
"""
from __future__ import annotations

import asyncio
import contextvars
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone

import httpx

from app.core.config import get_settings


def _enabled(s) -> bool:
    return bool(s.supabase_url and s.supabase_service_key and s.pulse_project_id)


def _usage(resp) -> tuple[int, int]:
    """(prompt_tokens, completion_tokens) from an Anthropic response — exact, not estimated."""
    u = getattr(resp, "usage", None)
    if not u:
        return 0, 0
    return int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0)


def _usage_detail(resp) -> dict:
    """Every billable count on the response: uncached input, output, cache write/read, web searches."""
    u = getattr(resp, "usage", None)
    if not u:
        return {"input_tokens": 0, "output_tokens": 0, "cache_creation_tokens": 0, "cache_read_tokens": 0, "web_search_requests": 0}
    stu = getattr(u, "server_tool_use", None)
    return {
        "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
        "cache_creation_tokens": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
        "cache_read_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0),
        "web_search_requests": int(getattr(stu, "web_search_requests", 0) or 0) if stu else 0,
    }


# ── Local ledger ────────────────────────────────────────────────────────────

#: The session the current request (and anything it spawns) is working on.
current_session_id: contextvars.ContextVar = contextvars.ContextVar("current_session_id", default=None)

_buffer: deque = deque(maxlen=20000)   # thread-safe appends/pops; bounded so a dead writer can't leak memory
_writer_task: "asyncio.Task | None" = None


def _record_local(*, model, resp, session_id, label, elapsed_sec, status) -> None:
    try:
        from app.core.pricing import cost_usd
        d = _usage_detail(resp)
        usd, priced = cost_usd(model, **d)
        _buffer.append({
            "created_at": datetime.utcnow(),
            "session_id": session_id or current_session_id.get(),
            "label": (label or "")[:80],
            "model": (model or "unknown")[:80],
            **d,
            "cost_usd": usd,
            "priced": 1 if priced else 0,
            "elapsed_sec": round(elapsed_sec, 2),
            "status": status,
        })
    except Exception:  # noqa: BLE001
        pass


async def flush_usage() -> int:
    """Bulk-insert whatever is buffered. Returns rows written."""
    rows = []
    while _buffer and len(rows) < 1000:
        rows.append(_buffer.popleft())
    if not rows:
        return 0
    try:
        from sqlalchemy import insert
        from app.core.database import AsyncSessionLocal
        from app.models.usage import LlmUsage
        import uuid
        for r in rows:
            r.setdefault("id", str(uuid.uuid4()))
        async with AsyncSessionLocal() as db:
            await db.execute(insert(LlmUsage), rows)
            await db.commit()
        return len(rows)
    except Exception as e:  # noqa: BLE001 — drop the batch rather than retry forever
        print(f"[usage] ledger write failed ({len(rows)} rows dropped): {type(e).__name__}: {e}")
        return 0


async def _writer_loop() -> None:
    while True:
        await asyncio.sleep(3)
        while await flush_usage():
            pass


def start_usage_writer() -> None:
    global _writer_task
    if _writer_task is None or _writer_task.done():
        _writer_task = asyncio.create_task(_writer_loop())


async def stop_usage_writer() -> None:
    if _writer_task and not _writer_task.done():
        _writer_task.cancel()
    while await flush_usage():
        pass


_SESSION_PATH = re.compile(r"/api/v1/sessions/([0-9a-fA-F-]{36})(?:/|$)")


class SessionContextMiddleware:
    """Pure ASGI: tag everything a `/sessions/{id}/…` request does (incl. tasks it spawns) with that id."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") in ("http", "websocket"):
            m = _SESSION_PATH.search(scope.get("path") or "")
            if m:
                token = current_session_id.set(m.group(1))
                try:
                    return await self.app(scope, receive, send)
                finally:
                    current_session_id.reset(token)
        return await self.app(scope, receive, send)


def _payload(*, model, prompt_tokens, completion_tokens, session_id, label, elapsed_sec, status) -> dict:
    return {
        "project_id": get_settings().pulse_project_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tokens_used": (prompt_tokens or 0) + (completion_tokens or 0),
        "prompt_tokens": prompt_tokens or 0,
        "completion_tokens": completion_tokens or 0,
        "current_llm": model or "unknown",
        "session_id": session_id,
        "execution_id": label or "11-minds-population",
        "execution_time_sec": round(elapsed_sec, 1),
        "status": status,
    }


def _send(payload: dict) -> None:
    """Blocking POST to Supabase REST. Best-effort; never raises."""
    s = get_settings()
    if not _enabled(s):
        return
    try:
        httpx.post(
            f"{s.supabase_url.rstrip('/')}/rest/v1/execution_logs",
            headers={
                "apikey": s.supabase_service_key,
                "Authorization": f"Bearer {s.supabase_service_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=payload,
            timeout=8.0,
        )
    except Exception as e:  # noqa: BLE001 — monitoring must never break the caller
        print(f"[pulse] usage log failed: {type(e).__name__}: {e}")


async def tracked_messages_create(client, *, session_id=None, label="", **create_kwargs):
    """Drop-in for `await client.messages.create(**kwargs)` that logs exact token usage to Pulse.

    Returns the Anthropic response unchanged. The log is fired off the request path so it
    never adds latency, and a logging failure can never affect the LLM call's result."""
    s = get_settings()
    started = time.time()
    status = "success"
    resp = None
    try:
        resp = await client.messages.create(**create_kwargs)
        return resp
    except Exception:
        status = "error"
        raise
    finally:
        elapsed = time.time() - started
        _record_local(model=create_kwargs.get("model"), resp=resp, session_id=session_id,
                      label=label, elapsed_sec=elapsed, status=status)
        if _enabled(s):
            try:
                prompt_tokens, completion_tokens = _usage(resp)
                payload = _payload(
                    model=create_kwargs.get("model"),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    session_id=session_id,
                    label=label,
                    elapsed_sec=elapsed,
                    status=status,
                )
                asyncio.create_task(asyncio.to_thread(_send, payload))
            except Exception:  # noqa: BLE001
                pass


def record_usage_sync(*, response=None, model, session_id=None, label="", started_at, status="success") -> None:
    """Log usage from a SYNCHRONOUS Anthropic call (the Vision ingestion paths). Fire-and-forget."""
    _record_local(model=model, resp=response, session_id=session_id, label=label,
                  elapsed_sec=time.time() - started_at, status=status)
    s = get_settings()
    if not _enabled(s):
        return
    try:
        prompt_tokens, completion_tokens = _usage(response)
        payload = _payload(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            session_id=session_id,
            label=label,
            elapsed_sec=time.time() - started_at,
            status=status,
        )
        threading.Thread(target=_send, args=(payload,), daemon=True).start()
    except Exception:  # noqa: BLE001
        pass
