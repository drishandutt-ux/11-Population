"""The research loop: frame → plan → (web rounds ‖ Reddit attempts) → brief → recommendations.

Everything is persisted as it happens (research_runs, research_queries, evidence) and
mirrored to the session WebSocket so the Ingest tab fills live and a reload rebuilds the panel.
Stop rules: judge satisfied, round/attempt caps, on-topic target, the budget (queries, pages,
seconds), or a user Stop (status → 'stopping', checked between steps).
"""
from __future__ import annotations

import asyncio
import os
import time
import traceback
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.core import database as dbm
from app.core.redis_client import publish, session_channel
from app.models.evidence import Evidence, ResearchQuery, ResearchRun

from .fetch_page import FetchedPage, fetch_page
from .frame import build_frame, fallback_frame, frame_terms, freshness_of, stale_before, today_iso
from .judge_social import judge_posts
from .judge_web import WebItem, WebVerdict, heuristic_verdict, judge_web
from .plan import plan_query
from .reddit import ReadPost, reddit_comments, search_reddit
from .search import SearchResult, get_search_provider
from .search.provider import has_keyed_engine

# ── Budgets (env-overridable) ────────────────────────────────────────────────
WEB_MAX_ROUNDS = int(os.environ.get("WEB_MAX_ROUNDS", 3))
WEB_RESULTS_PER_QUERY = int(os.environ.get("WEB_RESULTS_PER_QUERY", 6))
WEB_PAGES_PER_QUERY = int(os.environ.get("WEB_PAGES_PER_QUERY", 5))
SOCIAL_MAX_ATTEMPTS = int(os.environ.get("SOCIAL_MAX_ATTEMPTS", 6))
SOCIAL_TARGET_ON_TOPIC = int(os.environ.get("SOCIAL_TARGET_ON_TOPIC", 25))
SOCIAL_MIN_ON_TOPIC = int(os.environ.get("SOCIAL_MIN_ON_TOPIC", 3))
SOCIAL_COMMENT_POSTS = int(os.environ.get("SOCIAL_COMMENT_POSTS", 12))
SOCIAL_COMMENTS_PER_POST = int(os.environ.get("SOCIAL_COMMENTS_PER_POST", 10))
RESEARCH_MAX_PAGES = int(os.environ.get("RESEARCH_MAX_PAGES", 80))
RESEARCH_MAX_QUERIES = int(os.environ.get("RESEARCH_MAX_QUERIES", 20))
RESEARCH_MAX_SECONDS = int(os.environ.get("RESEARCH_MAX_SECONDS", 420))
KG_INGEST_CONCURRENCY = 4

_tasks: dict[str, asyncio.Task] = {}
_stop_flags: dict[str, bool] = {}


def _web_query_gap() -> float:
    return float(os.environ.get("WEB_QUERY_GAP_MS", 500 if has_keyed_engine() else 6000)) / 1000


def _now() -> datetime:
    return datetime.utcnow()


def _iso(dt) -> Optional[str]:
    """Naive UTC datetimes from the DB must be marked 'Z', or browsers read them as local time
    (the panel showed a 60-minute elapsed time on a fresh run in BST)."""
    if not dt:
        return None
    s = dt.isoformat()
    return s if (dt.tzinfo is not None or s.endswith("Z")) else s + "Z"


async def _emit(session_id: str, event: dict):
    await publish(session_channel(session_id), event)


def _run_payload(run: ResearchRun) -> dict:
    return {
        "id": run.id, "session_id": run.session_id, "status": run.status, "question": run.question, "sources": run.sources,
        "frame": run.frame, "plan": run.plan, "verdicts": run.verdicts or [], "covered": run.covered or [], "budget": run.budget or {},
        "brief": run.brief, "recommendations": run.recommendations, "note": run.note,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }


def _query_payload(q: ResearchQuery) -> dict:
    return {"id": q.id, "run_id": q.run_id, "source": q.source, "query": q.query, "round": q.round_no, "status": q.status, "engine": q.engine,
            "results": q.results, "read": q.read, "on_topic": q.on_topic, "note": q.note, "created_at": _iso(q.created_at)}


