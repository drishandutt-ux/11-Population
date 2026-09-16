"""Facet-tagging: turn the session's knowledge (graph chunks today, claims later) into
knowledge_units carrying a provenance class, a trust tier and a facet map whose values come
from the ontology's vocabulary.

One structured call per TAG_BATCH chunks on the fast model. Values the model returns that are
not in the vocabulary are dropped, so a facet can only ever point at something the ontology
knows. Re-tagging wipes and rewrites the session's units under a new snapshot id.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.services.evidence.llm import analyze, arr, enum, i, obj, s

from .profiles import looks_like_date, nodes_by_class
from .registry import DEFAULT_SESSION_RULES, REGISTER_LEVELS

TAG_BATCH = 12
TAG_CONCURRENCY = 4
MAX_UNITS = 240

_HEADER_RE = re.compile(r"^\[SOURCE\s+([a-z]+)(?:\s+([a-z]+))?\s*\|([^\]]*)\]\s*", re.I)
_POST_RE = re.compile(r"^\[([^\]|]{1,80})\s*\|\s*([^\]]{1,120})\]:\s*")

# Hosts whose pages are statistics, not just official: a patient leaflet on nhs.uk or a policy page on
# gov.uk is grey literature, so plain "nhs.uk" / "gov.uk" are deliberately not here.
_OFFICIAL_HOSTS = ("ons.gov.uk", "nomisweb", "gov.uk/government/statistics", "digital.nhs.uk", "nhsbsa", "openprescribing", "census", "nisra", "/statistics", "fingertips")
_PEER_HOSTS = ("pubmed", "nih.gov", "thelancet", "bmj.com", "nejm", "nature.com", "springer", "wiley", "doi.org", "sciencedirect", "jamanetwork", "europepmc")


def classify_chunk(chunk: str) -> tuple[str, str, str, str]:
    """(provenance_class, trust_tier, source_ref, body) from a chunk and its header."""
    m = _HEADER_RE.match(chunk)
    if m:
        kind = m.group(1).lower()
        detail = m.group(3).strip()
        ref = f"[SOURCE {kind}{(' ' + m.group(2)) if m.group(2) else ''} | {detail}]"
        body = chunk[m.end():].strip()
        low = detail.lower()
        if kind == "quant":
            return "official_statistic", "high", ref[:400], body
        if kind == "social":
            return "social_signal", "low", ref[:400], body
        if kind == "personal":
            return "client_data", "high", ref[:400], body
        if kind == "synthetic":
            return "model_inference", "low", ref[:400], body
        if kind == "youtube":
            return "grey_literature", "medium", ref[:400], body
        if any(h in low for h in _PEER_HOSTS):
            return "peer_reviewed", "high", ref[:400], body
        if any(h in low for h in _OFFICIAL_HOSTS):
            return "official_statistic", "high", ref[:400], body
        return "grey_literature", "medium", ref[:400], body
    p = _POST_RE.match(chunk)
    if p:
        return "model_inference", "low", f"debate: {p.group(1).strip()}"[:400], chunk[p.end():].strip()
    return "grey_literature", "medium", "", chunk.strip()


_TAG_SYSTEM = """You are tagging units of text from a knowledge base about a health-system question so that each unit
can be shown only to the people who would plausibly know it. For every unit, choose values ONLY from the
vocabulary below (exact spelling). Leave a list empty when nothing in the vocabulary fits — never invent.

- geography: every place the unit is about (all of them, not just the first).
- roles: who the unit is written for or about. Use the HCP roles listed, plus `patient` (people living with the
  condition) and `public` (anyone). A clinical audit → the HCP roles; a local news story → public; a leaflet → patient.
- channels: how a person would plausibly encounter this unit, from the channels listed.
- conditions, stages, segments: what the unit is about, from the lists.
- register: lay if a member of the public could read it as-is; professional for clinical, commissioning or policy
  content; technical for methods, statistics and trial detail.
- date: the date the unit refers to or was published, if stated (YYYY-MM-DD or YYYY); else empty.

Answer for every index you are given, in order.

