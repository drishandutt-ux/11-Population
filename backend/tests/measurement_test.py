"""Tests for the Behaviour Lab probe primitive.

Run:  cd backend && pytest tests/measurement_test.py -q
In-memory SQLite plus a stubbed Anthropic client — no API key, no network.

Covers the three things that make a probe result trustworthy: the statistics carry honest
intervals, the persona context actually reaches the model (public posts, prior decisions and
commercial priors, framed as priors), and a failed agent is dropped from the denominator
rather than filled with a default.
"""
import asyncio
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.models.session import AnalysisSession, SessionStatus  # noqa: E402,F401
from app.models.agent import SpawnedAgent, AgentStance  # noqa: E402,F401
from app.models.post import SimulationPost, PostType  # noqa: E402,F401
from app.models.measurement import Probe, ProbeAnswer  # noqa: E402,F401
from app.services.measurement import instruments, stats  # noqa: E402
from app.services.measurement import probe as probe_svc  # noqa: E402
from app.services.agents.agent_runner import _build_system_prompt  # noqa: E402


# ── stats ─────────────────────────────────────────────────────────────────────

def test_wilson_small_n_stays_inside_bounds():
    w = stats.wilson(1, 3)
    assert 0.0 <= w["low"] < w["share"] < w["high"] <= 1.0
    assert w["n"] == 3 and w["successes"] == 1


def test_wilson_handles_zero_and_total():
    assert stats.wilson(0, 0) == {"share": 0.0, "low": 0.0, "high": 0.0, "n": 0, "successes": 0}
    assert stats.wilson(10, 10)["high"] == 1.0
    assert stats.wilson(0, 10)["low"] == 0.0


def test_wilson_interval_narrows_with_n():
    small = stats.wilson(5, 10)
    large = stats.wilson(500, 1000)
    assert (large["high"] - large["low"]) < (small["high"] - small["low"])


def test_mean_ci_is_reproducible_for_a_seed():
    vals = [1, 4, 9, 12, 40, 3, 7, 8]
    assert stats.mean_ci(vals, seed=7) == stats.mean_ci(vals, seed=7)
    assert stats.mean_ci(vals, seed=7)["mean"] == pytest.approx(10.5)


def test_mean_ci_single_value_has_no_spread():
    out = stats.mean_ci([5.0])
    assert out["mean"] == out["low"] == out["high"] == 5.0


def test_demand_curve_is_monotonically_non_increasing():
    curve = stats.demand_curve([5, 10, 10, 20, 35])
    assert curve, "expected a curve"
    shares = [p["share"] for p in curve]
    assert shares == sorted(shares, reverse=True)
    assert shares[0] == 1.0  # everyone buys when it is free


def test_optimal_price_maximises_revenue():
    curve = stats.demand_curve([10, 10, 10, 30])
    best = stats.optimal_price(curve)
    assert best["revenue_index"] == max(p["revenue_index"] for p in curve)


def test_paired_lift_detects_a_real_difference():
    out = stats.paired_lift([(10, 20)] * 25, seed=1)
    assert out["mean"] == pytest.approx(10.0) and out["significant"] is True
    flat = stats.paired_lift([(10, 10)] * 25, seed=1)
    assert flat["significant"] is False


def test_segment_flags_thin_buckets_instead_of_hiding_them():
    rows = [{"segments": {"stance": "direct"}, "v": 1}] * 5 + [{"segments": {"stance": "neutral"}, "v": 0}]
    out = stats.segment(rows, "stance", lambda rs: {"mean": sum(r["v"] for r in rs) / len(rs)})
    thin = [b for b in out if b["thin"]]
    assert len(out) == 2 and len(thin) == 1 and thin[0]["value"] == "neutral"


def test_rake_weights_pull_marginals_towards_the_target():
    rows = [{"segments": {"age_band": "18-24"}}] * 9 + [{"segments": {"age_band": "65+"}}]
    w = stats.rake_weights(rows, {"age_band": {"18-24": 0.5, "65+": 0.5}})
    young = sum(w[:9])
    old = w[9]
    assert old > young / 9 * 5  # the lone 65+ agent now carries real weight
    assert sum(w) == pytest.approx(len(rows), rel=1e-3)