def evidence_payload(e: Evidence) -> dict:
    return {"id": e.id, "run_id": e.run_id, "source_class": e.source_class, "source_ref": e.source_ref, "title": e.title, "author": e.author,
            "published_at": e.published_at, "text": e.text, "structured": e.structured or {}, "trust_tier": e.trust_tier,
            "relevance": e.relevance, "on_topic": e.on_topic, "excluded": e.excluded, "in_graph": e.in_graph, "query": e.query,
            "attempt": e.attempt, "sub_questions": e.sub_questions or [], "created_at": _iso(e.created_at)}


# ── Public API ───────────────────────────────────────────────────────────────

async def start_research(session_id: str, question: str, sources: Optional[list[str]] = None, context: str = "", extra_frame: Optional[dict] = None) -> ResearchRun:
    """Create a run and launch it in the background. Returns the queued run row."""
    sources = [s for s in (sources or ["web", "reddit"]) if s in ("web", "reddit")] or ["web"]
    async with dbm.AsyncSessionLocal() as db:
        # One active run per session: stop an older one that is still going.
        old = (await db.execute(select(ResearchRun).where(ResearchRun.session_id == session_id, ResearchRun.status.in_(["queued", "running"])))).scalars().all()
        for r in old:
            r.status = "stopping"
            _stop_flags[r.id] = True
        run = ResearchRun(id=str(uuid.uuid4()), session_id=session_id, status="queued", question=question, sources=sources,
                          budget={"max_queries": RESEARCH_MAX_QUERIES, "max_pages": RESEARCH_MAX_PAGES, "max_seconds": RESEARCH_MAX_SECONDS, "queries": 0, "pages": 0, "seconds": 0, "items": 0, "on_topic": 0},
                          frame=extra_frame)
        db.add(run)
        await db.commit()
        run_id = run.id
    _stop_flags[run_id] = False
    _tasks[run_id] = asyncio.create_task(_run(run_id, context))
    return run


async def stop_research(session_id: str) -> Optional[str]:
    async with dbm.AsyncSessionLocal() as db:
        run = (await db.execute(select(ResearchRun).where(ResearchRun.session_id == session_id, ResearchRun.status.in_(["queued", "running"])).order_by(ResearchRun.started_at.desc()))).scalars().first()
        if not run:
            return None
        run.status = "stopping"
        await db.commit()
        _stop_flags[run.id] = True
    await _emit(session_id, {"type": "research_status", "run_id": run.id, "status": "stopping", "note": "Stopping — finishing the current step, then building the brief from what was gathered."})
    return run.id


async def latest_run(session_id: str) -> Optional[ResearchRun]:
    async with dbm.AsyncSessionLocal() as db:
        return (await db.execute(select(ResearchRun).where(ResearchRun.session_id == session_id).order_by(ResearchRun.started_at.desc()))).scalars().first()


# ── Internals ────────────────────────────────────────────────────────────────

class _Ctx:
    def __init__(self, run: ResearchRun):
        self.run_id = run.id
        self.session_id = run.session_id
        self.question = run.question
        self.sources = list(run.sources or [])
        self.frame: Optional[dict] = run.frame
        self.plan: Optional[dict] = None
        self.budget = dict(run.budget or {})
        self.t0 = time.time()
        self.hints: list[str] = []
        self.covered: list[str] = list(run.covered or [])
        self.verdicts: list[dict] = list(run.verdicts or [])
        self.kg_sem = asyncio.Semaphore(KG_INGEST_CONCURRENCY)
        self.kg_tasks: list[asyncio.Task] = []
        self.seen_refs: set[str] = set()

    def stopped(self) -> bool:
        return bool(_stop_flags.get(self.run_id))

    def over_budget(self) -> Optional[str]:
        b = self.budget
        b["seconds"] = int(time.time() - self.t0)
        if b["queries"] >= b["max_queries"]:
            return "query budget reached"
        if b["pages"] >= b["max_pages"]:
            return "page budget reached"
        if b["seconds"] >= b["max_seconds"]:
            return "time budget reached"
        return None

    async def save(self, **fields):
        async with dbm.AsyncSessionLocal() as db:
            run = (await db.execute(select(ResearchRun).where(ResearchRun.id == self.run_id))).scalar_one_or_none()
            if not run:
                return
            for k, v in fields.items():
                setattr(run, k, v)
            run.budget = dict(self.budget)
            run.covered = list(self.covered)
            run.verdicts = list(self.verdicts)
            await db.commit()

    async def budget_event(self):
        self.budget["seconds"] = int(time.time() - self.t0)
        await _emit(self.session_id, {"type": "research_budget", "run_id": self.run_id, "budget": dict(self.budget)})


