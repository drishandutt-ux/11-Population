import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.session import AnalysisSession
from app.models.report import ReportQuery

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
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

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


@router.get("/{session_id}/report/history", response_model=list)
async def get_report_history(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ReportQuery)
        .where(ReportQuery.session_id == session_id)
        .order_by(ReportQuery.created_at.asc())
    )
    return result.scalars().all()
