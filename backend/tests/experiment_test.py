"""Tests for the Behaviour Lab experiments layer (A/B/n on the probe primitive).

Run:  cd backend && pytest tests/experiment_test.py -q
In-memory SQLite plus a stubbed model — no API key, no network.

What makes an A/B result trustworthy: the same agents answer every arm (within-subjects),
an agent never sees its own answer to the other arm, the lift is paired with an honest
interval, flips are real changes of decision, and the verdict says what the numbers say.
"""
import asyncio
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.models.session import AnalysisSession, SessionStatus  # noqa: E402
from app.models.agent import SpawnedAgent, AgentStance  # noqa: E402
from app.models.measurement import Experiment, Probe, ProbeAnswer  # noqa: E402
from app.services.measurement import experiment as exp_svc  # noqa: E402
from app.services.measurement import instruments, stats  # noqa: E402

from tests.measurement_test import _agent, lab_db, api_client, _async  # noqa: E402,F401


PI = instruments.get("purchase_intent")


def _row(agent_id, *, buy, likelihood=50, price=10.0, driver="price", sentiment=0.0, stance="neutral", age="25-34", name=""):
    return {
        "agent_id": agent_id,
        "agent": {"name": name or agent_id, "role": "r", "avatar_color": "#000"},
        "answer": {"reasoning": f"because {driver}", "would_buy": buy, "likelihood_0_100": likelihood,
                   "max_price": price, "key_driver": driver, "sentiment": sentiment},
        "segments": {"stance": stance, "age_band": age, "humanity_band": "balanced", "purchase_intent_prior": "mid"},
    }


# ── declarations ──────────────────────────────────────────────────────────────

def test_purchase_intent_declares_metrics_with_one_primary():
    assert PI.supports_experiments()
    assert sum(1 for m in PI.metrics if m.primary) == 1
    assert PI.primary_metric().key == "would_buy"
    assert PI.decision_key == "would_buy" and PI.driver_key == "key_driver"
    a = {"would_buy": "yes", "likelihood_0_100": 70, "max_price": 12.5, "sentiment": 0.4}
    values = {m.key: m.value(a) for m in PI.metrics}
    assert values == {"would_buy": 1.0, "likelihood_0_100": 70.0, "max_price": 12.5, "sentiment": 0.4}


def test_instrument_payload_advertises_experiment_support():
    from app.api.v1.measurement import _instrument_payload
    p = _instrument_payload(PI)
    assert p["supports_experiments"] is True
    assert [m["key"] for m in p["metrics"]] == ["would_buy", "likelihood_0_100", "max_price", "sentiment"]
    assert p["decision_key"] == "would_buy"


# ── stats ─────────────────────────────────────────────────────────────────────

def test_unpaired_lift_detects_a_real_difference_and_is_wider_than_paired():
    a, b = [10.0] * 20 + [20.0] * 20, [20.0] * 20 + [30.0] * 20
    un = stats.unpaired_lift(a, b, seed=1)
    assert un["mean"] == pytest.approx(10.0) and un["significant"] is True
    pa = stats.paired_lift(list(zip(a, b)), seed=1)
    assert (un["high"] - un["low"]) > (pa["high"] - pa["low"])
    assert stats.unpaired_lift([], [1.0])["significant"] is False


def test_split_between_is_disjoint_seeded_and_balanced():
    agents = [_agent(session_id="s", name=f"A{i}") for i in range(11)]
    g1 = exp_svc.split_between(agents, 2, seed=5)
    g2 = exp_svc.split_between(agents, 2, seed=5)
    assert g1 == g2
    assert set(g1[0]).isdisjoint(g1[1]) and len(g1[0]) + len(g1[1]) == 11
    assert abs(len(g1[0]) - len(g1[1])) <= 1
    assert exp_svc.split_between(agents, 2, seed=6) != g1


# ── analysis ──────────────────────────────────────────────────────────────────

def _variants():
    return [
        {"key": "A", "label": "A", "spec": {"stimulus": "£12/month", "price": 12, "currency": "GBP"}},
        {"key": "B", "label": "B", "spec": {"stimulus": "£8/month", "price": 8, "currency": "GBP"}},
    ]


