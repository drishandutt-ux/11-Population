"""Probe runner — the one mechanism the whole Behaviour Lab is built on.

A probe asks every agent in a population one structured question, once, and stores a typed
answer. Everything a client sees afterwards (shares, intervals, segment splits, demand curves,
A/B lift, slider positions) is computed from those stored answers without another model call.

The persona is the point. An answer call reuses the agent's real system prompt — persona,
112 dials, humanity band — and shows the agent what it actually knows and has already done:
the topic, the ranked knowledge-graph context, what it argued in the debate, and every earlier
decision it made in this session. So the population behaves like a population: the sceptic who
argued against the thing in the thread does not quietly buy it, and the agent who said £9 was
its limit does not accept £14 an instrument later.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
import traceback
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.redis_client import publish, session_channel
from app.models.agent import SpawnedAgent
from app.models.measurement import Probe, ProbeAnswer
from app.models.post import SimulationPost
from app.models.session import AnalysisSession
from app.services.agents.agent_runner import _build_system_prompt
from app.services.evidence.llm import LlmError, LlmTruncated, analyze, clip
from app.services.knowledge_graph.lightrag_service import get_kg_context_string
from app.services.measurement import instruments

# Answers are short and cheap, so a probe can run hotter than a debate phase.
PROBE_CONCURRENCY = 32
MAX_PRIOR_POSTS = 3
MAX_PRIOR_ANSWERS = 4


# ── segments ──────────────────────────────────────────────────────────────────

def _age_band(age: int) -> str:
    for lo, hi, label in ((0, 25, "18-24"), (25, 35, "25-34"), (35, 45, "35-44"),
                          (45, 55, "45-54"), (55, 65, "55-64")):
        if lo <= age < hi:
            return label
    return "65+"


def _dial_bucket(v: Optional[float]) -> str:
    if v is None:
        return "unknown"
    v = float(v)
    return "low" if v <= 3 else "mid" if v <= 6 else "high"


def segments_for(agent: SpawnedAgent) -> dict:
    """Every attribute a result can be split by. Kept on the answer row so a split never
    needs the agent table, and so a segment survives the agent being respawned."""
    from app.services.agents.agent_runner import _humanity_band

    dials = agent.dials or {}
    commercial = dials.get("commercial", {}) if isinstance(dials, dict) else {}
    stance = agent.stance.value if hasattr(agent.stance, "value") else str(agent.stance)
    return {
        "stance": stance,
        "age_band": _age_band(agent.age or 30),
        "humanity_band": _humanity_band(getattr(agent, "humanity", 0) or 0),
        "purchase_intent_prior": _dial_bucket(commercial.get("purchase_intent")),
        "price_pain_prior": _dial_bucket(commercial.get("price_pain")),
    }


# ── per-agent context ─────────────────────────────────────────────────────────

_PRIOR_LABELS = {
    "would_buy": "decision", "likelihood_0_100": "likelihood", "max_price_gbp": "walk-away price",
    "key_driver": "driver", "sentiment": "feeling",
}


def _commercial_priors(agent: SpawnedAgent) -> str:
    """The agent's commercial dials, stated as tendencies. Priors, never answers."""
    dials = (agent.dials or {}).get("commercial", {}) if isinstance(agent.dials, dict) else {}
    if not dials:
        return ""
    parts = [f"{k.replace('_', ' ')} {v}/10" for k, v in list(dials.items())[:8] if v is not None]
    return ", ".join(parts)


def _format_prior_answer(instrument: str, answer: dict) -> str:
    bits = []
    for key, val in answer.items():
        if key == "reasoning" or val in (None, ""):
            continue
        bits.append(f"{_PRIOR_LABELS.get(key, key.replace('_', ' '))} {val}")
    why = clip(answer.get("reasoning", ""), 140)
    line = f"- {instrument.replace('_', ' ')}: " + ", ".join(bits[:4])
    return f'{line} — "{why}"' if why else line


