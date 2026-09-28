"""Outcome records (brief L6-01): every figure in a report is computed, cited, never typed.

Run:  cd backend && pytest tests/records_test.py -q
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.simulation import records as rec  # noqa: E402
from app.services.measurement.instruments import verdict as verdict_inst  # noqa: E402


def _probe(**kw):
    base = dict(id="p1", instrument="purchase_intent", spec={"price": 9.9, "currency": "GBP", "stimulus": "Mounjaro on prescription"},
                seed=7, schema_id="purchase_intent.v1", prompt_hash="abc", model="claude-haiku-4-5", agent_count=12, answer_count=12,
                created_at=datetime(2026, 9, 24, 12, 0),
                aggregates={"n": 12, "headline": {"metric": "would_buy_share", "label": "Would buy", "share": 0.75, "low": 0.47, "high": 0.91, "n": 12, "successes": 9},
                            "sentence": "75% would buy.", "segments": {"stance": [{"value": "direct", "share": 1.0, "n": 8}, {"value": "indirect", "share": 0.33, "n": 3}]},
                            "dont_know": {"n": 12, "refused": 0, "share": 0.0, "reasons": [], "who": []}})
    base.update(kw)
    return SimpleNamespace(**base)


# ── shaping ──────────────────────────────────────────────────────────────────

def test_a_probe_becomes_a_record_with_estimate_splits_provenance_and_confidence():
    r = rec.record_from_probe(_probe(), evidence_mix={"web": 23, "quant": 3}, frame={"report": {"level": "fair", "estimated": ["Age"], "thin_cells": ["65+ (n=1)"]}})
    assert r["id"] == "p1" and r["kind"] == "probe" and r["label"] == "Would buy at £9.9" and r["basis"] == "simulated"
    assert r["estimate"] == {"metric": "would_buy_share", "label": "Would buy", "format": "share", "value": 0.75, "low": 0.47, "high": 0.91, "n": 12, "successes": 9}
    assert r["splits"]["stance"][0]["value"] == "direct"
    assert r["provenance"]["evidence_mix"] == {"web": 23, "quant": 3} and r["provenance"]["frame_level"] == "fair" and r["provenance"]["seed"] == 7
    assert 5 <= r["confidence"]["score"] <= 95 and "12 twins answered" in r["confidence"]["drivers"]
    assert any(c.startswith("Model-estimated distributions: Age") for c in r["caveats"]) and any("Synthetic population" in c for c in r["caveats"])
    assert r["tags"] == {}


def test_the_verdict_probe_is_the_headline_record():
    p = _probe(id="v1", instrument="verdict", spec={"question": "Should GPs prescribe?", "stimulus": "Should GPs prescribe?"},
               aggregates={"n": 12, "headline": {"metric": "for_share", "label": "In favour", "share": 0.83, "low": 0.55, "high": 0.95, "n": 12, "successes": 10},
                           "sentence": "83% in favour.", "position": [{"value": "for", "count": 10, "share": 0.83}], "segments": {}})
    r = rec.record_from_probe(p)
    assert r["kind"] == "headline" and r["label"] == "Population verdict on the question" and r["question"] == "Should GPs prescribe?"
    assert r["distribution"][0]["value"] == "for"


def test_confidence_moves_for_the_right_reasons():
    hi = rec.confidence_for(n=40, low=0.6, high=0.7, fmt="share", unanimity=None, refusals=None, frame_level="good", weighted=True, model="claude-sonnet-4-6")
    lo = rec.confidence_for(n=6, low=0.2, high=0.9, fmt="share", unanimity={"flagged": True}, refusals={"share": 0.5}, frame_level=None, weighted=False)
    assert hi["score"] == 95 and lo["score"] == 5
    assert "only 6 twins answered" in lo["drivers"] and "agreement the population should not have produced" in lo["drivers"]
    assert "no sampling frame" in lo["drivers"] and "Pro model" in hi["drivers"]


def test_an_experiment_becomes_a_lift_record():
    e = SimpleNamespace(id="e1", instrument="purchase_intent", name="£9.90 vs £19.90", model="m", seed=3, created_at=datetime(2026, 9, 24),
                        results={"design": "within", "instrument": "purchase_intent", "arms": [{"key": "A", "n": 12}, {"key": "B", "n": 12}], "verdict": "B loses 25 points.",
                                 "comparisons": [{"variant": "B", "label": "£19.90", "control": "A", "control_label": "£9.90", "n": 12,
                                                  "metrics": [{"key": "would_buy", "label": "Would buy", "primary": True, "control": 0.75, "variant": 0.5,
                                                               "lift": {"mean": -0.25, "low": -0.45, "high": -0.05, "n": 12, "significant": True}}],
                                                  "segments": {}}]})
    r = rec.record_from_experiment(e)
    assert r["kind"] == "experiment" and r["estimate"]["format"] == "lift" and r["estimate"]["value"] == -0.25 and r["estimate"]["significant"]
    assert r["label"] == "£19.90 vs £9.90: lift in Would buy" and r["sentence"] == "B loses 25 points."
    assert not any("not significant" in c for c in r["caveats"])


def test_incomplete_results_give_no_record():
    assert rec.record_from_probe(_probe(aggregates=None)) is None
    assert rec.record_from_experiment(SimpleNamespace(id="e", results={})) is None


# ── the prompt side ───────────────────────────────────────────────────────────

def test_records_block_numbers_records_and_handles_resolve():
    r1 = rec.record_from_probe(_probe(id="11111111-1111-1111-1111-111111111111"))
    r2 = rec.record_from_probe(_probe(id="22222222-2222-2222-2222-222222222222", instrument="verdict", aggregates={"n": 12, "headline": {"metric": "for_share", "label": "In favour", "share": 0.83, "low": 0.55, "high": 0.95, "n": 12, "successes": 10}, "sentence": "s", "unanimity": {"flagged": True, "reason": "x"}, "dont_know": {"refused": 2, "n": 12, "share": 0.17}}))
    text, handles = rec.records_block([r2, r1])
    assert text.startswith("[[R1]] Population verdict on the question — In favour: 83% (95% CI 55–95%, n=12)")
    assert "FLAGGED: more unanimous" in text and "2 refused to answer" in text
    assert "[[R2]] Would buy at £9.9 — Would buy: 75% (95% CI 47–91%, n=12)" in text and "splits: stance: direct 100% vs indirect 33%" in text
    out = rec.resolve_handles("Most are in favour [[R1]], and 75% would buy [[r2]]; nothing here [[R7]].", handles)
    assert out == "Most are in favour [[record:22222222-2222-2222-2222-222222222222]], and 75% would buy [[record:11111111-1111-1111-1111-111111111111]]; nothing here ."
    assert rec.cited_record_ids(out) == ["22222222-2222-2222-2222-222222222222", "11111111-1111-1111-1111-111111111111"]
    assert rec.records_block([])[0].startswith("(none")


def test_figure_rules_forbid_typed_population_figures():
    assert "Do NOT type a figure about the population that is not in a record" in rec.FIGURE_RULES


# ── the verdict instrument ────────────────────────────────────────────────────

def test_verdict_aggregate_reports_the_for_share_with_splits():
    rows = [{"agent_id": f"a{k}", "agent": {"name": f"N{k}", "role": "r"}, "segments": {"stance": "direct" if k < 4 else "neutral"},
             "answer": {"position": "for" if k < 5 else "against", "confidence": 60 + k, "verdict": f"line {k}", "reasoning": "why"}} for k in range(8)]
    agg = verdict_inst.aggregate(rows, {"seed": 1})
    assert agg["headline"]["metric"] == "for_share" and agg["headline"]["successes"] == 5 and agg["n"] == 8
    assert agg["against"]["successes"] == 3 and agg["verbatims"]["for"][0]["verdict"] == "line 0"
    assert "5 of 8" in agg["sentence"]
    from app.services.measurement import instruments
    instruments._load()
    assert instruments.get("verdict").hidden is True


# ── the report waits for its headline ─────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.core.database as dbm
    from app.core.config import get_settings
    import app.models.report, app.models.preset, app.models.kg, app.models.population, app.models.archetype  # noqa: F401
    from app.services.measurement import probe as probe_svc
    from app.services.simulation import report_generator

    monkeypatch.setattr(get_settings(), "app_supabase_url", "")
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/records.db")
    Session = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(dbm, "engine", eng)
    monkeypatch.setattr(dbm, "AsyncSessionLocal", Session)
    monkeypatch.setattr(rec, "AsyncSessionLocal", Session)
    monkeypatch.setattr(dbm, "_sqlite", True)

    runs = []

    async def fake_run_probe(probe_id, **kw):
        """Complete the verdict probe with typed answers, the way the real runner would."""
        from app.models.measurement import Probe, ProbeAnswer
        from app.models.agent import SpawnedAgent
        from sqlalchemy import select
        runs.append(probe_id)
        async with Session() as db:
            p = await db.get(Probe, probe_id)
            agents = (await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == p.session_id))).scalars().all()
            rows = []
            for k, a in enumerate(agents):
                ans = {"position": "for" if k % 3 else "against", "confidence": 70, "verdict": f"{a.name} says so", "reasoning": "r", "can_answer": "yes"}
                db.add(ProbeAnswer(probe_id=probe_id, session_id=p.session_id, agent_id=a.id, answer=ans, reasoning="r"))
                rows.append({"agent_id": a.id, "agent": {"name": a.name, "role": a.role}, "segments": {"stance": a.stance.value}, "answer": ans})
            agg = verdict_inst.aggregate(rows, {"seed": 1})
            agg["dont_know"] = {"n": len(rows), "refused": 0, "share": 0.0, "reasons": [], "who": []}
            p.status, p.agent_count, p.answer_count, p.aggregates = "complete", len(agents), len(agents), agg
            await db.commit()

    monkeypatch.setattr(probe_svc, "run_probe", fake_run_probe)

    seen = {}

    async def fake_create(client_, *, session_id=None, label="", **kw):
        seen["system"] = kw["system"]; seen["prompt"] = kw["messages"][0]["content"]
        class R:
            content = [type("T", (), {"text": "## DIRECT ANSWER\nMost are in favour [[R1]] — [[A1]] said so.\nConfidence: HIGH\n\n## OUTCOME\nGo ahead [[R9]]."})()]
        return R()

    monkeypatch.setattr(report_generator, "tracked_messages_create", fake_create)

    async def fake_rag(session_id):
        return "rag"

    async def fake_query(rag, q, mode="hybrid"):
        return "kg"

    monkeypatch.setattr(report_generator, "get_lightrag", fake_rag)
    monkeypatch.setattr(report_generator, "query_rag", fake_query)

    async def _get_db():
        async with Session() as s:
            yield s

    from fastapi.testclient import TestClient
    from app.main import app
    app.dependency_overrides[dbm.get_db] = _get_db
    with TestClient(app) as c:
        yield c, runs, seen
    app.dependency_overrides.clear()


def test_generate_runs_the_verdict_once_and_renders_from_records(client):
    c, runs, seen = client
    sid = c.post("/api/v1/sessions", json={"title": "t", "query": "Should GPs prescribe GLP-1s?", "auto_research": False}).json()["id"]
    assert c.get(f"/api/v1/sessions/{sid}/records").json() == {"records": []}
    r = c.post(f"/api/v1/sessions/{sid}/spawn-agents", json={"count": 6, "mode": "fast"})
    assert r.status_code == 200, r.text
    import time
    for _ in range(40):
        if len(c.get(f"/api/v1/sessions/{sid}/agents").json()) == 6:
            break
        time.sleep(0.1)

    r = c.post(f"/api/v1/sessions/{sid}/report/generate", json={"question": "Write the report"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(runs) == 1                                             # the headline verdict ran once
    recs = body["records"]
    assert len(recs) == 1 and recs[0]["kind"] == "headline" and recs[0]["estimate"]["n"] == 6
    rid = recs[0]["id"]
    assert f"[[record:{rid}]]" in body["answer"] and "[[R9]]" not in body["answer"] and "[[R1]]" not in body["answer"]
    assert "[[twin:" in body["answer"]                                  # twin handles still resolve alongside
    assert "== OUTCOME RECORDS (1 computed" in seen["prompt"] and "Do NOT type a figure" in seen["system"]
    assert "outcome record(s) cited" in body["sources"]

    # the one-liners reached the roster, and a second report reuses the record
    agents = c.get(f"/api/v1/sessions/{sid}/agents").json()
    assert all(a["verdict"] and a["verdict"].endswith("says so") for a in agents)
    c.post(f"/api/v1/sessions/{sid}/report/generate", json={"question": "Again"})
    assert len(runs) == 1
    assert c.get(f"/api/v1/sessions/{sid}/records").json()["records"][0]["id"] == rid