# ── instrument registry ───────────────────────────────────────────────────────

def test_purchase_intent_is_registered_and_reasoning_comes_first():
    inst = instruments.get("purchase_intent")
    assert inst is not None
    keys = list(inst.answer_schema["properties"].keys())
    assert keys[0] == "reasoning", "reason-before-number keeps answers off the midpoint"
    assert inst.schema_id() == "purchase_intent.v2"


def test_unknown_instrument_is_none():
    assert instruments.get("nope") is None


def test_purchase_intent_aggregate_shape():
    def row(i, buy, price, like, driver):
        return {
            "agent_id": f"a{i}",
            "agent": {"name": f"N{i}", "role": "r"},
            "answer": {"reasoning": "because", "would_buy": buy, "likelihood_0_100": like,
                       "max_price": price, "key_driver": driver, "sentiment": 0.2},
            "segments": {"stance": "direct", "age_band": "25-34"},
        }
    rows = [row(0, "yes", 20, 80, "need"), row(1, "no", 5, 10, "price"),
            row(2, "unsure", 15, 55, "need"), row(3, "yes", 11, 45, "trust")]
    agg = instruments.get("purchase_intent").aggregate(rows, {"price": 12, "currency": "GBP", "seed": 1})

    assert agg["n"] == 4
    assert agg["headline"]["share"] == 0.5
    assert agg["headline"]["low"] < 0.5 < agg["headline"]["high"]
    assert agg["drivers"][0]["value"] == "need"
    assert agg["at_asking_price"]["successes"] == 2       # only £20 and £15 clear an ask of £12
    # Both directions of posturing: the "unsure" who would in fact pay, and the "yes" whose own
    # walk-away price is below the asking price.
    assert agg["consistency"]["contradictions"] == 2
    assert agg["demand_curve"] and agg["optimal_price"]["price"] > 0
    assert "±" in agg["sentence"] and "£" in agg["sentence"]
    assert [v["name"] for v in agg["verbatims"]["yes"]] == ["N0", "N3"]


def test_aggregate_with_no_rows_is_safe():
    assert instruments.get("purchase_intent").aggregate([], {})["n"] == 0


# ── persona wiring ────────────────────────────────────────────────────────────

def _agent(**kw):
    base = dict(
        id=str(uuid.uuid4()), session_id="s", name="Dana Okoro", age=58, role="district nurse",
        background="Works nights at a busy A&E.", stance=AgentStance.NEUTRAL,
        correlation="Would be a customer", personality=["blunt"], debate_style="direct",
        energy=0.5, avatar_color="#111111", humanity=0,
        dials={"commercial": {"purchase_intent": 8, "willingness_to_pay": 3, "price_pain": 9}},
    )
    base.update(kw)
    return SpawnedAgent(**base)


def test_probe_prompt_keeps_the_persona_and_drops_the_reddit_instruction():
    a = _agent()
    post = _build_system_prompt(a)
    probe = _build_system_prompt(a, task="probe")
    assert "Dana Okoro" in probe and "district nurse" in probe
    assert "Reddit" in post and "Reddit" not in probe
    assert "HOW YOU ANSWER THIS" in probe


def test_humanity_band_changes_how_the_agent_answers():
    gut = _build_system_prompt(_agent(humanity=85), task="probe")
    considered = _build_system_prompt(_agent(humanity=0), task="probe")
    assert "From the gut, instantly" in gut
    assert "Deliberately" in considered


def test_segments_bucket_age_and_dial_priors():
    segs = probe_svc.segments_for(_agent(age=58, humanity=75))
    assert segs["age_band"] == "55-64"
    assert segs["humanity_band"] == "reactive"
    assert segs["purchase_intent_prior"] == "high"   # 8/10
    assert segs["price_pain_prior"] == "high"        # 9/10


