"""Population Studio: build a realistic population with the analyst in the loop.

A build runs detect → gather (statistics sites) → clarify → plan, then waits. The analyst
answers the questions, accepts / edits / rejects segments, moves the dials and re-plans, and
finally approves — only then are agents generated, from the approved segments."""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, get_current_user, get_owned_session
from app.core.database import get_db
from app.models.population import PopulationBuild
from app.services.population import builder
from app.services.population.sources import default_sources, source_catalogue

router = APIRouter(tags=["population"])


class StartBuildRequest(BaseModel):
    mode: str = "fast"                      # fast (Haiku) | pro (Sonnet) — which model writes the personas
    count: int = 50
    constraints: dict = {}                  # the dials: stance, humanity, demographics, sentiment, profile_query, doc_context
    sources: dict = {}                      # {quant: bool, quant_sources: [keys], quant_query: str}


class AnswersRequest(BaseModel):
    answers: dict[str, str] = {}
    skip: bool = False


class SegmentDecisionRequest(BaseModel):
    decision: str                           # accept | reject | edit
    edits: Optional[dict] = None
    reason: str = ""


class ReplanRequest(BaseModel):
    constraints: Optional[dict] = None
    count: Optional[int] = None
    keep_accepted: bool = True


class ApproveRequest(BaseModel):
    count: Optional[int] = None
    mode: Optional[str] = None


class QuantSearchRequest(BaseModel):
    query: str
    sources: list[str] = []
    build_id: Optional[str] = None


@router.get("/population/sources")
async def list_sources(geography: str = "", user: AuthUser = Depends(get_current_user)):
    """The statistics publishers the Studio can search, and which are ticked by default for a geography."""
    return {"sources": source_catalogue(), "default": default_sources(geography)}


@router.post("/sessions/{session_id}/population/builds")
async def start_build(session_id: str, body: StartBuildRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    bld = await builder.start_build(session_id, mode=body.mode, count=body.count, constraints=body.constraints, sources=body.sources)
    return builder.build_payload(bld)


@router.get("/sessions/{session_id}/population/builds/latest")
async def latest_build(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    bld = await builder.latest_build(session_id)
    return {"build": builder.build_payload(bld) if bld else None}


async def _owned_build(session_id: str, build_id: str, user: AuthUser, db: AsyncSession) -> PopulationBuild:
    await get_owned_session(session_id, user, db)
    bld = (await db.execute(select(PopulationBuild).where(PopulationBuild.id == build_id, PopulationBuild.session_id == session_id))).scalar_one_or_none()
    if not bld:
        raise HTTPException(status_code=404, detail="Build not found")
    return bld


@router.get("/sessions/{session_id}/population/builds/{build_id}")
async def get_build(session_id: str, build_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    bld = await _owned_build(session_id, build_id, user, db)
    return builder.build_payload(bld)


@router.post("/sessions/{session_id}/population/builds/{build_id}/answers")
async def answer_questions(session_id: str, build_id: str, body: AnswersRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    bld = await _owned_build(session_id, build_id, user, db)
    if bld.status != "clarifying":
        raise HTTPException(status_code=409, detail=f"Build is {bld.status}, not waiting for answers")
    out = await builder.answer_questions(build_id, body.answers, body.skip)
    return builder.build_payload(out)


@router.post("/sessions/{session_id}/population/builds/{build_id}/segments/{segment_id}")
async def decide_segment(session_id: str, build_id: str, segment_id: str, body: SegmentDecisionRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    bld = await _owned_build(session_id, build_id, user, db)
    if body.decision not in ("accept", "reject", "edit"):
        raise HTTPException(status_code=400, detail="decision must be accept, reject or edit")
    if bld.status not in ("awaiting_review", "planning", "stopped", "complete", "error"):
        raise HTTPException(status_code=409, detail=f"Build is {bld.status}; segments can only be reviewed once the plan exists")
    out = await builder.decide_segment(build_id, segment_id, body.decision, body.edits, body.reason)
    out = (await builder.refresh_frame_report(build_id)) or out
    return builder.build_payload(out)


class FrameActionRequest(BaseModel):
    action: str                                   # estimate | upload | proxy | skip
    categories: Optional[list[dict]] = None       # upload: [{label, share_pct, age_min?, age_max?}]
    source: Optional[str] = ""
    proxy_of: Optional[str] = None                # proxy: the dimension key whose distribution stands in


@router.post("/sessions/{session_id}/population/builds/{build_id}/frame/estimate-all")
async def frame_estimate_all(session_id: str, build_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Resolve every open frame gap with a labelled model estimate (the model may decline attitudinal ones)."""
    bld = await _owned_build(session_id, build_id, user, db)
    if bld.status in ("spawning", "detecting", "gathering", "planning"):
        raise HTTPException(status_code=409, detail=f"Build is {bld.status}")
    try:
        out = await builder.frame_estimate_all(build_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return builder.build_payload(out)


@router.post("/sessions/{session_id}/population/builds/{build_id}/frame/{dim_key}")
async def frame_action(session_id: str, build_id: str, dim_key: str, body: FrameActionRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The ladder for one frame dimension: estimate · upload · proxy · skip."""
    bld = await _owned_build(session_id, build_id, user, db)
    if bld.status in ("spawning", "detecting", "gathering", "planning"):
        raise HTTPException(status_code=409, detail=f"Build is {bld.status}")
    try:
        out = await builder.resolve_frame_gap(build_id, dim_key, body.action, categories=body.categories, source=body.source or "", proxy_of=body.proxy_of)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return builder.build_payload(out)


@router.post("/sessions/{session_id}/population/builds/{build_id}/replan")
async def replan(session_id: str, build_id: str, body: ReplanRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    bld = await _owned_build(session_id, build_id, user, db)
    if bld.status in ("spawning", "detecting", "gathering", "planning"):
        raise HTTPException(status_code=409, detail=f"Build is {bld.status}")
    out = await builder.replan(build_id, body.constraints, body.count, body.keep_accepted)
    return builder.build_payload(out)


@router.post("/sessions/{session_id}/population/builds/{build_id}/approve")
async def approve(session_id: str, build_id: str, body: ApproveRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    bld = await _owned_build(session_id, build_id, user, db)
    if bld.status not in ("awaiting_review", "complete", "error", "stopped"):
        raise HTTPException(status_code=409, detail=f"Build is {bld.status}; approve once the plan is ready for review")
    if not bld.plan or not any(sg.get("decision") != "rejected" for sg in (bld.plan.get("segments") or [])):
        raise HTTPException(status_code=400, detail="No segments to build from")
    out = await builder.approve(build_id, count=body.count, mode=body.mode)
    return builder.build_payload(out)


@router.post("/sessions/{session_id}/population/builds/{build_id}/stop")
async def stop(session_id: str, build_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _owned_build(session_id, build_id, user, db)
    stopped = await builder.stop_build(session_id)
    return {"stopped": stopped is not None}


@router.post("/sessions/{session_id}/population/quant-search")
async def quant_search(session_id: str, body: QuantSearchRequest, background_tasks: BackgroundTasks, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Search the chosen statistics publishers now; results land as `quant` evidence and stream as research_item / population_log events."""
    await get_owned_session(session_id, user, db)
    q = body.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="query is required")
    background_tasks.add_task(builder.run_quant_search, session_id, q, body.sources, body.build_id)
    return {"queued": True}