def test_within_subjects_lift_is_paired_and_flips_are_real_changes():
    # 10 agents: 3 buy at A; at B those 3 plus 5 more buy → 8. Two never buy.
    a_rows, b_rows = {}, {}
    for i in range(10):
        aid = f"agent{i:02d}"
        buy_a = "yes" if i < 3 else "no"
        buy_b = "yes" if i < 8 else "no"
        a_rows[aid] = _row(aid, buy=buy_a, likelihood=30 + i, price=9.0, driver="price", stance="direct" if i < 5 else "indirect")
        b_rows[aid] = _row(aid, buy=buy_b, likelihood=60 + i, price=9.0, driver="need" if buy_b == "yes" else "price",
                           stance="direct" if i < 5 else "indirect")
    res = exp_svc.analyse(PI, "within", _variants(), {"A": a_rows, "B": b_rows}, seed=3)

    assert res["design"] == "within" and res["control"] == "A" and res["primary_metric"] == "would_buy"
    assert [a["n"] for a in res["arms"]] == [10, 10]
    cmp = res["comparisons"][0]
    assert cmp["variant"] == "B" and cmp["n"] == 10

    by_key = {m["key"]: m for m in cmp["metrics"]}
    wb = by_key["would_buy"]
    assert wb["primary"] and wb["control"] == 0.3 and wb["variant"] == 0.8
    assert wb["lift"]["mean"] == pytest.approx(0.5) and wb["lift"]["significant"] is True
    assert by_key["likelihood_0_100"]["lift"]["mean"] == pytest.approx(30.0)
    # Same walk-away price in both arms → zero lift, and not significant.
    assert by_key["max_price"]["lift"]["mean"] == 0.0 and by_key["max_price"]["lift"]["significant"] is False
    assert by_key["max_price"]["currency"] == "GBP"

    flips = cmp["flips"]
    assert flips["n"] == 5 and flips["paired"] == 10
    assert all(r["from"] == "no" and r["to"] == "yes" for r in flips["rows"])
    assert flips["direction"][0]["value"] == "no → yes" and flips["direction"][0]["count"] == 5
    # The flow matrix covers every paired agent, stayers included: 3 yes→yes, 5 no→yes, 2 no→no.
    assert {(m["from"], m["to"]): m["count"] for m in flips["matrix"]} == {("yes", "yes"): 3, ("no", "yes"): 5, ("no", "no"): 2}
    assert flips["reasons"][0]["value"] == "need"
    assert flips["rows"][0]["reasoning_variant"] and flips["rows"][0]["reasoning_control"]

    seg = {r["value"]: r for r in cmp["segments"]["stance"]}
    assert set(seg) == {"direct", "indirect"} and not seg["direct"]["thin"]
    # direct: 3 of 5 buy at A, 5 of 5 at B (+0.4); indirect: 0 of 5 → 3 of 5 (+0.6)
    assert seg["direct"]["mean"] == pytest.approx(0.4) and seg["indirect"]["mean"] == pytest.approx(0.6)

    assert "B beats A on would buy by 50 points" in cmp["sentence"]
    assert "driven by need" in cmp["sentence"]
    assert res["verdict"] == cmp["sentence"]


def test_within_subjects_only_pairs_agents_who_answered_both_arms():
    a_rows = {f"a{i}": _row(f"a{i}", buy="no") for i in range(6)}
    b_rows = {f"a{i}": _row(f"a{i}", buy="yes") for i in range(4)}   # two agents failed in arm B
    res = exp_svc.analyse(PI, "within", _variants(), {"A": a_rows, "B": b_rows}, seed=1)
    cmp = res["comparisons"][0]
    assert cmp["n"] == 4
    assert cmp["metrics"][0]["lift"]["n"] == 4
    assert cmp["flips"]["paired"] == 4 and cmp["flips"]["n"] == 4


def test_no_difference_reads_as_no_difference():
    a_rows = {f"a{i}": _row(f"a{i}", buy="yes" if i % 2 else "no") for i in range(20)}
    b_rows = {f"a{i}": _row(f"a{i}", buy="yes" if i % 2 else "no") for i in range(20)}
    res = exp_svc.analyse(PI, "within", _variants(), {"A": a_rows, "B": b_rows}, seed=1)
    cmp = res["comparisons"][0]
    assert cmp["metrics"][0]["lift"]["significant"] is False
    assert cmp["flips"]["n"] == 0
    assert res["verdict"].startswith("No reliable difference between A and B")


