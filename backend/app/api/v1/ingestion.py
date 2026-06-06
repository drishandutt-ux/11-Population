from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.session import AnalysisSession, SessionStatus
from app.services.ingestion.document_parser import parse_document
from app.services.ingestion.youtube_extractor import extract_youtube
from app.services.ingestion.text_processor import chunk_text
from app.services.knowledge_graph.lightrag_service import get_lightrag, insert_chunks

router = APIRouter(prefix="/sessions", tags=["ingestion"])


class TextIngestRequest(BaseModel):
    text: str


class YouTubeIngestRequest(BaseModel):
    url: str


async def _set_status(db: AsyncSession, session_id: str, status: SessionStatus):
    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if session:
        session.status = status
        await db.commit()


async def _ingest_chunks(session_id: str, raw_text: str, source: str = "document"):
    from app.core.database import AsyncSessionLocal
    from app.core.redis_client import publish, session_channel
    try:
        chunks = chunk_text(raw_text)
        rag = await get_lightrag(session_id)
        # Process in batches so frontend gets live updates
        batch_size = 5
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            new_entities, new_relations = await insert_chunks(rag, batch)
            if new_entities or new_relations:
                await publish(session_channel(session_id), {
                    "type": "kg_updated",
                    "new_entities": new_entities,
                    "new_relations": new_relations,
                    "source": source,
                })
    except Exception as e:
        print(f"[ingest_chunks] KG insertion failed for {session_id}: {e}")
    finally:
        async with AsyncSessionLocal() as db:
            await _set_status(db, session_id, SessionStatus.READY)
        await publish(session_channel(session_id), {
            "type": "ingest_complete",
            "source": source,
        })


@router.post("/{session_id}/ingest/text")
async def ingest_text(
    session_id: str,
    body: TextIngestRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.status = SessionStatus.INGESTING
    await db.commit()
    background_tasks.add_task(_ingest_chunks, session_id, body.text, "text input")
    return {"status": "ingesting", "session_id": session_id}


@router.post("/{session_id}/ingest/document")
async def ingest_document(
    session_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    content = await file.read()
    filename = file.filename or ""
    raw_text = parse_document(content, filename)

    session.status = SessionStatus.INGESTING
    await db.commit()
    background_tasks.add_task(_ingest_chunks, session_id, raw_text, filename)
    return {"status": "ingesting", "filename": filename, "session_id": session_id}


@router.post("/{session_id}/ingest/youtube")
async def ingest_youtube(
    session_id: str,
    body: YouTubeIngestRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.status = SessionStatus.INGESTING
    await db.commit()

    async def _ingest_yt():
        import traceback as _tb
        try:
            transcript = await extract_youtube(body.url)
        except Exception as e:
            print(f"[ingest_youtube] Extraction failed for {body.url}: {e}")
            _tb.print_exc()
            transcript = f"YouTube video URL: {body.url}\n\n(Automated extraction failed — agents will discuss based on the query alone.)"
        await _ingest_chunks(session_id, transcript, "YouTube")

    background_tasks.add_task(_ingest_yt)
    return {"status": "ingesting", "url": body.url, "session_id": session_id}


@router.post("/{session_id}/ingest/llm-search/generate")
async def generate_llm_paper(
    session_id: str,
    query: str = Form(...),
    llm: str = Form(default="claude"),
    context_file: Optional[UploadFile] = File(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Generate a research paper and return it to the frontend (no ingestion yet)."""
    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    context_text = ""
    if context_file and context_file.filename:
        raw = await context_file.read()
        try:
            context_text = parse_document(raw, context_file.filename or "")
        except Exception as e:
            print(f"[llm_search/generate] Context file parse failed: {e}")

    from app.services.ingestion.llm_search import categorize_query, generate_research_paper, CATEGORIES
    category = await categorize_query(query)
    paper = await generate_research_paper(query, category, context_text)

    return {
        "paper": paper,
        "category": category,
        "category_label": CATEGORIES.get(category, "Research"),
    }


@router.post("/{session_id}/ingest/llm-search")
async def ingest_llm_search(
    session_id: str,
    background_tasks: BackgroundTasks,
    query: str = Form(...),
    llm: str = Form(default="claude"),
    context_file: Optional[UploadFile] = File(default=None),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Parse optional context document now (before background task) so we hold the bytes
    context_text = ""
    if context_file and context_file.filename:
        raw = await context_file.read()
        try:
            context_text = parse_document(raw, context_file.filename or "")
        except Exception as e:
            print(f"[llm_search] Context file parse failed: {e}")

    session.status = SessionStatus.INGESTING
    await db.commit()

    async def _run():
        from app.services.ingestion.llm_search import categorize_query, generate_research_paper
        try:
            category = await categorize_query(query)
            paper = await generate_research_paper(query, category, context_text)
        except Exception as e:
            print(f"[llm_search] Generation failed: {e}")
            paper = (
                f"LLM Search query: {query}\n\n"
                "(Research paper generation failed — agents will discuss based on the query alone.)"
            )
        await _ingest_chunks(session_id, paper, "LLM Search")

    background_tasks.add_task(_run)
    return {"status": "ingesting", "session_id": session_id}