def test_user_message_carries_history_and_frames_dials_as_priors():
    inst = instruments.get("purchase_intent")
    msg = probe_svc._build_user_message(
        agent=_agent(),
        instrument=inst,
        spec={"stimulus": "A £12/month sleep tracker.", "price": 12, "currency": "GBP"},
        query="Should we launch a sleep tracker?",
        kg_context="ENTITIES: sleep, wearables",
        said=["I would never wear one of these to bed."],
        decided=["- brand funnel: awareness yes — \"heard of them\""],
    )
    assert "Should we launch a sleep tracker?" in msg
    assert "I would never wear one of these to bed." in msg
    assert "brand funnel" in msg
    assert "priors, NOT the answer" in msg
    assert "purchase intent 8/10" in msg
    assert "asking price: £12" in msg
    assert msg.rstrip().endswith("Record your answer with the tool.")


def test_context_policy_can_switch_history_off():
    msg = probe_svc._build_user_message(
        agent=_agent(), instrument=instruments.get("purchase_intent"),
        spec={"stimulus": "x", "context": {"kg": False, "own_posts": False, "prior_answers": False}},
        query="q", kg_context="ENTITIES: a", said=["public thing"], decided=["- x: y"],
    )
    assert "public thing" not in msg and "ENTITIES" not in msg


def test_agent_filter_is_seeded_and_reproducible():
    agents = [_agent(age=20 + i) for i in range(20)]
    spec = {"agent_filter": {"sample": 5}}
    first = [a.id for a in probe_svc._select_agents(agents, spec, 42)]
    again = [a.id for a in probe_svc._select_agents(agents, spec, 42)]
    other = [a.id for a in probe_svc._select_agents(agents, spec, 43)]
    assert first == again and len(first) == 5
    assert first != other


def test_agent_filter_by_segment():
    agents = [_agent(age=20), _agent(age=70), _agent(age=71)]
    chosen = probe_svc._select_agents(agents, {"agent_filter": {"segments": {"age_band": "65+"}}}, 0)
    assert len(chosen) == 2


# ── end-to-end run against a stubbed model ────────────────────────────────────