def test_between_subjects_has_no_flips_and_uses_unpaired_lift():
    a_rows = {f"a{i}": _row(f"a{i}", buy="no") for i in range(10)}
    b_rows = {f"b{i}": _row(f"b{i}", buy="yes") for i in range(10)}
    res = exp_svc.analyse(PI, "between", _variants(), {"A": a_rows, "B": b_rows}, seed=1)
    cmp = res["comparisons"][0]
    assert cmp["flips"] is None
    wb = cmp["metrics"][0]
    assert wb["lift"]["mean"] == pytest.approx(1.0) and wb["lift"]["n_a"] == 10 and wb["lift"]["n_b"] == 10
    assert "B beats A" in res["verdict"]


def test_abn_verdict_names_the_strongest_variant():
    variants = _variants() + [{"key": "C", "label": "C", "spec": {"stimulus": "£5", "price": 5, "currency": "GBP"}}]
    a_rows = {f"a{i}": _row(f"a{i}", buy="no") for i in range(12)}
    b_rows = {f"a{i}": _row(f"a{i}", buy="yes" if i < 4 else "no") for i in range(12)}
    c_rows = {f"a{i}": _row(f"a{i}", buy="yes" if i < 10 else "no") for i in range(12)}
    res = exp_svc.analyse(PI, "within", variants, {"A": a_rows, "B": b_rows, "C": c_rows}, seed=1)
    assert len(res["comparisons"]) == 2
    assert res["verdict"].startswith("C beats A") and "also tested: B" in res["verdict"]


def test_analysis_survives_an_empty_arm():
    a_rows = {f"a{i}": _row(f"a{i}", buy="no") for i in range(3)}
    res = exp_svc.analyse(PI, "within", _variants(), {"A": a_rows, "B": {}}, seed=1)
    cmp = res["comparisons"][0]
    assert cmp["n"] == 0 and cmp["metrics"][0]["lift"]["n"] == 0
    assert cmp["flips"]["n"] == 0 and cmp["segments"] == {}


# ── end-to-end run against a stubbed model ────────────────────────────────────

def test_run_experiment_end_to_end_within_subjects(lab_db, monkeypatch):
    """Both arms run on the SAME agents, an agent never sees its own answer to the other arm,
    and the comparison lands on the experiment row."""
    Session, loop = lab_db
    monkeypatch.setattr("app.services.measurement.experiment.AsyncSessionLocal", Session)
    session_id = str(uuid.uuid4())
    calls = []

    async def fake_analyze(schema, system, user, **kw):
        calls.append(user)
        cheap = "£8" in user
        return {"reasoning": "cheap enough" if cheap else "too dear", "would_buy": "yes" if cheap else "no",
                "likelihood_0_100": 70 if cheap else 20, "max_price": 9.0, "key_driver": "price",
                "sentiment": 0.3 if cheap else -0.2}

    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_analyze)
    monkeypatch.setattr("app.services.measurement.probe._probe_kg_context", lambda *a, **k: _async("ENTITIES: none"))

    async def run():
        async with Session() as db:
            db.add(AnalysisSession(id=session_id, title="T", query="Sleep tracker?", status=SessionStatus.COMPLETE))
            for i in range(6):
                db.add(_agent(session_id=session_id, name=f"A{i}"))
            e = Experiment(session_id=session_id, design="within", instrument="purchase_intent",
                           variants=_variants(), spec={}, seed=7, model="test-model", status="queued")
            db.add(e)
            await db.flush()
            for v in e.variants:
                db.add(Probe(session_id=session_id, instrument="purchase_intent", schema_id="purchase_intent.v2",
                             spec={**v["spec"], "seed": 7}, experiment_id=e.id, variant_key=v["key"],
                             seed=7, model="test-model", status="queued"))
            await db.commit()
            eid = e.id
        await exp_svc.run_experiment(eid)
        async with Session() as db:
            from sqlalchemy import select as sel
            done = await db.get(Experiment, eid)
            probes = (await db.execute(sel(Probe).where(Probe.experiment_id == eid))).scalars().all()
            answers = (await db.execute(sel(ProbeAnswer).where(ProbeAnswer.session_id == session_id))).scalars().all()
        return done, probes, answers

    exp, probes, answers = loop.run_until_complete(run())

    assert exp.status == "complete", exp.error
    assert exp.agent_count == 6
    assert {p.status for p in probes} == {"complete"} and all(p.answer_count == 6 for p in probes)
    assert len(answers) == 12 and len(calls) == 12
    # An agent answering arm B was never shown its arm-A decision (or vice versa).
    assert not any("WHAT YOU ALREADY DECIDED" in u for u in calls)

    r = exp.results
    assert r["design"] == "within" and r["probes"]["A"] != r["probes"]["B"]
    cmp = r["comparisons"][0]
    assert cmp["n"] == 6
    assert cmp["metrics"][0]["lift"]["mean"] == pytest.approx(1.0)
    assert cmp["flips"]["n"] == 6 and cmp["flips"]["rows"][0]["to"] == "yes"
    assert r["verdict"].startswith("B beats A on would buy by 100 points")