async def _new_query(ctx: _Ctx, source: str, query: str, round_no: int) -> ResearchQuery:
    async with dbm.AsyncSessionLocal() as db:
        q = ResearchQuery(id=str(uuid.uuid4()), run_id=ctx.run_id, session_id=ctx.session_id, source=source, query=query, round_no=round_no, status="running")
        db.add(q)
        await db.commit()
        await db.refresh(q)
    ctx.budget["queries"] += 1
    await _emit(ctx.session_id, {"type": "research_query", "query": _query_payload(q)})
    return q


async def _update_query(ctx: _Ctx, q: ResearchQuery, **fields):
    async with dbm.AsyncSessionLocal() as db:
        row = (await db.execute(select(ResearchQuery).where(ResearchQuery.id == q.id))).scalar_one_or_none()
        if not row:
            return
        for k, v in fields.items():
            setattr(row, k, v)
            setattr(q, k, v)
        await db.commit()
    await _emit(ctx.session_id, {"type": "research_query", "query": _query_payload(q)})


async def _persist(ctx: _Ctx, rows: list[Evidence]) -> list[Evidence]:
    if not rows:
        return []
    async with dbm.AsyncSessionLocal() as db:
        db.add_all(rows)
        await db.commit()
        for r in rows:
            await db.refresh(r)
    ctx.budget["items"] += len(rows)
    for r in rows:
        await _emit(ctx.session_id, {"type": "research_item", "item": evidence_payload(r)})
    return rows


async def _score(ctx: _Ctx, updates: dict[str, dict]):
    """Apply judge scores to persisted rows and re-emit them."""
    if not updates:
        return
    async with dbm.AsyncSessionLocal() as db:
        rows = (await db.execute(select(Evidence).where(Evidence.id.in_(list(updates.keys()))))).scalars().all()
        for r in rows:
            u = updates[r.id]
            r.relevance = float(u.get("relevance", r.relevance))
            r.on_topic = bool(u.get("on_topic", r.on_topic))
            if "sub_questions" in u:
                r.sub_questions = u["sub_questions"]
            if u.get("structured"):
                r.structured = {**(r.structured or {}), **u["structured"]}
        await db.commit()
        for r in rows:
            await _emit(ctx.session_id, {"type": "research_item", "item": evidence_payload(r)})
    ctx.budget["on_topic"] = sum(1 for u in updates.values() if u.get("on_topic")) + ctx.budget.get("on_topic", 0)


def _kg_chunk_for(e: Evidence) -> Optional[str]:
    """Provenance-tagged chunk for the knowledge graph. Header line = source class, title, ref, date."""
    if e.source_class == "web":
        body = (e.full_text or e.text or "").strip()
        if not body:
            return None
        return f"[SOURCE web | {e.title or e.author} | {e.source_ref} | {e.published_at or 'undated'}]\n{body[:6000]}"
    if e.source_class == "social":
        s = e.structured or {}
        comments = s.get("public_comments") or []
        ctext = "\n".join(f"- ({c.get('likes', 0)} pts) {c.get('text', '')[:400]}" for c in comments[:8])
        return (f"[SOURCE social reddit | {s.get('subreddit', '')} | {e.source_ref} | {e.published_at or 'undated'} | score {s.get('score', 0)}]\n"
                f"{(e.full_text or e.text or '')[:3000]}" + (f"\n\nTop comments:\n{ctext}" if ctext else ""))
    return None


async def _ingest_to_graph(ctx: _Ctx, items: list[Evidence]):
    """Only on-topic evidence reaches the graph, tagged with provenance. Fire-and-forget, bounded."""
    from app.services.ingestion.text_processor import chunk_text
    from app.services.knowledge_graph.lightrag_service import get_lightrag, insert_chunks

    async def one(e: Evidence):
        async with ctx.kg_sem:
            try:
                text = _kg_chunk_for(e)
                if not text:
                    return
                header, _, body = text.partition("\n")
                chunks = [f"{header}\n{c}" for c in chunk_text(body)[:3]] or [text]
                rag = await get_lightrag(ctx.session_id)
                new_e, new_r = await insert_chunks(rag, chunks)
                async with dbm.AsyncSessionLocal() as db:
                    row = (await db.execute(select(Evidence).where(Evidence.id == e.id))).scalar_one_or_none()
                    if row:
                        row.in_graph = True
                        await db.commit()
                if new_e or new_r:
                    await _emit(ctx.session_id, {"type": "kg_updated", "new_entities": new_e, "new_relations": new_r, "source": f"research:{e.source_class}"})
            except Exception as ex:  # noqa: BLE001
                print(f"[research] graph ingest failed for {e.id}: {type(ex).__name__}: {ex}")

    for e in items:
        ctx.kg_tasks.append(asyncio.create_task(one(e)))


