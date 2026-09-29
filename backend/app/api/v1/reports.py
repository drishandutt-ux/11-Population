import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.session import AnalysisSession
from app.models.report import ReportQuery
from app.core.auth import AuthUser, get_current_user, get_owned_session

router = APIRouter(prefix="/sessions", tags=["reports"])


class ReportQueryRequest(BaseModel):
    question: str


class ReportQueryResponse(BaseModel):
    id: str
    question: str
    answer: str
    sources: Optional[str] = None
    # The wired parts of the report proper (brief L6-02); None for Ask-Report follow-ups.
    structure: Optional[dict] = None

    class Config:
        from_attributes = True


@router.post("/{session_id}/report/query", response_model=ReportQueryResponse)
async def query_report(
    session_id: str,
    body: ReportQueryRequest,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_owned_session(session_id, user, db)

    from app.services.simulation.report_generator import answer_report_query
    answer, sources = await answer_report_query(session_id, session.query, body.question, db)

    record = ReportQuery(
        id=str(uuid.uuid4()),
        session_id=session_id,
        question=body.question,
        answer=answer,
        sources=sources,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


class GenerateReportRequest(BaseModel):
    # Optional since L6-02: the section spec lives server-side (`structure.REPORT_PROMPT`); a
    # non-empty question overrides it (kept for callers that still send their own).
    question: str = ""
    mode: str = "fast"


@router.post("/{session_id}/report/generate")
async def generate_report(
    session_id: str,
    body: GenerateReportRequest,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The report proper (brief L6-01 / L6-02): first make sure the headline outcome record
    exists — the population's answer to the session question, computed from a verdict probe
    (reused while the roster is unchanged) — then every other record on file, then the
    narrative written around them with the computed parts (confidence band, evidence by class,
    positions and named dissent, the records' caveats) stored as `structure` beside the prose.
    Returns the report row plus the records it was rendered from."""
    from app.services.simulation import records as records_mod
    from app.services.simulation.report_generator import generate_report as _generate

    session = await get_owned_session(session_id, user, db)
    headline = None
    try:
        headline = await records_mod.ensure_headline(session_id, session.query, mode="pro" if body.mode == "pro" else "fast")
    except Exception as e:  # noqa: BLE001
        print(f"[report] headline record failed: {type(e).__name__}: {e}")
    records = await records_mod.records_for_session(session_id)
    answer, sources, structure = await _generate(session_id, session.query, db, records, headline, request=body.question)
    record = ReportQuery(id=str(uuid.uuid4()), session_id=session_id, question=body.question or "report", answer=answer,
                         sources=sources, structure=structure)
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": record.id, "question": record.question, "answer": record.answer, "sources": record.sources,
            "records": records, "structure": structure}


@router.get("/{session_id}/records")
async def list_records(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Every outcome record on file for the session (§7.14): the headline verdict first, then Lab results."""
    from app.services.simulation import records as records_mod
    await get_owned_session(session_id, user, db)
    return {"records": await records_mod.records_for_session(session_id)}


@router.get("/{session_id}/export.zip")
async def export_bundle(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The structured export (brief L6-06): run record, every outcome record as JSON and flat
    CSVs, the latest report with its structure and as a client document, the source ledger, the
    roster — every file stamped with the synthetic-population statement (brief L6-07)."""
    from fastapi.responses import Response
    from app.services.simulation import export as export_mod
    await get_owned_session(session_id, user, db)
    data = await export_mod.bundle(session_id)
    return Response(content=data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="population-{session_id[:8]}.zip"'})


@router.get("/{session_id}/report/client")
async def client_report(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The client-facing document (brief L6-06) as data: the run record, the statement (L6-07),
    the latest report with its structure, the records, the roster names and the source ledger.
    The frontend renders it as a clean page; `report.md` in the export is the same document."""
    from app.models.agent import SpawnedAgent
    from app.services.simulation import export as export_mod
    from app.services.simulation import figures as figures_mod
    from app.services.simulation import records as records_mod
    await get_owned_session(session_id, user, db)
    run = await export_mod.run_record(session_id)
    latest = (await db.execute(select(ReportQuery).where(ReportQuery.session_id == session_id, ReportQuery.structure.isnot(None)).order_by(ReportQuery.created_at.desc()))).scalars().first()
    records = await records_mod.records_by_ids(session_id, ((latest.structure or {}).get("records") or {}).get("all") or []) if latest else []
    ledger = await figures_mod.load_ledger(session_id)
    agents = (await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == session_id))).scalars().all()
    names = {a.id: a.name for a in agents}
    report = {"id": latest.id, "created_at": latest.created_at.isoformat() if latest.created_at else None, "answer": latest.answer, "structure": latest.structure} if latest else None
    return {"run": run, "statement": export_mod.statement(run), "report": report, "records": records, "ledger": ledger,
            "markdown": export_mod.client_markdown(run=run, report=report, records=records, agents=names, ledger=ledger)}


@router.get("/{session_id}/report/delta")
async def report_delta(session_id: str, a: Optional[str] = None, b: Optional[str] = None, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """What changed between two reports proper (brief L6-06): `b` (default the latest) against
    `a` (default the one before). 404 when the session has fewer than two."""
    from app.services.simulation import delta as delta_mod
    await get_owned_session(session_id, user, db)
    out = await delta_mod.delta_for_session(session_id, a, b)
    if out is None:
        raise HTTPException(status_code=404, detail="Generate the report at least twice to compare runs.")
    return out


@router.get("/{session_id}/figures")
async def list_figures(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The source-figure ledger (brief L6-03): every typed statistic and evidence item on file with
    its provenance class — what a `[[fact:…]]` / `[[evidence:…]]` citation in a report resolves to."""
    from app.services.simulation import figures as figures_mod
    await get_owned_session(session_id, user, db)
    return await figures_mod.load_ledger(session_id)


@router.get("/{session_id}/report/history", response_model=list[ReportQueryResponse])
async def get_report_history(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    result = await db.execute(
        select(ReportQuery)
        .where(ReportQuery.session_id == session_id)
        .order_by(ReportQuery.created_at.asc())
    )
    return result.scalars().all()
