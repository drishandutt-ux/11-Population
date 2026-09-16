"""The typed ontology over a session's knowledge graph (brief L1-03).

The per-session graph is free text: entity strings and [head, verb, tail] triples that Claude
pulled out of whatever was ingested. That is fine for grounding a debate, but nothing can reason
over it — you cannot ask "which HCP roles treat this condition in this ICB" when "GP", "general
practitioner" and "Dr Nandakumar" are three unrelated strings and "Blackpool" does not know it
sits inside the North West.

This module lays a typed layer over that graph without touching it:

  * `SCHEMA`     — the classes we reason about (geography with its containment levels, HCP role,
                   condition, journey stage, intervention, channel, attitude segment, organisation)
                   and the predicates allowed between them.
  * `build(...)` — classifies every entity into a class (and a geography level), types every
                   relation with a predicate, and adds the containment edges the sources implied
                   but never stated (Blackpool → within → North West → within → England).
  * storage      — the result lives in `kg_graphs.ontology` (jsonb), so it survives restarts and
                   can be compared against the entity count it was built from (`stale`).

The build is on demand (a button on the Graph tab), not on every ingest: it costs one structured
call per ~80 entities plus one per ~100 relations, and the analyst wants to see it when the
graph has settled, not flicker while research streams in.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.core.config import get_settings
from app.services.evidence.llm import LlmError, analyze, arr, enum, i, obj, s

GEO_LEVELS = ["nation", "region", "icb", "local_authority", "lsoa", "place"]

CLASSES = [
    {"key": "geography", "label": "Geography", "color": "#38bdf8",
     "description": "A place at any level: nation → region → ICB → local authority → LSOA, or a named town/area.",
     "levels": GEO_LEVELS},
    {"key": "hcp_role", "label": "HCP role & specialty", "color": "#4ade80",
     "description": "A healthcare professional role or specialty (GP, community pharmacist, diabetes nurse, endocrinologist) — or a named clinician, classified by their role."},
    {"key": "condition", "label": "Condition", "color": "#fb7185",
     "description": "A disease, diagnosis or clinical state (obesity, type 2 diabetes, hypertension)."},
    {"key": "journey_stage", "label": "Journey stage", "color": "#facc15",
     "description": "A stage in the patient journey: at risk, aware & seeking, assessed, initiated, retained, outcome achieved — or a named barrier at one of them (GP access, initiation, 6–12 week discontinuation)."},
    {"key": "intervention", "label": "Intervention", "color": "#a78bfa",
     "description": "A therapy, programme, policy or service change (oral GLP-1, tiered commissioning, community-pharmacy follow-up, transport subsidy)."},
    {"key": "channel", "label": "Channel", "color": "#fb923c",
     "description": "How information or care reaches people: rep visits, NHS app, pharmacy counter, social media, GP letter, local press."},
    {"key": "attitude_segment", "label": "Attitude segment", "color": "#f472b6",
     "description": "A cohort defined by attitude or circumstance (sceptical low-income patients, early-adopter GPs, IMD 1–2 households, More in Common segments)."},
    {"key": "organisation", "label": "Organisation", "color": "#2dd4bf",
     "description": "A body that acts in the system: NHS England, an ICB, a trust, a manufacturer, a charity, a regulator."},
    {"key": "other", "label": "Other", "color": "#94a3b8",
     "description": "Anything that fits none of the above (a statistic, a document, an abstract concept)."},
]
CLASS_KEYS = [c["key"] for c in CLASSES]

PREDICATES = [
    {"key": "within", "label": "within", "domain": ["geography"], "range": ["geography"],
     "description": "Geographic containment (Blackpool within North West within England)."},
    {"key": "located_in", "label": "located in", "domain": ["*"], "range": ["geography"],
     "description": "Anything that sits in a place: an organisation, a cohort, a service."},
    {"key": "treats", "label": "treats", "domain": ["hcp_role", "organisation"], "range": ["condition"],
     "description": "A role or body manages a condition."},
    {"key": "has_stage", "label": "has stage", "domain": ["condition"], "range": ["journey_stage"],
     "description": "A condition's journey passes through this stage or barrier."},
    {"key": "precedes", "label": "precedes", "domain": ["journey_stage"], "range": ["journey_stage"],
     "description": "Stage ordering."},
    {"key": "addresses", "label": "addresses", "domain": ["intervention"], "range": ["journey_stage", "condition"],
     "description": "An intervention targets a stage, a barrier or a condition."},
    {"key": "delivered_by", "label": "delivered by", "domain": ["intervention"], "range": ["hcp_role", "organisation", "channel"],
     "description": "Who or what carries an intervention."},
    {"key": "reaches", "label": "reaches", "domain": ["channel"], "range": ["hcp_role", "attitude_segment", "geography"],
     "description": "A channel's audience."},
    {"key": "holds_view_on", "label": "holds view on", "domain": ["attitude_segment", "hcp_role"], "range": ["*"],
     "description": "A cohort or role has a stance toward something."},
    {"key": "affects", "label": "affects", "domain": ["*"], "range": ["attitude_segment", "journey_stage", "condition"],
     "description": "A causal or contributing link (transport cost affects retention)."},
    {"key": "part_of", "label": "part of", "domain": ["*"], "range": ["organisation", "intervention"],
     "description": "Structural membership that is not geographic."},
    {"key": "related_to", "label": "related to", "domain": ["*"], "range": ["*"],
     "description": "Fallback when no typed predicate fits."},
]
PREDICATE_KEYS = [p["key"] for p in PREDICATES]

SCHEMA = {"classes": CLASSES, "predicates": PREDICATES, "geo_levels": GEO_LEVELS}

ENTITY_BATCH = 80
RELATION_BATCH = 100
MAX_ENTITIES = 240
MAX_RELATIONS = 400

_CLASSIFY_SYSTEM = """You are building a typed ontology over a knowledge graph extracted from documents,
web pages and a debate about a health-system question. Classify every entity you are given into exactly one
class, and for places give the level and the containing area.