# ── Web loop ─────────────────────────────────────────────────────────────────

async def _web_loop(ctx: _Ctx):
    provider = get_search_provider()
    queries = list((ctx.plan or {}).get("web_queries") or [])
    region = (ctx.plan or {}).get("web_region") or None
    tried: list[str] = []
    items: list[WebItem] = []
    id_by_index: dict[int, str] = {}
    for round_no in range(1, WEB_MAX_ROUNDS + 1):
        if not queries or ctx.stopped() or ctx.over_budget():
            break
        for qi, q in enumerate(queries):
            if ctx.stopped() or ctx.over_budget():
                break
            tried.append(q)
            row = await _new_query(ctx, "web", q, round_no)
            t0 = time.time()
            try:
                results: list[SearchResult] = await provider.search(q, {"max_results": WEB_RESULTS_PER_QUERY, "region": region})
                fresh = [r for r in results if r.url not in ctx.seen_refs]
                for r in fresh:
                    ctx.seen_refs.add(r.url)
                pages: dict[str, FetchedPage] = {}
                budget_left = max(0, ctx.budget["max_pages"] - ctx.budget["pages"])

                async def read(r: SearchResult):
                    if ctx.stopped():
                        return
                    try:
                        pages[r.url] = await fetch_page(r.url, ctx.question)
                    except Exception as e:  # noqa: BLE001
                        print(f"[research] fetch skipped {r.domain}: {e}")

                await asyncio.gather(*[read(r) for r in fresh[:min(WEB_PAGES_PER_QUERY, budget_left)]])
                ctx.budget["pages"] += len(pages)
                rows = []
                for r in fresh:
                    p = pages.get(r.url)
                    e = Evidence(
                        id=str(uuid.uuid4()), session_id=ctx.session_id, run_id=ctx.run_id, source_class="web", source_ref=r.url,
                        title=(p.title if p and len(p.title) > 3 else r.title), author=r.domain, published_at=(p.published_at if p else None) or r.published_at,
                        text=(p.markdown[:600] if p else r.snippet), full_text=(p.markdown if p else None),
                        structured={"kind": "web", "domain": r.domain, "provider": r.provider, "fetched": bool(p), "kind_detail": (p.kind if p else "snippet"), "image_url": (p.image_url if p else None),
                                    "freshness": freshness_of((p.published_at if p else None) or r.published_at, ctx.frame)},
                        trust_tier="medium", query=q, attempt=round_no,
                    )
                    rows.append(e)
                saved = await _persist(ctx, rows)
                for e in saved:
                    idx = len(items)
                    id_by_index[idx] = e.id
                    items.append(WebItem(title=e.title or "", domain=e.author or "", url=e.source_ref, snippet=(e.text or "")[:300], excerpt=(e.full_text or "")[:600] or None, published_at=e.published_at, index=idx))
                engine = results[0].provider if results else provider.name
                await _update_query(ctx, row, status="done", engine=engine, results=len(fresh), read=len(pages), note=f"{len(fresh)} new results, {len(pages)} pages read ({engine}) in {int(time.time() - t0)}s")
            except Exception as e:  # noqa: BLE001
                await _update_query(ctx, row, status="error", note=str(e)[:300])
            await ctx.budget_event()
            if qi < len(queries) - 1:
                await asyncio.sleep(_web_query_gap())

        # Judge the round
        try:
            verdict = await asyncio.wait_for(judge_web(ctx.question, today_iso(), tried, items, ctx.frame, ctx.session_id), timeout=90)
        except Exception as e:  # noqa: BLE001
            from app.core.llm_errors import friendly_llm_error
            verdict = heuristic_verdict(items, f"Coverage judge unavailable ({friendly_llm_error(e).strip('⚠️ ')}); all results kept.")
        useful = set(verdict.useful)
        updates = {}
        for idx, eid in id_by_index.items():
            updates[eid] = {"on_topic": idx in useful, "relevance": 0.9 if idx in useful else 0.2, "sub_questions": verdict.covered if idx in useful else []}
        await _score(ctx, updates)
        for ent in verdict.entities:
            if ent not in ctx.hints:
                ctx.hints.append(ent)
        for c in verdict.covered:
            if c not in ctx.covered:
                ctx.covered.append(c)
        ctx.verdicts.append({"source": "web", "round": round_no, "queries": tried[-len(queries):], "read": len(items), "on_topic": len(useful), "satisfied": verdict.satisfied, "missing": verdict.missing, "reason": verdict.reason, "at": _now().isoformat()})
        await ctx.save()
        await _emit(ctx.session_id, {"type": "research_verdict", "run_id": ctx.run_id, "source": "web", "round": round_no, "verdict": ctx.verdicts[-1], "covered": ctx.covered})
        # Graph: useful items only
        async with dbm.AsyncSessionLocal() as db:
            useful_rows = (await db.execute(select(Evidence).where(Evidence.id.in_([id_by_index[i] for i in useful if i in id_by_index]), Evidence.in_graph.is_(False)))).scalars().all()
        await _ingest_to_graph(ctx, list(useful_rows))
        if verdict.satisfied or not verdict.refined_queries or ctx.stopped():
            break
        queries = verdict.refined_queries[:3]
        await asyncio.sleep(_web_query_gap())


