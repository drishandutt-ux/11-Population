"""Auto-research: start/stop a run, read its live state, browse evidence, brief, recommendations."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, get_current_user, get_owned_session
from app.core.database import get_db
from app.models.evidence import Evidence, ResearchQuery, ResearchRun
from app.services.evidence.loop import evidence_payload, latest_run, start_research, stop_research, _run_payload, _query_payload

router = APIRouter(prefix="/sessions", tags=["research"])


class StartRequest(BaseModel):
    sources: Optional[list[str]] = None      # ["web", "reddit"]
    context: str = ""                         # optional pasted material to frame from


class SubQuestionRequest(BaseModel):
    text: str


class ExcludeRequest(BaseModel):
    excluded: bool = True


@router.post("/{session_id}/research/start")
async def research_start(session_id: str, body: Optional[StartRequest] = None, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await get_owned_session(session_id, user, db)
    run = await start_research(session_id, session.query, (body.sources if body else None), (body.context if body else ""))
    return _run_payload(run)


@router.post("/{session_id}/research/stop")
async def research_stop(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    run_id = await stop_research(session_id)
    return {"stopped": run_id is not None, "run_id": run_id}


@router.post("/{session_id}/research/subquestion")
async def research_subquestion(session_id: str, body: SubQuestionRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Add a sub-question: a bounded extra run framed on that question, reusing the session's frame."""
    session = await get_owned_session(session_id, user, db)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Sub-question text is required")
    prev = await latest_run(session_id)
    frame = None
    if prev and prev.frame:
        frame = dict(prev.frame)
        sqs = list(frame.get("sub_questions") or [])
        sqs.append({"id": f"q{len(sqs) + 1}", "text": text, "kind": "status"})
        frame["sub_questions"] = sqs
    run = await start_research(session_id, f"{session.query}\n\nAdditional sub-question: {text}", (prev.sources if prev else None), "", extra_frame=frame)
    return _run_payload(run)


@router.get("/{session_id}/research")
async def research_state(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The latest run with its queries and evidence counts — enough to rebuild the panel on reload."""
    await get_owned_session(session_id, user, db)
    run = (await db.execute(select(ResearchRun).where(ResearchRun.session_id == session_id).order_by(ResearchRun.started_at.desc()))).scalars().first()
    if not run:
        return {"run": None, "queries": [], "counts": {}}
    queries = (await db.execute(select(ResearchQuery).where(ResearchQuery.run_id == run.id).order_by(ResearchQuery.created_at.asc()))).scalars().all()
    counts_rows = (await db.execute(
        select(Evidence.source_class, Evidence.on_topic, func.count(Evidence.id)).where(Evidence.session_id == session_id, Evidence.excluded.is_(False)).group_by(Evidence.source_class, Evidence.on_topic)
    )).all()
    counts: dict = {}
    for sc, on, c in counts_rows:
        d = counts.setdefault(sc, {"read": 0, "on_topic": 0})
        d["read"] += int(c)
        if on:
            d["on_topic"] += int(c)
    in_graph = (await db.execute(select(func.count(Evidence.id)).where(Evidence.session_id == session_id, Evidence.in_graph.is_(True)))).scalar_one()
    return {"run": _run_payload(run), "queries": [_query_payload(q) for q in queries], "counts": counts, "in_graph": int(in_graph)}


@router.get("/{session_id}/evidence")
async def list_evidence(
    session_id: str, source_class: Optional[str] = None, on_topic: Optional[bool] = None, limit: int = 200,
    user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    await get_owned_session(session_id, user, db)
    q = select(Evidence).where(Evidence.session_id == session_id)
    if source_class:
        q = q.where(Evidence.source_class == source_class)
    if on_topic is not None:
        q = q.where(Evidence.on_topic.is_(on_topic))
    q = q.order_by(Evidence.created_at.asc()).limit(max(1, min(limit, 1000)))
    rows = (await db.execute(q)).scalars().all()
    return [evidence_payload(e) for e in rows]


@router.get("/{session_id}/evidence/brief")
async def get_brief(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    run = (await db.execute(select(ResearchRun).where(ResearchRun.session_id == session_id, ResearchRun.brief.isnot(None)).order_by(ResearchRun.started_at.desc()))).scalars().first()
    return {"brief": run.brief if run else None, "run_id": run.id if run else None}


@router.get("/{session_id}/evidence/{evidence_id}")
async def get_evidence(session_id: str, evidence_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    e = (await db.execute(select(Evidence).where(Evidence.id == evidence_id, Evidence.session_id == session_id))).scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="Evidence not found")
    d = evidence_payload(e)
    d["full_text"] = e.full_text
    return d


@router.post("/{session_id}/evidence/{evidence_id}/exclude")
async def exclude_evidence(session_id: str, evidence_id: str, body: ExcludeRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    e = (await db.execute(select(Evidence).where(Evidence.id == evidence_id, Evidence.session_id == session_id))).scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="Evidence not found")
    e.excluded = body.excluded
    await db.commit()
    return evidence_payload(e)


@router.get("/{session_id}/recommendations")
async def get_recommendations(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    run = (await db.execute(select(ResearchRun).where(ResearchRun.session_id == session_id, ResearchRun.recommendations.isnot(None)).order_by(ResearchRun.started_at.desc()))).scalars().first()
    return {"recommendations": (run.recommendations if run else []) or [], "run_id": run.id if run else None}