async def _agent_history(db, session_id: str, agent_id: str, probe_id: str) -> tuple[list[str], list[str]]:
    """(what this agent said publicly, what it already decided privately)."""
    posts = (await db.execute(
        select(SimulationPost.content)
        .where(SimulationPost.session_id == session_id, SimulationPost.agent_id == agent_id,
               SimulationPost.content.isnot(None))
        .order_by(SimulationPost.created_at.desc()).limit(MAX_PRIOR_POSTS)
    )).scalars().all()

    rows = (await db.execute(
        select(Probe.instrument, ProbeAnswer.answer)
        .join(Probe, Probe.id == ProbeAnswer.probe_id)
        .where(ProbeAnswer.session_id == session_id, ProbeAnswer.agent_id == agent_id,
               ProbeAnswer.probe_id != probe_id)
        .order_by(ProbeAnswer.created_at.desc()).limit(MAX_PRIOR_ANSWERS)
    )).all()

    said = [clip(p, 320) for p in posts if p and p.strip()]
    decided = [_format_prior_answer(inst, ans or {}) for inst, ans in rows]
    return said, decided


def _build_user_message(
    *, agent: SpawnedAgent, instrument, spec: dict, query: str, kg_context: str,
    said: list[str], decided: list[str],
) -> str:
    ctx = spec.get("context") or {}
    blocks = [f"THE TOPIC: {query}"]

    if ctx.get("kg", True) and kg_context:
        blocks.append(f"WHAT YOU KNOW ABOUT IT:\n{clip(kg_context, 3500)}")

    if ctx.get("own_posts", True) and said:
        blocks.append(
            "WHAT YOU SAID IN THE DISCUSSION (your public position — be consistent with it, or "
            "say in your reasoning why you have changed your mind):\n"
            + "\n".join(f'- "{p}"' for p in said)
        )

    if ctx.get("prior_answers", True) and decided:
        blocks.append(
            "WHAT YOU ALREADY DECIDED EARLIER IN THIS SESSION (these were your own answers; "
            "do not contradict them without a reason):\n" + "\n".join(decided)
        )

    priors = _commercial_priors(agent)
    if priors:
        blocks.append(
            f"YOUR GENERAL TENDENCIES (priors, NOT the answer to this): {priors}"
        )

    stimulus = (spec.get("stimulus") or "").strip()
    if stimulus:
        price = spec.get("price")
        currency = spec.get("currency", "GBP")
        sym = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency, "")
        head = "WHAT YOU ARE BEING ASKED ABOUT:"
        if price:
            head += f" (asking price: {sym}{float(price):g})"
        blocks.append(f"{head}\n{clip(stimulus, 2500)}")

    blocks.append(instrument.question + "\n\nRecord your answer with the tool.")
    return "\n\n".join(blocks)


# ── one agent, one answer ─────────────────────────────────────────────────────

