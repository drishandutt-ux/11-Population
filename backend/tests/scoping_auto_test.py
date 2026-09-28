"""Scoping as a pipeline step (brief L1-04 wired end to end): tagged automatically when knowledge
lands, awaited before personas are written, a debate starts or a probe runs; every twin records
what it was written from and can see.

Run:  cd backend && pytest tests/scoping_auto_test.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.scoping import auto, service, tagger  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def quiet_emit(monkeypatch):
    events = []

    async def fake_emit(session_id, event):
        events.append(event)

    monkeypatch.setattr(auto, "_emit", fake_emit)
    return events


def test_a_segment_becomes_a_stand_in_twin_for_the_exposure_profile():
    seg = {"name": "Coastal patients", "description": "Adults with obesity in Blackpool", "register": "reactive",
           "demographics": {"regions": ["Blackpool, England", "Fleetwood"], "occupations": ["care worker", "taxi driver"]}}
    seed = auto.segment_seed(seg)
    assert seed.role == "care worker" and seed.demographics == {"region": "Blackpool, England"} and seed.humanity == 80 and seed.segment == "Coastal patients"
    cast = auto.segment_seed(seg, role="GP partner", region="Fleetwood")
    assert cast.role == "GP partner" and cast.demographics["region"] == "Fleetwood"
    assert auto.segment_seed({"name": "x"}).humanity == 50


def test_ensure_tagged_runs_only_when_untagged_or_stale_and_announces_itself(monkeypatch, quiet_emit):
    states = {"s1": {"tagged": False, "stale": False, "chunk_count": 12, "unit_count": 0}}
    calls = []

    async def fake_state(session_id):
        return states[session_id]

    async def fake_tag(session_id, query, model=None):
        calls.append((session_id, query))
        states[session_id] = {"tagged": True, "stale": False, "chunk_count": 12, "unit_count": 12, "snapshot_id": "snap", "counts": {}}
        return states[session_id]

    async def fake_annotate(session_id, query=None, *, reason="", agent_ids=None):
        return 0

    monkeypatch.setattr(service, "state", fake_state)
    monkeypatch.setattr(tagger, "tag_session", fake_tag)
    monkeypatch.setattr(auto, "annotate_agents", fake_annotate)
    from app.services.knowledge_graph import lightrag_service as lr
    monkeypatch.setitem(lr._kg_cache, "s1", {"entities": [], "relations": [], "chunks": ["[SOURCE web | a | u | 2024]\nchunk"] * 12})
    monkeypatch.setitem(lr._kg_cache, "s2", {"entities": [], "relations": [], "chunks": []})

    st = _run(auto.ensure_tagged("s1", "Q?", reason="build", warm=False))
    assert st["tagged"] and calls == [("s1", "Q?")]
    assert [e["type"] for e in quiet_emit] == ["scoping_started", "scoping_complete"] and quiet_emit[1]["unit_count"] == 12
    # already tagged and fresh: nothing happens
    _run(auto.ensure_tagged("s1", "Q?", reason="debate", warm=False))
    assert len(calls) == 1
    # the graph grew: stale → tagged again
    states["s1"]["stale"] = True
    _run(auto.ensure_tagged("s1", "Q?", reason="probe", warm=False))
    assert len(calls) == 2
    # nothing ingested: nothing to tag, no event
    states["s2"] = {"tagged": False, "stale": False, "chunk_count": 0, "unit_count": 0}
    quiet_emit.clear()
    assert _run(auto.ensure_tagged("s2", "Q?", reason="build", warm=False))["tagged"] is False and quiet_emit == []


def test_a_failed_tag_is_reported_and_the_caller_carries_on_unscoped(monkeypatch, quiet_emit):
    async def fake_state(session_id):
        return {"tagged": False, "stale": False, "chunk_count": 3, "unit_count": 0}

    async def fake_tag(session_id, query, model=None):
        raise RuntimeError("model down")

    monkeypatch.setattr(service, "state", fake_state)
    monkeypatch.setattr(tagger, "tag_session", fake_tag)
    from app.services.knowledge_graph import lightrag_service as lr
    monkeypatch.setitem(lr._kg_cache, "s3", {"entities": [], "relations": [], "chunks": ["[SOURCE web | a | u | 2024]\nchunk"] * 3})
    st = _run(auto.ensure_tagged("s3", "Q?", reason="debate", warm=False))
    assert st["tagged"] is False and quiet_emit[-1]["type"] == "scoping_error" and "model down" in quiet_emit[-1]["error"]


def test_the_knowledge_record_says_what_a_twin_can_see_and_where_from(monkeypatch):
    profile = {"values": {"geography": ["Blackpool"], "role": ["patient", "public"], "register": "lay", "channel": ["Local press"], "segment": []},
               "basis": {"geography": "demographics.region = 'Blackpool'"}}
    res = {"visible": [{"unit": {"id": "u1", "provenance_class": "official_statistic"}, "route": "via Local press"},
                       {"unit": {"id": "u2", "provenance_class": "social_signal"}, "route": "from people talking about it online"}],
           "visible_total": 2, "hidden": [{"unit": {"id": "u3"}, "failed": []}] * 5}

    async def fake_retrieval(session_id, agent, query, *, purpose="post", limit=14, log=True):
        return profile, res, "snap-1", 2

    monkeypatch.setattr(service, "retrieval_for_agent", fake_retrieval)
    rec = _run(auto.knowledge_for_agent("s", SimpleNamespace(id="a1"), "Q?", written_from="scoped"))
    assert rec["visible"] == 2 and rec["total"] == 7 and rec["snapshot_id"] == "snap-1" and rec["policy_version"] == 2
    assert rec["unit_ids"] == ["u1", "u2"] and rec["routes"] == ["from people talking about it online", "via Local press"]
    assert rec["provenance"] == {"official_statistic": 1, "social_signal": 1} and rec["profile"]["register"] == "lay" and "segment" not in rec["profile"]
    assert rec["written_from"] == "scoped" and rec["basis"]["geography"].startswith("demographics.region")

    async def not_scoped(session_id, agent, query, *, purpose="post", limit=14, log=True):
        return None

    monkeypatch.setattr(service, "retrieval_for_agent", not_scoped)
    assert _run(auto.knowledge_for_agent("s", SimpleNamespace(id="a1"), "Q?")) is None


def test_the_segment_context_is_the_scoped_block_with_a_writer_heading(monkeypatch):
    async def fake_ctx(session_id, agent, query, *, purpose="post", limit=14, log=True):
        assert purpose == "write" and log is False and agent.segment == "Seg"
        return "- [via Local press] Blackpool surgery closures"

    monkeypatch.setattr(service, "context_for_agent", fake_ctx)
    block = _run(auto.context_for_segment("s", {"name": "Seg"}, "Q?"))
    assert block.startswith("WHAT PEOPLE LIKE THIS WOULD ACTUALLY KNOW") and "Blackpool surgery closures" in block

    async def none_ctx(session_id, agent, query, *, purpose="post", limit=14, log=True):
        return None

    monkeypatch.setattr(service, "context_for_agent", none_ctx)
    assert _run(auto.context_for_segment("s", {"name": "Seg"}, "Q?")) is None


def test_a_probe_record_carries_whether_its_answers_were_scoped():
    from app.services.simulation import records as rec
    p = SimpleNamespace(id="p", instrument="verdict", spec={"question": "Q"}, seed=1, schema_id="v", prompt_hash="h", model="m", agent_count=3, answer_count=3, created_at=None,
                        aggregates={"n": 3, "headline": {"metric": "for_share", "label": "In favour", "share": 0.67, "low": 0.2, "high": 0.9, "n": 3, "successes": 2},
                                    "sentence": "s", "segments": {}, "scoping": {"scoped": True, "snapshot_id": "snap-9"}})
    r = rec.record_from_probe(p)
    assert r["provenance"]["scoped"] is True and r["provenance"]["scoping_snapshot"] == "snap-9"
    p.aggregates = {**p.aggregates, "scoping": {"scoped": False, "snapshot_id": None}}
    assert rec.record_from_probe(p)["provenance"]["scoped"] is False
