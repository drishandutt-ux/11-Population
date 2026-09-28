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
    question: str
    mode: str = "fast"


@router.post("/{session_id}/report/generate")
async def generate_report(
    session_id: str,
    body: GenerateReportRequest,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The report proper (brief L6-01): first make sure the headline outcome record exists —
    the population's answer to the session question, computed from a verdict probe (reused while
    the roster is unchanged) — then every other record on file, then the narrative written
    around them. Returns the report row plus the records it was rendered from."""
    from app.services.simulation import records as records_mod
    from app.services.simulation.report_generator import answer_report_query

    session = await get_owned_session(session_id, user, db)
    try:
        await records_mod.ensure_headline(session_id, session.query, mode="pro" if body.mode == "pro" else "fast")
    except Exception as e:  # noqa: BLE001
        print(f"[report] headline record failed: {type(e).__name__}: {e}")
    records = await records_mod.records_for_session(session_id)
    answer, sources = await answer_report_query(session_id, session.query, body.question, db, records=records)
    record = ReportQuery(id=str(uuid.uuid4()), session_id=session_id, question=body.question, answer=answer, sources=sources)
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": record.id, "question": record.question, "answer": record.answer, "sources": record.sources, "records": records}


@router.get("/{session_id}/records")
async def list_records(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Every outcome record on file for the session (§7.14): the headline verdict first, then Lab results."""
    from app.services.simulation import records as records_mod
    await get_owned_session(session_id, user, db)
    return {"records": await records_mod.records_for_session(session_id)}


@router.get("/{session_id}/report/history", response_model=list)
async def get_report_history(session_id: str, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_owned_session(session_id, user, db)
    result = await db.execute(
        select(ReportQuery)
        .where(ReportQuery.session_id == session_id)
        .order_by(ReportQuery.created_at.asc())
    )
    return result.scalars().all()