Classes:
{classes}

Geography levels: nation (England, Scotland, UK), region (North West, South East), icb (an NHS Integrated Care
Board / ICS footprint such as Lancashire and South Cumbria), local_authority (Blackpool, Oxford City), lsoa (a
census small area or a named neighbourhood), place (a town, city or area that does not map cleanly to one of
those). For a geography, `parent` is the containing area one level up (Blackpool → Lancashire and South Cumbria
ICB, or → North West if the ICB is not known) and `parent_level` is that parent's level; both empty when the
entity is not a geography or is a nation.

A named person is classified by what they are (a GP → hcp_role, a health minister → organisation is wrong, use
other). Keep `name` exactly as given — never rename. Use `other` honestly rather than forcing a class."""

_RELATE_SYSTEM = """You are typing the relations of a knowledge graph against a fixed set of predicates. Each
relation is `head → verb → tail` with the class of head and tail already known. Pick the predicate that best
captures the verb given those classes; the allowed domain/range for each predicate is listed. Use `related_to`
only when nothing else fits. Answer for every index you are given, in order.

Predicates:
{predicates}"""


def _classes_text() -> str:
    return "\n".join(f"- {c['key']}: {c['description']}" for c in CLASSES)


def _predicates_text() -> str:
    return "\n".join(f"- {p['key']} (domain {', '.join(p['domain'])} → range {', '.join(p['range'])}): {p['description']}" for p in PREDICATES)


_CLASSIFY_SCHEMA = obj({
    "nodes": arr(obj({
        "name": s("the entity exactly as given"),
        "cls": enum(CLASS_KEYS),
        "level": enum(GEO_LEVELS + ["none"], "geography level; none for non-geography"),
        "parent": s("for a geography below nation: the containing area; else empty"),
        "parent_level": enum(GEO_LEVELS + ["none"]),
    })),
})

_RELATE_SCHEMA = obj({
    "edges": arr(obj({
        "index": i("the relation's index in the list you were given"),
        "predicate": enum(PREDICATE_KEYS),
    })),
})


def _batches(items: list, size: int) -> list[list]:
    return [items[k:k + size] for k in range(0, len(items), size)]


def _mention_counts(entities: list[str], chunks: list[str]) -> dict[str, int]:
    lowered = [c.lower() for c in chunks[-200:]]
    return {e: sum(1 for c in lowered if e.lower() in c) for e in entities}


def _pick_entities(kg: dict, query: str) -> list[str]:
    """Every entity when the graph is small; the best-connected and most-mentioned ones otherwise."""
    entities = [e for e in kg.get("entities", []) if isinstance(e, str) and e.strip()]
    if len(entities) <= MAX_ENTITIES:
        return entities
    from app.services.knowledge_graph.lightrag_service import rank_entities
    terms = [t for t in (query or "").replace("?", " ").split() if len(t) > 3]
    return rank_entities(kg, terms, MAX_ENTITIES)


async def classify_entities(entities: list[str], *, session_id: str, model: Optional[str] = None) -> dict[str, dict]:
    """name → {cls, level, parent, parent_level} for every entity (one call per ENTITY_BATCH)."""
    out: dict[str, dict] = {}
    system = _CLASSIFY_SYSTEM.format(classes=_classes_text())
    for batch in _batches(entities, ENTITY_BATCH):
        user = "ENTITIES:\n" + "\n".join(f"- {e}" for e in batch)
        res = await analyze(_CLASSIFY_SCHEMA, system, user, session_id=session_id, label="ontology_classify", model=model, max_tokens=6000)
        given = {e.lower(): e for e in batch}
        for node in res.get("nodes", []):
            name = given.get(str(node.get("name", "")).strip().lower())
            if not name:
                continue
            cls = node.get("cls") if node.get("cls") in CLASS_KEYS else "other"
            level = node.get("level") if cls == "geography" and node.get("level") in GEO_LEVELS else None
            parent = str(node.get("parent") or "").strip() if cls == "geography" else ""
            parent_level = node.get("parent_level") if parent and node.get("parent_level") in GEO_LEVELS else None
            out[name] = {"cls": cls, "level": level, "parent": parent, "parent_level": parent_level}
        for e in batch:
            out.setdefault(e, {"cls": "other", "level": None, "parent": "", "parent_level": None})
    return out


async def type_relations(relations: list[list], classes: dict[str, dict], *, session_id: str, model: Optional[str] = None) -> list[str]:
    """One predicate per relation, in order (one call per RELATION_BATCH)."""
    predicates: list[str] = ["related_to"] * len(relations)
    system = _RELATE_SYSTEM.format(predicates=_predicates_text())
    offset = 0
    for batch in _batches(relations, RELATION_BATCH):
        lines = []
        for k, r in enumerate(batch):
            hc = classes.get(r[0], {}).get("cls", "other")
            tc = classes.get(r[2], {}).get("cls", "other")
            lines.append(f"{k}. {r[0]} [{hc}] → {r[1]} → {r[2]} [{tc}]")
        res = await analyze(_RELATE_SCHEMA, system, "RELATIONS:\n" + "\n".join(lines), session_id=session_id, label="ontology_relate", model=model, max_tokens=4000)
        for edge in res.get("edges", []):
            try:
                k = int(edge.get("index"))
            except (TypeError, ValueError):
                continue
            if 0 <= k < len(batch) and edge.get("predicate") in PREDICATE_KEYS:
                predicates[offset + k] = edge["predicate"]
        offset += len(batch)
    return predicates


def assemble(entities: list[str], relations: list[list], classes: dict[str, dict], predicates: list[str], chunks: list[str]) -> dict:
    """Pure: nodes + edges from the classified entities, the typed relations and the implied containment."""
    mentions = _mention_counts(entities, chunks)
    nodes: dict[str, dict] = {}
    for e in entities:
        c = classes.get(e, {"cls": "other", "level": None})
        nodes[e] = {"id": e, "cls": c["cls"], "level": c.get("level"), "mentions": mentions.get(e, 0), "inferred": False}

    edges: list[dict] = []
    seen: set[tuple] = set()

    def add_edge(head: str, predicate: str, tail: str, verb: str = "", inferred: bool = False):
        key = (head, predicate, tail)
        if head == tail or key in seen:
            return
        seen.add(key)
        edges.append({"head": head, "predicate": predicate, "tail": tail, "verb": verb, "inferred": inferred})

    for r, p in zip(relations, predicates):
        if r[0] in nodes and r[2] in nodes:
            add_edge(r[0], p, r[2], verb=r[1])

    # Implied geography containment: parents that were never entities become inferred nodes.
    by_lower = {k.lower(): k for k in nodes}
    for e in entities:
        c = classes.get(e) or {}
        parent = (c.get("parent") or "").strip()
        if c.get("cls") != "geography" or not parent or parent.lower() == e.lower():
            continue
        pid = by_lower.get(parent.lower())
        if pid is None:
            pid = parent
            nodes[pid] = {"id": pid, "cls": "geography", "level": c.get("parent_level"), "mentions": mentions.get(pid, 0), "inferred": True}
            by_lower[pid.lower()] = pid
        elif nodes[pid]["cls"] != "geography":
            continue
        add_edge(e, "within", pid, inferred=True)

    counts = {c["key"]: 0 for c in CLASSES}
    for n in nodes.values():
        counts[n["cls"]] = counts.get(n["cls"], 0) + 1
    return {"nodes": list(nodes.values()), "edges": edges, "counts": counts}


async def build(session_id: str, query: str, *, model: Optional[str] = None) -> dict:
    """Build the ontology for a session's current graph and persist it. Raises LlmError on a
    model failure and ValueError when the graph is empty."""
    from app.services.knowledge_graph.lightrag_service import get_lightrag, _load_kg

    await get_lightrag(session_id)
    kg = _load_kg(session_id)
    entities = _pick_entities(kg, query)
    if not entities:
        raise ValueError("The knowledge graph is empty — ingest sources or run research first.")
    chosen = set(entities)
    relations = [r for r in kg.get("relations", []) if len(r) == 3 and r[0] in chosen and r[2] in chosen][:MAX_RELATIONS]

    settings = get_settings()
    model = model or settings.model_fast
    classes = await classify_entities(entities, session_id=session_id, model=model)
    predicates = await type_relations(relations, classes, session_id=session_id, model=model) if relations else []
    ontology = assemble(entities, relations, classes, predicates, kg.get("chunks", []))
    ontology.update({
        "built_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "entity_count": len(kg.get("entities", [])),
        "relation_count": len(kg.get("relations", [])),
        "classified": len(entities),
        "typed": len(relations),
    })
    await save(session_id, ontology)
    return ontology


async def save(session_id: str, ontology: dict) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.kg import KnowledgeGraph

    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(KnowledgeGraph).where(KnowledgeGraph.session_id == session_id))).scalar_one_or_none()
        if row is None:
            db.add(KnowledgeGraph(session_id=session_id, entities=[], relations=[], chunks=[], ontology=ontology))
        else:
            row.ontology = ontology
        await db.commit()


async def load(session_id: str) -> Optional[dict]:
    from app.core.database import AsyncSessionLocal
    from app.models.kg import KnowledgeGraph

    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(KnowledgeGraph.ontology).where(KnowledgeGraph.session_id == session_id))).first()
    return dict(row[0]) if row and row[0] else None


async def state(session_id: str) -> dict:
    """What the Graph tab reads: the schema, the stored ontology (or null) and whether the graph
    has grown since it was built."""
    from app.services.knowledge_graph.lightrag_service import get_lightrag, _load_kg

    await get_lightrag(session_id)
    kg = _load_kg(session_id)
    ontology = await load(session_id)
    entity_count = len(kg.get("entities", []))
    stale = bool(ontology) and int(ontology.get("entity_count", -1)) != entity_count
    return {"schema": SCHEMA, "ontology": ontology, "stale": stale, "entity_count": entity_count}


__all__ = ["SCHEMA", "CLASSES", "PREDICATES", "GEO_LEVELS", "build", "state", "load", "save", "assemble", "LlmError"]
