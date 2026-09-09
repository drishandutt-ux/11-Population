"""Per-agent one-line verdicts ("Agent Opinions" sidebar).

Why this exists as its own module: the original endpoint asked Haiku for ONE JSON
object keyed by 36-char UUIDs for every agent in a single call with `max_tokens=1200`.
Production Pulse logs showed every call finishing at exactly 1200 completion tokens —
i.e. the JSON was always truncated, `json.loads` always failed, and the endpoint
silently returned `{}` (the UI then showed "summarising…" forever).

This implementation:
  * batches agents (BATCH agents per call) and runs the batches concurrently;
  * keys each agent by a short integer inside the batch (not a UUID) so the model
    can't mangle ids and the output is ~40% smaller;
  * sizes `max_tokens` from the batch size with generous headroom;
  * salvages every complete `"k": "v"` pair if a response is still truncated;
  * never raises on LLM failure — returns whatever it got plus an `error` string;
  * persists each verdict on `SpawnedAgent.verdict` so a reload shows it instantly.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Optional

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.monitoring import tracked_messages_create
from app.core.llm_errors import friendly_llm_error
from app.models.agent import SpawnedAgent
from app.models.post import SimulationPost, PostType

BATCH = 25                 # agents per LLM call
CONCURRENCY = 6            # parallel verdict calls
TOKENS_PER_AGENT = 70      # output budget per agent (10-15 words + JSON overhead, with slack)
MAX_VERDICT_CHARS = 160
POSTS_PER_AGENT = 3
POST_EXCERPT_CHARS = 400


_PAIR_RE = re.compile(r'"(\d+)"\s*:\s*"((?:[^"\\]|\\.)*)"')


def parse_verdict_json(raw: str) -> dict[str, str]:
    """Parse `{"1": "verdict", ...}`; tolerate code fences and truncated output."""
    if not raw:
        return {}
    raw = raw.strip()
    if "```" in raw:
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("`").strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if v}
    except Exception:
        pass
    # Truncated / malformed: salvage every complete "n": "text" pair
    out: dict[str, str] = {}
    for k, v in _PAIR_RE.findall(raw):
        try:
            out[k] = json.loads(f'"{v}"')
        except Exception:
            out[k] = v
    return out


def _clean(v: str) -> str:
    v = " ".join(str(v).split())
    if len(v) > MAX_VERDICT_CHARS:
        v = v[:MAX_VERDICT_CHARS - 1].rstrip() + "…"
    return v


def _prompt(query: str, blocks: list[str]) -> str:
    return (
        'Write a KPI verdict label for each agent in a research simulation.\n\n'
        f'Session query: "{query}"\n\n'
        'Rules:\n'
        '- One line per agent, 10-15 words MAX\n'
        "- A direct, opinionated answer to the query from that agent's unique perspective\n"
        '- Specific (include numbers/positions where the agent gave them)\n'
        '- No "I think", no hedging, no restating the question\n'
        '- Feels like a Bloomberg terminal KPI, not a sentence from their post\n\n'
        'Bad: "The regulatory environment is complex and may affect valuations"\n'
        'Good: "$180 fair value; FSD optionality unjustified at current regulatory risk"\n\n'
        f'Respond ONLY with a single flat JSON object mapping the agent NUMBER to its verdict, '
        f'e.g. {{"1": "verdict", "2": "verdict"}}. Include every agent 1-{len(blocks)}. '
        'No markdown, no commentary.\n\n'
        'AGENTS:\n' + "\n\n".join(blocks)
    )


async def _verdict_batch(
    client, session_id: str, query: str, batch: list[tuple[SpawnedAgent, str]], sem: asyncio.Semaphore,
) -> tuple[dict[str, str], Optional[str]]:
    settings = get_settings()
    blocks = [
        f'#{i + 1} | {a.name} | {a.role} | stance:{getattr(a.stance, "value", a.stance)}\nPosts: {excerpt}'
        for i, (a, excerpt) in enumerate(batch)
    ]
    async with sem:
        try:
            response = await tracked_messages_create(
                client,
                session_id=session_id,
                label="opinions",
                model=settings.model_fast,
                max_tokens=min(4096, 200 + TOKENS_PER_AGENT * len(batch)),
                messages=[{"role": "user", "content": _prompt(query, blocks)}],
            )
        except Exception as e:  # noqa: BLE001
            print(f"[opinions] LLM call failed for session {session_id}: {type(e).__name__}: {e}")
            return {}, friendly_llm_error(e)

    raw = response.content[0].text if response.content else ""
    parsed = parse_verdict_json(raw)
    stop = getattr(response, "stop_reason", None)
    if stop == "max_tokens":
        print(f"[opinions] batch truncated at max_tokens (session {session_id}); salvaged {len(parsed)}/{len(batch)}")
    out: dict[str, str] = {}
    for i, (agent, _) in enumerate(batch):
        v = parsed.get(str(i + 1))
        if v:
            out[agent.id] = _clean(v)
    if not out:
        print(f"[opinions] batch produced no parsable verdicts (session {session_id}). Raw head: {raw[:200]!r}")
        return {}, "The model returned an unreadable response. Please retry."
    return out, None


async def generate_opinions(
    db: AsyncSession,
    session_id: str,
    query: str,
    agent_ids: Optional[list[str]] = None,
) -> dict:
    """Generate (and persist) one-line verdicts for every agent that has posted.

    Returns {"opinions": {agent_id: verdict}, "generated": n, "total": m, "error": str|None}
    where `opinions` includes previously persisted verdicts for agents not regenerated.
    """
    agents_result = await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == session_id))
    agents = list(agents_result.scalars().all())
    if not agents:
        return {"opinions": {}, "generated": 0, "total": 0, "error": None}

    posts_result = await db.execute(
        select(SimulationPost)
        .where(SimulationPost.session_id == session_id)
        .where(SimulationPost.type != PostType.LIKE)
        .where(SimulationPost.content.isnot(None))
        .order_by(SimulationPost.created_at.asc())
    )
    posts = posts_result.scalars().all()

    posts_by_agent: dict[str, list[str]] = {}
    for p in posts:
        if p.content:
            posts_by_agent.setdefault(p.agent_id, []).append(p.content[:POST_EXCERPT_CHARS])

    existing = {a.id: a.verdict for a in agents if getattr(a, "verdict", None)}
    wanted = set(agent_ids) if agent_ids else None

    targets: list[tuple[SpawnedAgent, str]] = []
    for a in agents:
        if wanted is not None and a.id not in wanted:
            continue
        excerpts = posts_by_agent.get(a.id)
        if not excerpts:
            continue
        targets.append((a, " … ".join(excerpts[-POSTS_PER_AGENT:])[:900]))

    total_posted = sum(1 for a in agents if posts_by_agent.get(a.id))
    if not targets:
        return {"opinions": existing, "generated": 0, "total": total_posted, "error": None}

    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    sem = asyncio.Semaphore(CONCURRENCY)
    batches = [targets[i:i + BATCH] for i in range(0, len(targets), BATCH)]
    results = await asyncio.gather(*[_verdict_batch(client, session_id, query, b, sem) for b in batches])

    generated: dict[str, str] = {}
    error: Optional[str] = None
    for verdicts, err in results:
        generated.update(verdicts)
        if err and not error:
            error = err

    if generated:
        by_id = {a.id: a for a in agents}
        for aid, verdict in generated.items():
            agent = by_id.get(aid)
            if agent is not None:
                agent.verdict = verdict
        try:
            await db.commit()
        except Exception as e:  # noqa: BLE001
            print(f"[opinions] failed to persist verdicts for session {session_id}: {e}")
            await db.rollback()

    merged = dict(existing)
    merged.update(generated)
    return {"opinions": merged, "generated": len(generated), "total": total_posted, "error": error}