# ── Reddit loop ──────────────────────────────────────────────────────────────

async def _reddit_loop(ctx: _Ctx):
    queue = list((ctx.plan or {}).get("reddit_queries") or [])
    tried: list[str] = []
    seen: set[str] = set()
    on_topic_total = 0
    before = stale_before(ctx.frame)
    for attempt in range(1, SOCIAL_MAX_ATTEMPTS + 1):
        if not queue or ctx.stopped() or ctx.over_budget():
            break
        q = queue.pop(0)
        tried.append(q)
        row = await _new_query(ctx, "reddit", q, attempt)
        t0 = time.time()
        try:
            posts, note = await asyncio.wait_for(search_reddit(q), timeout=120)
        except Exception as e:  # noqa: BLE001
            await _update_query(ctx, row, status="error", note=str(e)[:300])
            continue
        fresh = [p for p in posts if p.external_id not in seen]
        for p in fresh:
            seen.add(p.external_id)
        if not fresh and "blocked" in note.lower():
            await _update_query(ctx, row, status="error", note=note[:300])
            break
        verdict = await judge_posts(ctx.question, "reddit", q, tried, fresh, SOCIAL_MIN_ON_TOPIC, hints=list(ctx.hints), frame=ctx.frame, stale_before=before, session_id=ctx.session_id)
        for k, p in enumerate(fresh):
            v = verdict.verdicts[k] if k < len(verdict.verdicts) else None
            p.relevance = v.relevance if v else 0.0
            p.on_topic = v.on_topic if v else False
            p.query, p.attempt = q, attempt
        targets = sorted([p for p in fresh if p.on_topic], key=lambda p: -p.relevance)[:SOCIAL_COMMENT_POSTS]
        for p in targets:
            if ctx.stopped():
                break
            try:
                p.comments = await asyncio.wait_for(reddit_comments(p, SOCIAL_COMMENTS_PER_POST), timeout=45)
            except Exception as e:  # noqa: BLE001
                print(f"[research] reddit comments failed for {p.external_id}: {e}")
        rows = []
        for p in fresh:
            rows.append(Evidence(
                id=str(uuid.uuid4()), session_id=ctx.session_id, run_id=ctx.run_id, source_class="social", source_ref=p.url or p.external_id,
                title=(p.payload.get("title") or p.text.split("\n")[0])[:300], author=p.author, published_at=p.published_at,
                text=p.text[:600], full_text=p.text,
                structured={"kind": "social", "platform": "reddit", "subreddit": p.author_title, "score": p.likes, "comments": p.comment_count,
                            "flair": p.payload.get("flair"), "post_kind": p.payload.get("kind"), "image_url": p.image_url,
                            "public_comments": [{"author": c.author, "text": c.text, "likes": c.likes, "published_at": c.published_at} for c in p.comments],
                            "freshness": freshness_of(p.published_at, ctx.frame)},
                trust_tier="low", relevance=p.relevance, on_topic=p.on_topic, query=q, attempt=attempt,
            ))
        saved = await _persist(ctx, rows)
        ctx.budget["on_topic"] += verdict.on_topic
        on_topic_total += verdict.on_topic
        n_comments = sum(len(p.comments) for p in targets)
        await _update_query(ctx, row, status="done", engine="reddit", results=len(fresh), read=len(fresh), on_topic=verdict.on_topic,
                            note=f"{verdict.reason} {n_comments} comments on {sum(1 for p in targets if p.comments)} posts. {int(time.time() - t0)}s")
        ctx.verdicts.append({"source": "reddit", "round": attempt, "queries": [q], "read": len(fresh), "on_topic": verdict.on_topic, "satisfied": on_topic_total >= SOCIAL_TARGET_ON_TOPIC, "missing": [], "reason": verdict.reason, "at": _now().isoformat()})
        await ctx.save()
        await _emit(ctx.session_id, {"type": "research_verdict", "run_id": ctx.run_id, "source": "reddit", "round": attempt, "verdict": ctx.verdicts[-1], "covered": ctx.covered})
        await _ingest_to_graph(ctx, [e for e in saved if e.on_topic])
        await ctx.budget_event()
        if on_topic_total >= SOCIAL_TARGET_ON_TOPIC:
            break
        r = (verdict.refined_query or "").strip()
        if r and r.lower() not in {t.lower() for t in tried} and r.lower() not in {x.lower() for x in queue}:
            queue.append(r)


