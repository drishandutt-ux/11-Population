"""
Lightweight knowledge graph: Claude Haiku extracts entities/relations, stored per session.

Storage moved from per-session `kg.json` files (lost on every Railway redeploy) to the
`kg_graphs` table. An in-process cache keeps the hot path synchronous:

  * `await get_lightrag(session_id)`  — loads the graph into the cache (DB, else a legacy
    kg.json on disk, else an empty graph). Callers that read synchronously afterwards
    (`get_kg_context_string`, `get_kg_data`, `get_entity_details`) must warm it first.
  * `insert_chunks(...)` / `_save_kg` — async: update the cache and persist to the DB.
"""
import os
import json
import asyncio
from typing import Tuple
import anthropic
from sqlalchemy import select
from app.core.config import get_settings
from app.core.monitoring import tracked_messages_create

_kg_cache: dict = {}
_locks: dict = {}


def _empty() -> dict:
    return {"entities": [], "relations": [], "chunks": []}


def _legacy_path(session_id: str) -> str:
    settings = get_settings()
    return os.path.join(settings.lightrag_data_dir, session_id, "kg.json")


def _load_kg(session_id: str) -> dict:
    """Synchronous cache read. Returns an empty graph if nothing was warmed yet."""
    if session_id in _kg_cache:
        return _kg_cache[session_id]
    kg = _empty()
    _kg_cache[session_id] = kg
    return kg


async def _load_from_db(session_id: str) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.kg import KnowledgeGraph

    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(KnowledgeGraph).where(KnowledgeGraph.session_id == session_id))).scalar_one_or_none()
    if row is not None:
        return {"entities": list(row.entities or []), "relations": list(row.relations or []), "chunks": list(row.chunks or [])}
    # One-time import of a legacy on-disk graph, if present (pre-2026-09-09 deployments).
    path = _legacy_path(session_id)
    if os.path.exists(path):
        try:
            with open(path) as f:
                kg = json.load(f)
            kg = {"entities": kg.get("entities", []), "relations": kg.get("relations", []), "chunks": kg.get("chunks", [])}
            await _save_kg(session_id, kg)
            return kg
        except Exception as e:  # noqa: BLE001
            print(f"[lightrag] legacy kg.json import failed for {session_id}: {e}")
    return _empty()


async def _save_kg(session_id: str, kg: dict):
    from app.core.database import AsyncSessionLocal
    from app.models.kg import KnowledgeGraph

    _kg_cache[session_id] = kg
    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(KnowledgeGraph).where(KnowledgeGraph.session_id == session_id))).scalar_one_or_none()
            if row is None:
                db.add(KnowledgeGraph(session_id=session_id, entities=kg["entities"], relations=kg["relations"], chunks=kg["chunks"]))
            else:
                row.entities = list(kg["entities"])
                row.relations = list(kg["relations"])
                row.chunks = list(kg["chunks"])
            await db.commit()
    except Exception as e:  # noqa: BLE001 — the cache still serves the run; log loudly
        print(f"[lightrag] failed to persist KG for session {session_id}: {type(e).__name__}: {e}")


async def get_lightrag(session_id: str):
    """Warm the cache for a session (idempotent) and return the session id as the handle."""
    if session_id not in _kg_cache:
        _kg_cache[session_id] = await _load_from_db(session_id)
    return session_id


def forget(session_id: str):
    _kg_cache.pop(session_id, None)
    _locks.pop(session_id, None)


