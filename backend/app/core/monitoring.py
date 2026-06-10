"""AI Agent Pulse — direct-to-Supabase usage logging (no n8n).

11 Minds calls the Anthropic SDK directly, so the standard Pulse onboarding (an n8n
"Token Logger" workflow that scrapes token *estimates* from the n8n execution API) does
not apply. Instead, every Anthropic call routes through `tracked_messages_create` (async)
or is recorded via `record_usage_sync` (the two synchronous Vision calls). We read the
EXACT token usage straight off the SDK response (`response.usage.input_tokens` /
`output_tokens` — not an estimate) and POST a row into the Supabase `execution_logs`
table over its REST API. Cost is filled in by the table's `calculate_cost()` trigger
from `llm_pricing`, so we never send it.

Fully **no-op** unless `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` and `PULSE_PROJECT_ID` are
configured — safe to ship before the monitoring project is wired up. Every failure is
swallowed: monitoring must never break a request.
"""
from __future__ import annotations

import asyncio
import threading
import time
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
    if not _enabled(s):
        return await client.messages.create(**create_kwargs)

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
        try:
            prompt_tokens, completion_tokens = _usage(resp)
            payload = _payload(
                model=create_kwargs.get("model"),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                session_id=session_id,
                label=label,
                elapsed_sec=time.time() - started,
                status=status,
            )
            asyncio.create_task(asyncio.to_thread(_send, payload))
        except Exception:  # noqa: BLE001
            pass


def record_usage_sync(*, response=None, model, session_id=None, label="", started_at, status="success") -> None:
    """Log usage from a SYNCHRONOUS Anthropic call (the Vision ingestion paths). Fire-and-forget."""
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