# ── The run ──────────────────────────────────────────────────────────────────

async def _run(run_id: str, context: str = ""):
    async with dbm.AsyncSessionLocal() as db:
        run = (await db.execute(select(ResearchRun).where(ResearchRun.id == run_id))).scalar_one_or_none()
        if not run:
            return
        run.status = "running"
        await db.commit()
        ctx = _Ctx(run)
    await _emit(ctx.session_id, {"type": "research_started", "run_id": run_id, "question": ctx.question, "sources": ctx.sources})
    try:
        if not ctx.frame:
            ctx.frame = await build_frame(ctx.question, ctx.session_id, context) or fallback_frame(ctx.question)
        await ctx.save(frame=ctx.frame)
        await _emit(ctx.session_id, {"type": "research_frame", "run_id": run_id, "frame": ctx.frame})

        ctx.plan = await plan_query(ctx.question, ctx.frame, ctx.session_id)
        if "web" not in ctx.sources:
            ctx.plan["web_queries"] = []
        if "reddit" not in ctx.sources:
            ctx.plan["reddit_queries"] = []
        await ctx.save(plan=ctx.plan)
        await _emit(ctx.session_id, {"type": "research_plan", "run_id": run_id, "plan": ctx.plan})

        loops = []
        if ctx.plan.get("web_queries"):
            loops.append(_web_loop(ctx))
        if ctx.plan.get("reddit_queries"):
            loops.append(_reddit_loop(ctx))
        results = await asyncio.gather(*loops, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                print(f"[research] loop error: {type(r).__name__}: {r}")
                traceback.print_exception(type(r), r, r.__traceback__)

        await _emit(ctx.session_id, {"type": "research_status", "run_id": run_id, "status": "finalising", "note": "Building the evidence brief and tool recommendations from what was gathered."})
        # Let graph ingestion finish (bounded wait) so the brief sees a complete graph.
        if ctx.kg_tasks:
            await asyncio.wait(ctx.kg_tasks, timeout=90)

        from .brief import build_brief
        from .recommend import recommend_tools
        brief = await build_brief(ctx.session_id, ctx.question, ctx.frame)
        await ctx.save(brief=brief)
        await _emit(ctx.session_id, {"type": "research_brief", "run_id": run_id, "brief": brief})
        recs = await recommend_tools(ctx.session_id, ctx.question, ctx.frame, brief)
        status = "stopped" if ctx.stopped() else "complete"
        note = ctx.over_budget() or ("stopped by user" if ctx.stopped() else "coverage satisfied or query plan exhausted")
        await ctx.save(recommendations=recs, status=status, note=note, finished_at=_now())
        await _emit(ctx.session_id, {"type": "research_complete", "run_id": run_id, "status": status, "note": note, "budget": ctx.budget, "covered": ctx.covered, "recommendations": recs})
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        await ctx.save(status="error", note=f"{type(e).__name__}: {e}"[:500], finished_at=_now())
        await _emit(ctx.session_id, {"type": "research_error", "run_id": run_id, "error": f"{type(e).__name__}: {e}"[:300]})
    finally:
        _tasks.pop(run_id, None)
        _stop_flags.pop(run_id, None)