def test_run_experiment_between_subjects_splits_the_population(lab_db, monkeypatch):
    Session, loop = lab_db
    monkeypatch.setattr("app.services.measurement.experiment.AsyncSessionLocal", Session)
    session_id = str(uuid.uuid4())

    async def fake_analyze(schema, system, user, **kw):
        return {"reasoning": "ok", "would_buy": "yes" if "£8" in user else "no", "likelihood_0_100": 50,
                "max_price": 9.0, "key_driver": "price", "sentiment": 0.0}

    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_analyze)
    monkeypatch.setattr("app.services.measurement.probe._probe_kg_context", lambda *a, **k: _async("ENTITIES: none"))

    async def run():
        async with Session() as db:
            db.add(AnalysisSession(id=session_id, title="T", query="q", status=SessionStatus.COMPLETE))
            for i in range(9):
                db.add(_agent(session_id=session_id, name=f"A{i}"))
            e = Experiment(session_id=session_id, design="between", instrument="purchase_intent",
                           variants=_variants(), spec={}, seed=11, model="m", status="queued")
            db.add(e)
            await db.flush()
            for v in e.variants:
                db.add(Probe(session_id=session_id, instrument="purchase_intent", schema_id="purchase_intent.v2",
                             spec={**v["spec"], "seed": 11}, experiment_id=e.id, variant_key=v["key"],
                             seed=11, model="m", status="queued"))
            await db.commit()
            eid = e.id
        await exp_svc.run_experiment(eid)
        async with Session() as db:
            from sqlalchemy import select as sel
            done = await db.get(Experiment, eid)
            probes = (await db.execute(sel(Probe).where(Probe.experiment_id == eid))).scalars().all()
            answers = (await db.execute(sel(ProbeAnswer).where(ProbeAnswer.session_id == session_id))).scalars().all()
        return done, probes, answers

    exp, probes, answers = loop.run_until_complete(run())
    assert exp.status == "complete", exp.error
    assert len(answers) == 9                                # each agent asked exactly once
    counts = sorted(p.answer_count for p in probes)
    assert counts == [4, 5]
    ids = [set(p.spec["agent_filter"]["agent_ids"]) for p in probes]
    assert ids[0].isdisjoint(ids[1])
    assert exp.results["comparisons"][0]["flips"] is None
    assert exp.results["comparisons"][0]["metrics"][0]["lift"]["mean"] == pytest.approx(1.0)


# ── HTTP surface ──────────────────────────────────────────────────────────────

def _seed_population(client, Session, n=4):
    session_id = client.post("/api/v1/sessions", json={"title": "T", "query": "Sleep tracker?",
                                                       "auto_research": False}).json()["id"]

    async def seed():
        async with Session() as db:
            for i in range(n):
                db.add(_agent(session_id=session_id, name=f"P{i}"))
            await db.commit()
    asyncio.run(seed())
    return session_id


