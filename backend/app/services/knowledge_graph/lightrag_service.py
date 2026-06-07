"""
Lightweight knowledge graph: Claude Haiku extracts entities/relations,
stored as JSON per session.
"""
import os
import json
import asyncio
from typing import Tuple
import anthropic
from app.core.config import get_settings

_kg_cache: dict = {}
_locks: dict = {}


def _kg_path(session_id: str) -> str:
    settings = get_settings()
    data_dir = os.path.join(settings.lightrag_data_dir, session_id)
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "kg.json")


def _load_kg(session_id: str) -> dict:
    if session_id in _kg_cache:
        return _kg_cache[session_id]
    path = _kg_path(session_id)
    if os.path.exists(path):
        with open(path) as f:
            kg = json.load(f)
    else:
        kg = {"entities": [], "relations": [], "chunks": []}
    _kg_cache[session_id] = kg
    return kg


def _save_kg(session_id: str, kg: dict):
    _kg_cache[session_id] = kg
    with open(_kg_path(session_id), "w") as f:
        json.dump(kg, f, indent=2)


async def get_lightrag(session_id: str):
    _load_kg(session_id)
    return session_id


async def insert_chunks(rag: str, chunks: list) -> Tuple[list, list]:
    """Insert chunks and return (new_entities, new_relations) added this call."""
    session_id = rag
    if not chunks:
        return [], []
    if session_id not in _locks:
        _locks[session_id] = asyncio.Lock()
    async with _locks[session_id]:
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
            response = await client.messages.create(
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
        _save_kg(session_id, kg)
        return new_entities, new_relations


async def query_rag(rag: str, query: str, mode: str = "hybrid") -> str:
    session_id = rag
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
        response = await client.messages.create(
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


def get_kg_context_string(session_id: str, max_entities: int = 60, max_relations: int = 40) -> str:
    kg = _load_kg(session_id)
    entities = kg.get("entities", [])[:max_entities]
    relations = kg.get("relations", [])[:max_relations]
    ents = ", ".join(entities) if entities else "none"
    rels = "\n".join(f"  {r[0]} → {r[1]} → {r[2]}" for r in relations if len(r) == 3) if relations else "none"
    return f"KNOWLEDGE GRAPH ENTITIES: {ents}\n\nKEY RELATIONS:\n{rels}"