async def insert_chunks(rag: str, chunks: list) -> Tuple[list, list]:
    """Insert chunks and return (new_entities, new_relations) added this call."""
    session_id = rag
    if not chunks:
        return [], []
    if session_id not in _locks:
        _locks[session_id] = asyncio.Lock()
    async with _locks[session_id]:
        await get_lightrag(session_id)
        kg = _load_kg(session_id)
        settings = get_settings()
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        combined = "\n\n".join(chunks[:5])
        prompt = f"""Extract key entities and relationships from this text. Be concise.

TEXT:
{combined[:2500]}

Return JSON only:
{{
  "entities": ["entity1", "entity2"],
  "relations": [["entity1", "verb phrase", "entity2"]]
}}

Rules: entities = 1-4 words, 5-12 entities, 3-8 relations. No markdown, just JSON."""

        new_entities: list = []
        new_relations: list = []
        try:
            response = await tracked_messages_create(
                client,
                session_id=session_id,
                label="kg_extract",
                model=settings.model_fast,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip().rstrip("`").strip()
            extracted = json.loads(raw)

            existing_entities = set(kg["entities"])
            for e in extracted.get("entities", []):
                if e and e not in existing_entities:
                    kg["entities"].append(e)
                    existing_entities.add(e)
                    new_entities.append(e)

            existing_relations = set(tuple(r) for r in kg["relations"])
            for r in extracted.get("relations", []):
                if len(r) == 3:
                    t = tuple(r)
                    if t not in existing_relations:
                        kg["relations"].append(list(r))
                        existing_relations.add(t)
                        new_relations.append(list(r))

        except Exception as e:
            print(f"[lightrag.insert_chunks] extraction failed for session {session_id}: {type(e).__name__}: {e}")

        kg["chunks"].extend(chunks)
        kg["chunks"] = kg["chunks"][-200:]
        await _save_kg(session_id, kg)
        return new_entities, new_relations


async def query_rag(rag: str, query: str, mode: str = "hybrid") -> str:
    session_id = rag
    await get_lightrag(session_id)
    kg = _load_kg(session_id)
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    entities_str = ", ".join(kg["entities"][:50]) if kg["entities"] else "none yet"
    relations_str = "\n".join(
        f"  {r[0]} → {r[1]} → {r[2]}" for r in kg["relations"][:30]
    ) if kg["relations"] else "none yet"
    chunks_str = "\n\n---\n\n".join(kg["chunks"][-8:]) if kg["chunks"] else "No content ingested yet."

    prompt = f"""Using the knowledge graph below, answer this query concisely.

QUERY: {query}

ENTITIES: {entities_str}

RELATIONS:
{relations_str}

SOURCE EXCERPTS:
{chunks_str[:3500]}

Give a direct, insightful answer grounded in the knowledge graph."""

    try:
        response = await tracked_messages_create(
            client,
            session_id=session_id,
            label="kg_query",
            model=settings.model_fast,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"Knowledge graph query failed: {e}"


def get_kg_entities(session_id: str) -> list:
    return _load_kg(session_id).get("entities", [])


def get_kg_data(session_id: str) -> dict:
    kg = _load_kg(session_id)
    return {
        "entities": kg.get("entities", []),
        "relations": kg.get("relations", []),
    }


def get_entity_details(session_id: str, entity_name: str) -> dict:
    kg = _load_kg(session_id)
    name_lower = entity_name.lower()
    relations_from = [r for r in kg["relations"] if r[0].lower() == name_lower]
    relations_to = [r for r in kg["relations"] if len(r) > 2 and r[2].lower() == name_lower]
    mentions = [c for c in kg["chunks"][-100:] if name_lower in c.lower()][:6]
    return {
        "entity": entity_name,
        "relations_from": relations_from,
        "relations_to": relations_to,
        "mentions": [m[:400] for m in mentions],
    }


def rank_entities(kg: dict, focus_terms: list, max_entities: int) -> list:
    """Cheap relevance ranking (no LLM): +2 per focus term contained in the entity name, +log of how
    many chunks mention it, small penalty for synthetic-only mentions. Replaces insertion order,
    which fed agents whatever was ingested first (the cause of the 'irrelevant context' complaints)."""
    import math
    chunks = kg.get("chunks", [])[-200:]
    lowered = [c.lower() for c in chunks]
    terms = [t.lower() for t in (focus_terms or []) if t]
    scored = []
    for e in kg.get("entities", []):
        el = e.lower()
        hits = [c for c in lowered if el in c]
        mentions = len(hits)
        synthetic_only = mentions > 0 and all(c.startswith("[source synthetic") for c in hits)
        score = 2.0 * sum(1 for t in terms if t in el or el in t) + math.log1p(mentions) - (1.5 if synthetic_only else 0.0)
        scored.append((score, e))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:max_entities]]


def get_kg_context_string(session_id: str, max_entities: int = 60, max_relations: int = 40, focus_terms: list = None) -> str:
    kg = _load_kg(session_id)
    if focus_terms:
        entities = rank_entities(kg, focus_terms, max_entities)
        chosen = set(entities)
        rels_all = [r for r in kg.get("relations", []) if len(r) == 3]
        relations = [r for r in rels_all if r[0] in chosen or r[2] in chosen][:max_relations]
        if len(relations) < max_relations:
            seen = {tuple(r) for r in relations}
            relations += [r for r in rels_all if tuple(r) not in seen][: max_relations - len(relations)]
    else:
        entities = kg.get("entities", [])[:max_entities]
        relations = kg.get("relations", [])[:max_relations]
    ents = ", ".join(entities) if entities else "none"
    rels = "\n".join(f"  {r[0]} → {r[1]} → {r[2]}" for r in relations if len(r) == 3) if relations else "none"
    return f"KNOWLEDGE GRAPH ENTITIES: {ents}\n\nKEY RELATIONS:\n{rels}"