async def answer_one(
    agent: SpawnedAgent, *, instrument, spec: dict, probe_id: str, session_id: str,
    query: str, kg_context: str, model: str,
) -> Optional[dict]:
    """Ask one agent the instrument's question and persist the typed answer.

    Returns the answer dict, or None if the call failed (a failed agent is dropped from the
    denominator rather than filled with a default — a made-up answer would corrupt the share)."""
    started = time.monotonic()
    async with AsyncSessionLocal() as db:
        said, decided = await _agent_history(db, session_id, agent.id, probe_id)

    system = _build_system_prompt(agent, task="probe") + instrument.directive
    user = _build_user_message(
        agent=agent, instrument=instrument, spec=spec, query=query,
        kg_context=kg_context, said=said, decided=decided,
    )

    try:
        answer = await analyze(
            instrument.answer_schema, system, user,
            session_id=session_id, label=f"probe:{instrument.key}",
            model=model, max_tokens=instrument.max_tokens,
        )
    except LlmTruncated:
        # Short schemas rarely truncate; when they do, one retry with more room is enough.
        try:
            answer = await analyze(
                instrument.answer_schema, system, user,
                session_id=session_id, label=f"probe:{instrument.key}:retry",
                model=model, max_tokens=instrument.max_tokens * 2,
            )
        except (LlmError, Exception) as e:  # noqa: BLE001
            print(f"[probe] {agent.id} failed after retry: {type(e).__name__}: {e}")
            return None
    except Exception as e:  # noqa: BLE001
        print(f"[probe] {agent.id} failed: {type(e).__name__}: {e}")
        return None

    latency_ms = int((time.monotonic() - started) * 1000)
    row = {
        "agent_id": agent.id,
        "agent": {"name": agent.name, "role": agent.role, "avatar_color": agent.avatar_color},
        "answer": answer,
        "segments": segments_for(agent),
    }

    async with AsyncSessionLocal() as db:
        db.add(ProbeAnswer(
            probe_id=probe_id, session_id=session_id, agent_id=agent.id,
            answer=answer, reasoning=str(answer.get("reasoning", ""))[:2000],
            latency_ms=latency_ms,
        ))
        await db.commit()

    await publish(session_channel(session_id), {
        "type": "probe_answer",
        "probe_id": probe_id,
        "agent_id": agent.id,
        "agent_name": agent.name,
        "avatar_color": agent.avatar_color,
        "answer": answer,
        "segments": row["segments"],
    })
    return row


# ── the run ───────────────────────────────────────────────────────────────────

def _select_agents(agents: list[SpawnedAgent], spec: dict, seed: int) -> list[SpawnedAgent]:
    """Apply the spec's agent filter: segment equality plus an optional random sample.

    The sample is seeded, so "the same 100 agents" means the same 100 agents on a re-run —
    which is what makes a between-subjects A/B split honest."""
    flt = spec.get("agent_filter") or {}
    chosen = agents
    for key, want in (flt.get("segments") or {}).items():
        wanted = {want} if isinstance(want, str) else set(want or [])
        if wanted:
            chosen = [a for a in chosen if segments_for(a).get(key) in wanted]
    ids = flt.get("agent_ids")
    if ids:
        keep = set(ids)
        chosen = [a for a in chosen if a.id in keep]
    limit = flt.get("sample")
    if limit and 0 < int(limit) < len(chosen):
        rng = random.Random(seed)
        chosen = sorted(rng.sample(chosen, int(limit)), key=lambda a: a.id)
    return chosen


async def _set_status(probe_id: str, **fields) -> None:
    async with AsyncSessionLocal() as db:
        probe = await db.get(Probe, probe_id)
        if not probe:
            return
        for k, v in fields.items():
            setattr(probe, k, v)
        await db.commit()


async def _is_stopped(probe_id: str) -> bool:
    async with AsyncSessionLocal() as db:
        status = (await db.execute(select(Probe.status).where(Probe.id == probe_id))).scalar_one_or_none()
    return status in ("stopped", None)


