"""Structured output for the judges and planners: one Claude tool-use call whose
`input_schema` is the answer schema, so the reply is always valid JSON of the right shape.
Schemas stay flat, with no optionals/unions, exactly like SuperMind's strict-mode zod schemas."""
from __future__ import annotations

import html
import json
import re
from typing import Any, Optional

import anthropic

from app.core.config import get_settings
from app.core.monitoring import tracked_messages_create


class LlmError(RuntimeError):
    pass


class LlmTruncated(LlmError):
    """The model hit max_tokens mid-structure; the tool input is partial and must not be used."""


_ITEM_RE = re.compile(r"<item>(.*?)(?=<item>|$)", re.S)
_PARAM_RE = re.compile(r'<parameter name="([^"]+)">(.*?)(?:</parameter>|$)', re.S)


def _unescape(t: str) -> str:
    return html.unescape(t).strip()


def _parse_pseudo_xml_items(text: str) -> list[dict]:
    """Recover `<item><parameter name="k">v</parameter>…</item>` blocks the model sometimes emits
    instead of a JSON array of objects (seen in production for nested array-of-object schemas)."""
    out = []
    for m in _ITEM_RE.finditer(text):
        params = _PARAM_RE.findall(m.group(1))
        if params:
            out.append({k: _unescape(v) for k, v in params})
    return out


def coerce(schema: dict, value: Any) -> Any:
    """Force `value` into the shape `schema` describes. Wrong-shaped model output becomes the
    nearest sane value (a string where a list was asked → one-item list or recovered items; a
    string where a number was asked → parsed number or 0; missing required keys → empty defaults)
    so downstream code and the UI can rely on types."""
    t = schema.get("type")
    if t == "object":
        props = schema.get("properties", {})
        if isinstance(value, str):
            items = _parse_pseudo_xml_items(value)
            value = items[0] if items else {}
        if not isinstance(value, dict):
            value = {}
        return {k: coerce(sub, value.get(k)) for k, sub in props.items()}
    if t == "array":
        items_schema = schema.get("items", {})
        if isinstance(value, str):
            recovered = _parse_pseudo_xml_items(value) if items_schema.get("type") == "object" else None
            if recovered:
                value = recovered
            elif items_schema.get("type") == "object":
                value = []
            else:
                lines = [ln.strip(" -•\t") for ln in value.splitlines() if ln.strip(" -•\t")]
                value = lines if len(lines) > 1 else ([value.strip()] if value.strip() else [])
        elif isinstance(value, dict):
            value = list(value.values())
        elif value is None:
            value = []
        elif not isinstance(value, list):
            value = [value]
        out = [coerce(items_schema, v) for v in value]
        if items_schema.get("type") == "object":
            out = [o for o in out if any(v not in ("", 0, [], None) for v in o.values())]
        mx = schema.get("maxItems")
        return out[:mx] if mx else out
    if t == "string":
        if value is None:
            return ""
        if isinstance(value, (list, dict)):
            return json.dumps(value)
        v = str(value)
        if "enum" in schema and v not in schema["enum"]:
            low = v.strip().lower()
            match = next((e for e in schema["enum"] if e.lower() == low), None)
            return match or schema["enum"][0]
        return v
    if t in ("number", "integer"):
        try:
            n = float(value) if not isinstance(value, bool) else 0.0
        except (TypeError, ValueError):
            m = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
            n = float(m.group()) if m else 0.0
        return int(round(n)) if t == "integer" else n
    if t == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "yes", "1")
    return value


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
    if getattr(resp, "stop_reason", None) == "max_tokens":
        raise LlmTruncated(f"{label}: output hit max_tokens={max_tokens}; structured answer is incomplete")
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use":
            inp = block.input
            if isinstance(inp, str):
                try:
                    inp = json.loads(inp)
                except Exception:  # noqa: BLE001
                    inp = {}
            return coerce(schema, inp)
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