@pytest.fixture
def lab_db(monkeypatch):
    """In-memory SQLite on a loop of its own.

    The aiosqlite engine binds to the loop that created it, so the schema setup and the probe
    run have to share one loop — `asyncio.get_event_loop()` does not guarantee that once other
    test modules have run."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.core.database import Base

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.core.database.AsyncSessionLocal", Session)
    monkeypatch.setattr("app.services.measurement.probe.AsyncSessionLocal", Session)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    loop.run_until_complete(setup())
    try:
        yield Session, loop
    finally:
        loop.run_until_complete(engine.dispose())
        loop.close()
        asyncio.set_event_loop(None)


def test_run_probe_end_to_end(lab_db, monkeypatch):
    Session, loop = lab_db
    session_id = str(uuid.uuid4())

    calls = []

    async def fake_analyze(schema, system, user, **kw):
        calls.append({"system": system, "user": user})
        n = len(calls)
        if n == 3:                       # one agent's call fails
            raise RuntimeError("overloaded")
        return {
            "reasoning": f"answer {n}", "would_buy": "yes" if n % 2 else "no",
            "likelihood_0_100": 50 + n, "max_price_gbp": 10 + n,
            "key_driver": "price", "sentiment": 0.1,
        }

    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_analyze)
    monkeypatch.setattr("app.services.measurement.probe._probe_kg_context",
                        lambda *a, **k: _async("ENTITIES: sleep"))

    async def run():
        async with Session() as db:
            db.add(AnalysisSession(id=session_id, title="Sleep tracker",
                                   query="Should we launch a sleep tracker?",
                                   status=SessionStatus.COMPLETE))
            agents = [_agent(session_id=session_id, name=f"A{i}") for i in range(5)]
            for a in agents:
                db.add(a)
            db.add(SimulationPost(session_id=session_id, agent_id=agents[0].id,
                                  type=PostType.COMMENT, content="Not for me at that price."))
            p = Probe(session_id=session_id, instrument="purchase_intent",
                      schema_id="purchase_intent.v1", model="test-model", seed=3,
                      spec={"stimulus": "A £12/month sleep tracker.", "price": 12, "seed": 3})
            db.add(p)
            await db.commit()
            probe_id = p.id

        await probe_svc.run_probe(probe_id)

        async with Session() as db:
            done = await db.get(Probe, probe_id)
            from sqlalchemy import select as sel
            answers = (await db.execute(sel(ProbeAnswer).where(ProbeAnswer.probe_id == probe_id))).scalars().all()
        return done, answers

    probe_row, answers = loop.run_until_complete(run())

    assert probe_row.status == "complete"
    assert probe_row.agent_count == 5
    assert probe_row.answer_count == 4 and probe_row.failed_count == 1
    assert len(answers) == 4
    # The failed agent is absent from the denominator, never defaulted into it.
    assert probe_row.aggregates["n"] == 4
    assert probe_row.aggregates["headline"]["n"] == 4
    assert probe_row.aggregates["sentence"]
    assert all(a.reasoning for a in answers)

    # The persona and its own public post reached the model.
    assert any("Not for me at that price." in c["user"] for c in calls)
    assert all("HOW YOU ANSWER THIS" in c["system"] for c in calls)
    assert all("A £12/month sleep tracker." in c["user"] for c in calls)


async def _async(v):
    return v


# ── HTTP surface ──────────────────────────────────────────────────────────────

@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """TestClient on a fresh SQLite DB in dev mode (no auth), with the model stubbed."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.core.database as dbm
    from app.core.config import get_settings
    import app.models.report, app.models.preset, app.models.kg  # noqa: F401

    monkeypatch.setattr(get_settings(), "app_supabase_url", "")   # dev mode: every call is the dev user
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/lab.db")
    Session = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(dbm, "engine", eng)
    monkeypatch.setattr(dbm, "AsyncSessionLocal", Session)
    monkeypatch.setattr(dbm, "_sqlite", True)
    monkeypatch.setattr("app.services.measurement.probe.AsyncSessionLocal", Session)

    async def fake_analyze(schema, system, user, **kw):
        return {"reasoning": "it is too dear for me", "would_buy": "no", "likelihood_0_100": 15,
                "max_price_gbp": 7.5, "key_driver": "price", "sentiment": -0.3}

    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_analyze)

    async def no_kg(*a, **k):
        return "ENTITIES: none"
    monkeypatch.setattr("app.services.measurement.probe._probe_kg_context", no_kg)

    async def _get_db():
        async with Session() as s:
            yield s

    from fastapi.testclient import TestClient
    from app.main import app
    app.dependency_overrides[dbm.get_db] = _get_db
    with TestClient(app) as c:
        yield c, Session
    app.dependency_overrides.clear()


def test_http_probe_round_trip(api_client):
    client, Session = api_client

    assert any(i["key"] == "purchase_intent" for i in client.get("/api/v1/lab/instruments").json()["instruments"])

    session_id = client.post("/api/v1/sessions", json={"title": "T", "query": "Sleep tracker?",
                                                       "auto_research": False}).json()["id"]

    # A probe without a population is a user error, not a 500.
    assert client.post(f"/api/v1/sessions/{session_id}/probes",
                       json={"instrument": "purchase_intent", "spec": {"stimulus": "x"}}).status_code == 400

    async def seed():
        async with Session() as db:
            for i in range(3):
                db.add(_agent(session_id=session_id, name=f"P{i}"))
            await db.commit()
    asyncio.run(seed())

    body = {"instrument": "purchase_intent", "spec": {"stimulus": "A £12/month sleep tracker.", "price": 12}}
    est = client.post(f"/api/v1/sessions/{session_id}/probes/estimate", json=body).json()
    assert est["agent_count"] == 3 and est["estimated_cost_usd"] > 0

    # BackgroundTasks run inside the TestClient request, so the probe is finished on return.
    created = client.post(f"/api/v1/sessions/{session_id}/probes", json=body)
    assert created.status_code == 200, created.text
    probe_id = created.json()["id"]

    got = client.get(f"/api/v1/sessions/{session_id}/probes/{probe_id}").json()
    assert got["status"] == "complete" and got["answer_count"] == 3
    assert got["aggregates"]["headline"]["share"] == 0.0          # every stub answer is a "no"
    assert got["aggregates"]["at_asking_price"]["successes"] == 0  # £7.50 never clears £12
    assert len(got["answers"]) == 3 and got["answers"][0]["segments"]["stance"] == "neutral"

    assert client.get(f"/api/v1/sessions/{session_id}/probes").json()["probes"][0]["id"] == probe_id

    csv_res = client.get(f"/api/v1/sessions/{session_id}/probes/{probe_id}/export.csv")
    assert csv_res.status_code == 200
    lines = csv_res.text.strip().splitlines()
    assert lines[0].startswith("agent_id,name,role,stance,age_band")
    assert len(lines) == 4 and "too dear" in csv_res.text