async def run_probe(probe_id: str) -> None:
    """Background task: run one probe to completion and store its aggregates."""
    try:
        async with AsyncSessionLocal() as db:
            probe = await db.get(Probe, probe_id)
            if not probe:
                return
            session = await db.get(AnalysisSession, probe.session_id)
            agents = (await db.execute(
                select(SpawnedAgent).where(SpawnedAgent.session_id == probe.session_id)
            )).scalars().all()
            session_id, spec, seed = probe.session_id, dict(probe.spec or {}), probe.seed
            instrument_key, model = probe.instrument, probe.model
            query = (session.query if session else "") or ""

        instrument = instruments.get(instrument_key)
        if not instrument:
            await _set_status(probe_id, status="failed", error=f"unknown instrument '{instrument_key}'")
            return

        chosen = _select_agents(list(agents), spec, seed)
        if not chosen:
            await _set_status(probe_id, status="failed", error="no agents matched the filter",
                              completed_at=datetime.utcnow())
            await publish(session_channel(session_id), {"type": "probe_complete", "probe_id": probe_id, "status": "failed"})
            return

        # One KG snapshot for the whole probe: every agent answers the same question against
        # the same evidence, which is what makes the comparison between them meaningful.
        kg_context = await _probe_kg_context(session_id, query, spec)

        await _set_status(probe_id, status="running", agent_count=len(chosen))
        await publish(session_channel(session_id), {
            "type": "probe_started", "probe_id": probe_id,
            "instrument": instrument_key, "agent_count": len(chosen),
        })

        sem = asyncio.Semaphore(PROBE_CONCURRENCY)
        await_stop = asyncio.Event()
        rows: list[dict] = []
        failed = 0
        lock = asyncio.Lock()

        async def one(agent):
            nonlocal failed
            if await_stop.is_set():
                return
            async with sem:
                if await_stop.is_set():
                    return
                row = await answer_one(
                    agent, instrument=instrument, spec=spec, probe_id=probe_id,
                    session_id=session_id, query=query, kg_context=kg_context, model=model,
                )
            async with lock:
                if row:
                    rows.append(row)
                else:
                    failed += 1

        async def watch_stop():
            while not await_stop.is_set():
                await asyncio.sleep(1.0)
                if await _is_stopped(probe_id):
                    await_stop.set()
                    return

        watcher = asyncio.create_task(watch_stop())
        try:
            await asyncio.gather(*(one(a) for a in chosen))
        finally:
            await_stop.set()
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass

        rows.sort(key=lambda r: r["agent_id"])
        aggregates = instrument.aggregate(rows, spec)
        status = "stopped" if (failed + len(rows)) < len(chosen) else "complete"
        await _set_status(
            probe_id, status=status, answer_count=len(rows), failed_count=failed,
            aggregates=aggregates, completed_at=datetime.utcnow(),
        )
        await publish(session_channel(session_id), {
            "type": "probe_complete", "probe_id": probe_id, "status": status,
            "answer_count": len(rows), "failed_count": failed,
            "sentence": aggregates.get("sentence", ""),
        })
        print(f"[probe] {instrument_key} {probe_id}: {len(rows)} answers, {failed} failed ({status})")

    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        await _set_status(probe_id, status="failed", error=f"{type(e).__name__}: {e}",
                          completed_at=datetime.utcnow())


async def _probe_kg_context(session_id: str, query: str, spec: dict) -> str:
    """The same ranked KG + evidence-brief context the debate agents get, so a probe answer is
    grounded in exactly what the population was arguing about."""
    if not (spec.get("context") or {}).get("kg", True):
        return ""
    try:
        from app.services.evidence.brief import brief_for_prompt
        from app.services.evidence.frame import frame_terms
        from app.services.evidence.loop import latest_run
        from app.services.evidence.search.provider import query_terms

        focus = query_terms(query) if query else []
        brief_text = ""
        try:
            run = await latest_run(session_id)
            if run and run.frame:
                focus += frame_terms(run.frame)
            if run and run.brief:
                brief_text = brief_for_prompt(run.brief, 1600)
        except Exception:  # noqa: BLE001 — research is optional context
            pass
        kg = get_kg_context_string(session_id, max_entities=40, max_relations=25, focus_terms=focus)
        if "ENTITIES: none" in kg:
            kg = f"Topic under discussion: {query}"
        return (brief_text + "\n\n" + kg).strip() if brief_text else kg
    except Exception as e:  # noqa: BLE001
        print(f"[probe] KG context unavailable: {e}")
        return f"Topic under discussion: {query}"


def prompt_hash(instrument, spec: dict) -> str:
    """Fingerprint of what was asked, so two results are only ever compared when the ask matched."""
    blob = json.dumps({
        "schema": instrument.schema_id(),
        "question": instrument.question,
        "directive": instrument.directive,
        "spec": {k: spec.get(k) for k in sorted(spec) if k != "seed"},
    }, sort_keys=True, default=str)
    return hashlib.md5(blob.encode()).hexdigest()[:32]
