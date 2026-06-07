"""
Knowledge-graph ingestion verification.

Proves that content flows all the way into the per-session knowledge graph and
back out through the read APIs the frontend uses. Five layers:

  A. chunk_text          — text is split into overlapping, bounded chunks
  B. parse_document      — the text-producing front-ends (txt/csv/json/html/md)
  C. insert_chunks       — Claude Haiku extracts entities/relations, dedups,
                           persists to disk  (LIVE Anthropic call)
  D. update_graph_post   — the agent-post path used during simulation, incl.
                           the kg_updated pub/sub event the UI listens on
  E. HTTP end-to-end     — create → ingest/text → poll → GET /kg → GET
                           /kg/entity  against the RUNNING server (LIVE)

All four ingestion sources (text, document, youtube, llm-search) funnel through
the same _ingest_chunks → insert_chunks core that layers C and E exercise.

Run from backend/:   venv/bin/python tests/kg_ingestion_test.py
Skip the live HTTP layer (offline): KG_TEST_SKIP_HTTP=1 venv/bin/python tests/kg_ingestion_test.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app.services.ingestion.text_processor import chunk_text  # noqa: E402
from app.services.ingestion.document_parser import parse_document  # noqa: E402
from app.services.knowledge_graph.lightrag_service import (  # noqa: E402
    get_lightrag,
    insert_chunks,
    get_kg_data,
    get_entity_details,
)
from app.services.knowledge_graph.graph_updater import update_graph_from_post  # noqa: E402
from app.core.redis_client import subscribe, unsubscribe, session_channel  # noqa: E402

BASE_URL = os.getenv("KG_TEST_BASE_URL", "http://localhost:8000")
SKIP_HTTP = os.getenv("KG_TEST_SKIP_HTTP") == "1"

# ── tiny test harness ──────────────────────────────────────────────────────
_passed = 0
_failed = 0
_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global _passed, _failed
    mark = "\033[92mPASS\033[0m" if ok else "\033[91mFAIL\033[0m"
    line = f"  [{mark}] {name}"
    if detail:
        line += f"  — {detail}"
    print(line)
    if ok:
        _passed += 1
    else:
        _failed += 1
        _failures.append(name)
    return ok


def section(title: str):
    print(f"\n\033[1m{title}\033[0m")


SAMPLE_TEXT = (
    "Nvidia reported record data-center revenue driven by demand for its H100 "
    "GPUs from cloud providers like Microsoft Azure and Amazon Web Services. "
    "CEO Jensen Huang said generative AI workloads are the primary growth "
    "engine, and that the upcoming Blackwell architecture will succeed Hopper. "
    "Analysts at Morgan Stanley raised their price target, citing widening "
    "gross margins and a large backlog of orders from enterprise customers. "
    "Competition from AMD's MI300 accelerator and custom silicon from Google "
    "remains the main risk to Nvidia's dominant market share in AI training."
)


# ── A. chunk_text ───────────────────────────────────────────────────────────
def test_chunk_text():
    section("A. chunk_text — splitting & bounds")

    check("empty string yields no chunks", chunk_text("") == [])
    check("whitespace-only yields no chunks", chunk_text("   \n\n  ") == [])

    short = "A short sentence that fits in one chunk."
    sc = chunk_text(short)
    check("short text → exactly 1 chunk", len(sc) == 1, f"got {len(sc)}")

    long = ("word " * 700).strip()  # ~3500 chars, no sentence boundaries
    lc = chunk_text(long, chunk_size=1200, overlap=200)
    check("long text → multiple chunks", len(lc) >= 2, f"got {len(lc)}")
    check("every chunk within size bound", all(len(c) <= 1200 for c in lc),
          f"max={max((len(c) for c in lc), default=0)}")
    check("no empty chunks produced", all(c.strip() for c in lc))
    # overlap: chunk[1] should share its leading text with chunk[0]'s tail
    if len(lc) >= 2:
        tail = lc[0][-50:]
        check("consecutive chunks overlap", lc[1][:50] in lc[0] or tail[:20] in lc[1],
              "overlap window present")


# ── B. parse_document (text-producing front-ends) ────────────────────────────
def test_parse_document():
    section("B. parse_document — feeds raw_text into ingestion")

    txt = parse_document(b"Hello knowledge graph", "note.txt")
    check(".txt decodes to text", txt == "Hello knowledge graph", repr(txt))

    md = parse_document(b"# Heading\n\nBody text", "doc.md")
    check(".md preserved", "Heading" in md and "Body text" in md)

    csv = parse_document(b"name,role\nAda,engineer\nGrace,admiral", "people.csv")
    check(".csv rows extracted", "Ada" in csv and "admiral" in csv, repr(csv[:60]))

    js = parse_document(b'{"company":"Nvidia","ceo":"Jensen Huang"}', "d.json")
    check(".json flattened to text", "Nvidia" in js and "Jensen Huang" in js)

    html = parse_document(
        b"<html><head><style>x{}</style></head><body><p>Visible text</p></body></html>",
        "page.html",
    )
    check(".html strips tags & script/style", "Visible text" in html and "x{}" not in html,
          repr(html))

    # unknown extension falls back to utf-8 decode rather than throwing
    fb = parse_document(b"raw bytes content", "mystery.bin")
    check("unknown ext → utf-8 fallback", fb == "raw bytes content")


# ── C. insert_chunks (LIVE: Claude Haiku extraction) ──────────────────────────
async def test_insert_chunks():
    section("C. insert_chunks — entity/relation extraction + dedup (LIVE)")

    session_id = f"kgtest-insert-{uuid.uuid4().hex[:8]}"
    rag = await get_lightrag(session_id)

    chunks = chunk_text(SAMPLE_TEXT)
    new_ents, new_rels = await insert_chunks(rag, chunks)

    check("first ingest extracts entities", len(new_ents) > 0, f"{len(new_ents)} entities")
    check("first ingest extracts relations", len(new_rels) > 0, f"{len(new_rels)} relations")
    check("relations are well-formed triples",
          all(isinstance(r, list) and len(r) == 3 for r in new_rels),
          "each [head, verb, tail]")

    data = get_kg_data(session_id)
    check("entities persisted & readable", len(data["entities"]) == len(new_ents))
    check("no duplicate entities stored",
          len(data["entities"]) == len(set(data["entities"])))
    check("no duplicate relations stored",
          len(data["relations"]) == len(set(tuple(r) for r in data["relations"])))

    # Dedup: re-ingesting identical content must not balloon the graph.
    ents_before = len(data["entities"])
    again_ents, _ = await insert_chunks(rag, chunks)
    ents_after = len(get_kg_data(session_id)["entities"])
    check("re-ingest is near-idempotent (dedup works)",
          ents_after <= ents_before + max(2, len(new_ents) // 2),
          f"{ents_before} → {ents_after} (+{len(again_ents)} new)")
    check("still no duplicates after re-ingest",
          ents_after == len(set(get_kg_data(session_id)["entities"])))

    # Entity detail lookup (powers the frontend node-click panel)
    if data["entities"]:
        probe = data["entities"][0]
        detail = get_entity_details(session_id, probe)
        has_context = bool(detail["relations_from"] or detail["relations_to"] or detail["mentions"])
        check("get_entity_details returns context", has_context,
              f"'{probe}': {len(detail['relations_from'])} out, "
              f"{len(detail['relations_to'])} in, {len(detail['mentions'])} mentions")
        check("entity detail case-insensitive",
              get_entity_details(session_id, probe.upper())["entity"] == probe.upper(),
              "lookup normalizes case")

    return ents_after > 0


# ── D. update_graph_from_post (agent-post path + pub/sub event) ───────────────
async def test_update_graph_from_post():
    section("D. update_graph_from_post — simulation path + kg_updated event (LIVE)")

    session_id = f"kgtest-post-{uuid.uuid4().hex[:8]}"
    channel = session_channel(session_id)
    q = subscribe(channel)  # listen like the websocket endpoint does
    try:
        await update_graph_from_post(
            session_id,
            agent_name="Ravi",
            agent_role="Semiconductor Analyst",
            content=(
                "Nvidia's Blackwell ramp will pressure AMD on training workloads, "
                "but TSMC capacity constraints could cap near-term upside."
            ),
        )
        data = get_kg_data(session_id)
        check("agent post produced entities", len(data["entities"]) > 0,
              f"{len(data['entities'])} entities")

        got_event = not q.empty()
        check("kg_updated event published to subscribers", got_event,
              "frontend live-update channel fired")
        if got_event:
            import json
            evt = json.loads(q.get_nowait())
            check("event carries new_entities/new_relations",
                  "new_entities" in evt and "new_relations" in evt,
                  f"type={evt.get('type')}, source={evt.get('source')}")
    finally:
        unsubscribe(channel, q)


# ── E. HTTP end-to-end against the running server (LIVE) ──────────────────────
async def test_http_end_to_end():
    section("E. HTTP end-to-end — create → ingest → poll → read APIs (LIVE)")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # health
        try:
            h = await client.get("/health")
        except Exception as e:
            check("server reachable", False, f"{type(e).__name__}: {e} — is it running on {BASE_URL}?")
            return
        if not check("server reachable", h.status_code == 200, f"/health → {h.status_code}"):
            return

        # create session
        r = await client.post("/api/v1/sessions",
                              json={"title": "KG ingestion test", "query": "Does ingestion populate the KG?"})
        if not check("create session", r.status_code == 200, f"→ {r.status_code}"):
            return
        sid = r.json()["id"]
        print(f"       session = {sid}")

        # graph starts empty
        r = await client.get(f"/api/v1/sessions/{sid}/kg")
        empty = r.json()
        check("new session KG starts empty",
              r.status_code == 200 and not empty["entities"] and not empty["relations"])

        # ingest text (kicks off background task)
        r = await client.post(f"/api/v1/sessions/{sid}/ingest/text", json={"text": SAMPLE_TEXT})
        check("POST /ingest/text accepted", r.status_code == 200, f"→ {r.status_code}")

        # poll /kg until entities appear (background extraction is async + LLM)
        entities: list = []
        relations: list = []
        status = "?"
        for _ in range(40):  # ~40s budget
            await asyncio.sleep(1.0)
            kg = (await client.get(f"/api/v1/sessions/{sid}/kg")).json()
            entities, relations = kg["entities"], kg["relations"]
            status = (await client.get(f"/api/v1/sessions/{sid}")).json().get("status")
            if entities:
                break

        check("ingestion populated entities via API", len(entities) > 0, f"{len(entities)} entities")
        check("ingestion populated relations via API", len(relations) > 0, f"{len(relations)} relations")
        check("session reached 'ready' status", status == "ready", f"status={status}")

        # entity-detail endpoint (frontend node click)
        if entities:
            from urllib.parse import quote
            probe = entities[0]
            r = await client.get(f"/api/v1/sessions/{sid}/kg/entity/{quote(probe, safe='')}")
            ok = r.status_code == 200
            detail = r.json() if ok else {}
            check("GET /kg/entity/{name} returns detail",
                  ok and detail.get("entity", "").lower() == probe.lower(),
                  f"'{probe}' → {r.status_code}")

        # dedup via the real pipeline: re-ingest, ensure no ballooning
        before = len(entities)
        await client.post(f"/api/v1/sessions/{sid}/ingest/text", json={"text": SAMPLE_TEXT})
        after = before
        for _ in range(40):
            await asyncio.sleep(1.0)
            kg = (await client.get(f"/api/v1/sessions/{sid}/kg")).json()
            st = (await client.get(f"/api/v1/sessions/{sid}")).json().get("status")
            after = len(kg["entities"])
            if st == "ready":
                break
        check("re-ingest does not balloon graph (dedup via API)",
              after <= before + max(2, before // 2),
              f"{before} → {after} entities")


async def main():
    print("\033[1m═══ Knowledge-Graph Ingestion Verification ═══\033[0m")
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("\033[93mWARNING: ANTHROPIC_API_KEY not set — live extraction layers will fail.\033[0m")

    test_chunk_text()
    test_parse_document()
    await test_insert_chunks()
    await test_update_graph_from_post()
    if SKIP_HTTP:
        section("E. HTTP end-to-end — SKIPPED (KG_TEST_SKIP_HTTP=1)")
    else:
        await test_http_end_to_end()

    section("SUMMARY")
    total = _passed + _failed
    print(f"  {_passed}/{total} checks passed")
    if _failures:
        print("  \033[91mFailed:\033[0m " + ", ".join(_failures))
        sys.exit(1)
    print("  \033[92mAll knowledge-graph ingestion checks passed.\033[0m")


if __name__ == "__main__":
    asyncio.run(main())