def test_http_unknown_instrument_is_404(api_client):
    client, _ = api_client
    session_id = client.post("/api/v1/sessions", json={"title": "T", "query": "q", "auto_research": False}).json()["id"]
    r = client.post(f"/api/v1/sessions/{session_id}/probes", json={"instrument": "nope", "spec": {}})
    assert r.status_code == 404


# ── cost estimate ─────────────────────────────────────────────────────────────

def test_cost_is_priced_from_the_model_not_the_mode_label():
    """Regression: the estimate used to be a per-mode constant, so a "Fast" probe was quoted
    at Haiku rates even where MODEL_AGENTS is overridden to Sonnet — a ~12x understatement."""
    from app.api.v1.measurement import estimate_cost_usd

    haiku = estimate_cost_usd("claude-haiku-4-5-20251001", 10)
    sonnet46 = estimate_cost_usd("claude-sonnet-4-6", 10)
    opus = estimate_cost_usd("claude-opus-5", 10)
    assert haiku < sonnet46 < opus
    # 10 × (2400 tok × $3/M + 260 tok × $15/M)
    assert sonnet46 == pytest.approx(0.111, abs=0.001)


def test_cost_scales_with_agent_count():
    from app.api.v1.measurement import estimate_cost_usd
    assert estimate_cost_usd("claude-haiku-4-5", 100) == pytest.approx(
        estimate_cost_usd("claude-haiku-4-5", 10) * 10, rel=1e-6)
    assert estimate_cost_usd("claude-haiku-4-5", 0) == 0


def test_unknown_model_is_priced_at_the_top_tier_not_the_cheapest():
    from app.api.v1.measurement import estimate_cost_usd
    unknown = estimate_cost_usd("some-future-model", 10)
    assert unknown >= estimate_cost_usd("claude-opus-5", 10)


# ── currency-neutral walk-away price ──────────────────────────────────────────

def test_walk_away_price_field_is_currency_neutral():
    """v1 called it max_price_gbp while the instrument already priced in USD/EUR."""
    inst = instruments.get("purchase_intent")
    props = inst.answer_schema["properties"]
    assert "max_price" in props and "max_price_gbp" not in props
    assert inst.schema_id() == "purchase_intent.v2"


def test_v1_answers_still_aggregate():
    """Answers recorded under the old field name must not silently become £0."""
    rows = [{
        "agent_id": "a1", "agent": {"name": "N", "role": "r"},
        "answer": {"reasoning": "r", "would_buy": "yes", "likelihood_0_100": 70,
                   "max_price_gbp": 31.99, "key_driver": "convenience", "sentiment": 0.2},
        "segments": {},
    }]
    agg = instruments.get("purchase_intent").aggregate(rows, {"price": 34.99, "seed": 1})
    assert agg["max_price"]["median"] == 31.99
    assert agg["consistency"]["contradictions"] == 1   # said yes, own price is below the ask


# ── no canned phrasing ────────────────────────────────────────────────────────

def test_dial_directives_never_hand_the_model_a_stock_sentence():
    """Regression: the balanced directive contained the literal example
    "part of me feels…, but rationally…", and every balanced-band agent opened with it —
    in the debate and in probe answers alike."""
    from app.services.agents import agent_runner

    for band, text in agent_runner._HUMANITY_DIRECTIVES.items():
        assert "part of me" not in text.lower(), f"{band} band hands the model a stock phrase"
    for band, text in agent_runner._PROBE_DIRECTIVES.items():
        assert "part of me" not in text.lower(), f"{band} probe directive hands over a stock phrase"