def test_http_experiment_round_trip(api_client, monkeypatch):
    client, Session = api_client
    monkeypatch.setattr("app.services.measurement.experiment.AsyncSessionLocal", Session)

    async def fake_analyze(schema, system, user, **kw):
        cheap = "£8" in user
        return {"reasoning": "cheap" if cheap else "dear", "would_buy": "yes" if cheap else "no",
                "likelihood_0_100": 60 if cheap else 20, "max_price": 9.0, "key_driver": "price", "sentiment": 0.0}
    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_analyze)

    session_id = _seed_population(client, Session, n=4)
    body = {
        "instrument": "purchase_intent", "design": "within", "name": "Price test",
        "variants": [
            {"key": "A", "label": "£12", "spec": {"stimulus": "Tracker at £12/month", "price": 12, "currency": "GBP"}},
            {"key": "B", "label": "£8", "spec": {"stimulus": "Tracker at £8/month", "price": 8, "currency": "GBP"}},
        ],
    }
    est = client.post(f"/api/v1/sessions/{session_id}/experiments/estimate", json=body).json()
    assert est["agent_count"] == 4 and est["calls"] == 8 and est["estimated_cost_usd"] > 0
    between = client.post(f"/api/v1/sessions/{session_id}/experiments/estimate", json={**body, "design": "between"}).json()
    assert between["calls"] == 4

    created = client.post(f"/api/v1/sessions/{session_id}/experiments", json=body)
    assert created.status_code == 200, created.text
    payload = created.json()
    eid = payload["id"]
    assert [p["variant_key"] for p in payload["probes"]] == ["A", "B"]
    assert all(p["experiment_id"] == eid for p in payload["probes"])

    got = client.get(f"/api/v1/sessions/{session_id}/experiments/{eid}").json()
    assert got["status"] == "complete", got.get("error")
    assert got["name"] == "Price test"
    assert got["results"]["verdict"].startswith("£8 beats £12 on would buy")   # variant labels, not keys
    assert len(got["probes"]) == 2 and all(p["status"] == "complete" for p in got["probes"])

    listed = client.get(f"/api/v1/sessions/{session_id}/experiments").json()["experiments"]
    assert listed[0]["id"] == eid

    # The arms are ordinary probes too, tagged with the experiment.
    probes = client.get(f"/api/v1/sessions/{session_id}/probes").json()["probes"]
    assert sum(1 for p in probes if p["experiment_id"] == eid) == 2

    csv_res = client.get(f"/api/v1/sessions/{session_id}/experiments/{eid}/export.csv")
    assert csv_res.status_code == 200
    lines = csv_res.text.strip().splitlines()
    assert lines[0].startswith("agent_id,name,role,stance") and "A_would_buy" in lines[0] and "B_would_buy" in lines[0]
    assert lines[0].endswith("flipped") and len(lines) == 5
    assert all(line.endswith(",yes") for line in lines[1:])


def test_http_experiment_validation(api_client):
    client, Session = api_client
    session_id = _seed_population(client, Session, n=2)
    ok = {"key": "A", "spec": {"stimulus": "x"}}

    r = client.post(f"/api/v1/sessions/{session_id}/experiments", json={"instrument": "nope", "variants": [ok, {**ok, "key": "B"}]})
    assert r.status_code == 404
    r = client.post(f"/api/v1/sessions/{session_id}/experiments", json={"instrument": "purchase_intent", "variants": [ok]})
    assert r.status_code == 400 and "2 to 6" in r.text
    r = client.post(f"/api/v1/sessions/{session_id}/experiments", json={"instrument": "purchase_intent", "variants": [ok, ok]})
    assert r.status_code == 400 and "unique" in r.text
    r = client.post(f"/api/v1/sessions/{session_id}/experiments",
                    json={"instrument": "purchase_intent", "variants": [ok, {"key": "B", "label": "Cheap", "spec": {}}]})
    assert r.status_code == 400 and "Variant Cheap: missing The offer" in r.text
    r = client.post(f"/api/v1/sessions/{session_id}/experiments",
                    json={"instrument": "purchase_intent", "design": "sideways", "variants": [ok, {**ok, "key": "B"}]})
    assert r.status_code == 400 and "design" in r.text