VOCABULARY
{vocab}"""

_TAG_SCHEMA = obj({
    "units": arr(obj({
        "index": i("the unit's index in the list"),
        "geography": arr(s()),
        "roles": arr(s()),
        "channels": arr(s()),
        "conditions": arr(s()),
        "stages": arr(s()),
        "segments": arr(s()),
        "register": enum(REGISTER_LEVELS),
        "date": s(),
    })),
})


def _vocab_text(classes: dict[str, list[str]]) -> str:
    def line(label, key, extra=None):
        names = list(classes.get(key, [])) + (extra or [])
        return f"{label}: {', '.join(names) if names else '(none)'}"
    return "\n".join([
        line("geography", "geography"),
        line("roles", "hcp_role", ["patient", "public"]),
        line("channels", "channel"),
        line("conditions", "condition"),
        line("stages", "journey_stage"),
        line("segments", "attitude_segment"),
    ])


def _keep(values: list, allowed: set[str]) -> list[str]:
    out = []
    for v in values or []:
        v = str(v).strip()
        if v in allowed and v not in out:
            out.append(v)
    return out


async def tag_batch(bodies: list[str], classes: dict[str, list[str]], *, session_id: str, model: Optional[str]) -> list[dict]:
    system = _TAG_SYSTEM.format(vocab=_vocab_text(classes))
    user = "UNITS:\n" + "\n\n".join(f"{k}. {b[:900]}" for k, b in enumerate(bodies))
    res = await analyze(_TAG_SCHEMA, system, user, session_id=session_id, label="scoping_tag", model=model, max_tokens=6000)
    allowed = {
        "geography": set(classes.get("geography", [])),
        "role": set(classes.get("hcp_role", [])) | {"patient", "public"},
        "channel": set(classes.get("channel", [])),
        "condition": set(classes.get("condition", [])),
        "stage": set(classes.get("journey_stage", [])),
        "segment": set(classes.get("attitude_segment", [])),
    }
    out: list[dict] = [{} for _ in bodies]
    for u in res.get("units", []):
        try:
            k = int(u.get("index"))
        except (TypeError, ValueError):
            continue
        if not (0 <= k < len(bodies)):
            continue
        facets = {
            "geography": _keep(u.get("geography"), allowed["geography"]),
            "role": _keep(u.get("roles"), allowed["role"]),
            "channel": _keep(u.get("channels"), allowed["channel"]),
            "condition": _keep(u.get("conditions"), allowed["condition"]),
            "stage": _keep(u.get("stages"), allowed["stage"]),
            "segment": _keep(u.get("segments"), allowed["segment"]),
            "register": u.get("register") if u.get("register") in REGISTER_LEVELS else "lay",
        }
        d = looks_like_date(str(u.get("date") or ""))
        if d:
            facets["time"] = d
        out[k] = facets
    for k in range(len(bodies)):
        out[k].setdefault("register", "lay")
        for key in ("geography", "role", "channel", "condition", "stage", "segment"):
            out[k].setdefault(key, [])
    return out


async def tag_session(session_id: str, query: str, *, model: Optional[str] = None) -> dict:
    """Tag every chunk in the session's graph; wipe and rewrite the session's units. Returns the
    scoping state. Raises ValueError when there is nothing to tag."""
    from app.core.database import AsyncSessionLocal
    from app.models.scoping import KnowledgeUnit, ScopePolicy
    from app.services.knowledge_graph import ontology as onto_svc
    from app.services.knowledge_graph.lightrag_service import get_lightrag, _load_kg

    await get_lightrag(session_id)
    kg = _load_kg(session_id)
    chunks = [c for c in kg.get("chunks", []) if isinstance(c, str) and c.strip()][-MAX_UNITS:]
    if not chunks:
        raise ValueError("Nothing to tag — the knowledge graph has no chunks. Ingest sources or run research first.")

    onto = await onto_svc.load(session_id)
    if not onto or int(onto.get("entity_count", -1)) != len(kg.get("entities", [])):
        onto = await onto_svc.build(session_id, query, model=model)
    classes = nodes_by_class(onto)

    settings = get_settings()
    model = model or settings.model_fast
    parsed = [classify_chunk(c) for c in chunks]
    bodies = [p[3] for p in parsed]
    batches = [list(range(k, min(k + TAG_BATCH, len(bodies)))) for k in range(0, len(bodies), TAG_BATCH)]
    sem = asyncio.Semaphore(TAG_CONCURRENCY)
    facets_all: list[dict] = [{} for _ in bodies]

    async def one(idx: list[int]):
        async with sem:
            try:
                res = await tag_batch([bodies[k] for k in idx], classes, session_id=session_id, model=model)
            except Exception as e:  # noqa: BLE001 — a failed batch leaves its units unscoped, not missing
                print(f"[scoping] tag batch failed: {type(e).__name__}: {e}")
                res = [{"register": "lay", "geography": [], "role": [], "channel": [], "condition": [], "stage": [], "segment": []} for _ in idx]
            for k, f in zip(idx, res):
                facets_all[k] = f

    await asyncio.gather(*[one(b) for b in batches])

    snapshot_id = str(uuid.uuid4())
    now = datetime.utcnow()
    rows = []
    for (prov, trust, ref, body), f in zip(parsed, facets_all):
        if not body:
            continue
        f["project"] = session_id   # units belong to the session's project (L1-07 isolation is a hard dimension)
        rows.append(KnowledgeUnit(session_id=session_id, snapshot_id=snapshot_id, text=body[:2000], source_ref=ref,
                                  provenance_class=prov, trust_tier=trust, facets=f, created_at=now))

    async with AsyncSessionLocal() as db:
        await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.session_id == session_id))
        db.add_all(rows)
        existing = (await db.execute(select(ScopePolicy).where(ScopePolicy.session_id == session_id, ScopePolicy.layer == "session"))).scalars().first()
        if existing is None:
            db.add(ScopePolicy(session_id=session_id, layer="session", version=1, rules=list(DEFAULT_SESSION_RULES), note="default"))
        await db.commit()

    from . import service
    service.forget(session_id)
    return await service.state(session_id)
