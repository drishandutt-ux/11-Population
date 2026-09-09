"""Structured output for the judges and planners: one Claude tool-use call whose
`input_schema` is the answer schema, so the reply is always valid JSON of the right shape.
Schemas stay flat, with no optionals/unions, exactly like SuperMind's strict-mode zod schemas."""
from __future__ import annotations

import json
from typing import Any, Optional

import anthropic

from app.core.config import get_settings
from app.core.monitoring import tracked_messages_create


class LlmError(RuntimeError):
    pass


def clip(s: Optional[str], n: int) -> str:
    s = (s or "").replace("\r", "")
    return s if len(s) <= n else s[: n - 1] + "…"


async def analyze(
    schema: dict,
    system: str,
    user: str,
    *,
    session_id: Optional[str] = None,
    label: str = "research",
    model: Optional[str] = None,
    max_tokens: int = 2000,
) -> dict:
    """Ask Claude to fill `schema` (a JSON Schema object) for the given prompt. Returns the dict."""
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    tool = {"name": "record", "description": "Record the analysis in the required structure.", "input_schema": schema}
    resp = await tracked_messages_create(
        client,
        session_id=session_id,
        label=label,
        model=model or settings.model_fast,
        max_tokens=max_tokens,
        system=system,
        tools=[tool],
        tool_choice={"type": "tool", "name": "record"},
        messages=[{"role": "user", "content": user}],
    )
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use":
            inp = block.input
            if isinstance(inp, str):
                inp = json.loads(inp)
            return dict(inp)
    raise LlmError("model returned no structured answer")


def obj(properties: dict[str, Any], required: Optional[list[str]] = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or list(properties.keys()), "additionalProperties": False}


def arr(items: dict, description: str = "", max_items: Optional[int] = None) -> dict:
    d: dict[str, Any] = {"type": "array", "items": items}
    if description:
        d["description"] = description
    if max_items:
        d["maxItems"] = max_items
    return d


def s(description: str = "") -> dict:
    return {"type": "string", "description": description} if description else {"type": "string"}


def n(description: str = "") -> dict:
    return {"type": "number", "description": description} if description else {"type": "number"}


def i(description: str = "") -> dict:
    return {"type": "integer", "description": description} if description else {"type": "integer"}


def b(description: str = "") -> dict:
    return {"type": "boolean", "description": description} if description else {"type": "boolean"}


def enum(values: list[str], description: str = "") -> dict:
    d: dict[str, Any] = {"type": "string", "enum": values}
    if description:
        d["description"] = description
    return d
