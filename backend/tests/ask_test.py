"""Tests for the generic Ask instrument, theme coding and the choose-between-them design.

Run:  cd backend && pytest tests/ask_test.py -q
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
from app.models.measurement import Experiment, Probe, ProbeAnswer  # noqa: E402
from app.services.measurement import experiment as exp_svc  # noqa: E402
from app.services.measurement import instruments, themes  # noqa: E402
from app.services.measurement import probe as probe_svc  # noqa: E402

from tests.measurement_test import _agent, lab_db, api_client, _async  # noqa: E402,F401

ASK = instruments.get("ask")
CHOICE = instruments.get("choice")


# ── declarations ──────────────────────────────────────────────────────────────

def test_ask_is_generic_the_question_comes_from_the_spec():
    assert ASK.stimulus_key == "material" and ASK.question_from == "question"
    assert ASK.question_for({"question": "Would you open this email?"}) == "Would you open this email?"
    assert ASK.question_for({}) == ASK.question                    # falls back to the default phrasing
    assert [f.key for f in ASK.inputs] == ["material", "question"]
    assert ASK.inputs[1].suggestions and ASK.inputs[1].default == ASK.inputs[1].suggestions[0]
    assert list(ASK.answer_schema["properties"])[0] == "reasoning"   # reason before verdict
    assert ASK.primary_metric().key == "verdict" and ASK.decision_key == "verdict" and ASK.driver_key == "theme"


def test_choice_is_hidden_and_builds_its_enum_from_the_options():
    assert CHOICE.hidden
    schema = CHOICE.schema_for({"option_keys": ["A", "B", "C"]})
    assert schema["properties"]["choice"]["enum"] == ["A", "B", "C"]
    assert schema["properties"]["runner_up"]["enum"] == ["A", "B", "C"]
    assert list(schema["properties"])[0] == "reasoning"


def test_prompt_uses_the_instruments_own_stimulus_key_and_question(monkeypatch):
    agent = _agent(session_id="s", name="Ann")
    spec = {"material": "SUBJECT: Your bill is changing", "question": "Would you open this email?"}
    msg = probe_svc._build_user_message(agent=agent, instrument=ASK, spec=spec, query="q", kg_context="",
                                        said=[], decided=[])
    assert "SUBJECT: Your bill is changing" in msg
    assert "THE QUESTION: Would you open this email?" in msg
    # A different question changes the fingerprint, so results are never compared across asks.
    assert probe_svc.prompt_hash(ASK, spec) != probe_svc.prompt_hash(ASK, {**spec, "question": "Would you delete it?"})


# ── aggregation ───────────────────────────────────────────────────────────────

def _row(aid, verdict, *, strength=50, feeling=0.0, factor="", theme="", stance="neutral"):
    return {
        "agent_id": aid, "agent": {"name": aid, "role": "r", "avatar_color": "#000"},
        "answer": {"reasoning": "because", "verdict": verdict, "strength": strength, "feeling": feeling,
                   "key_factor": factor, **({"theme": theme} if theme else {})},
        "segments": {"stance": stance, "age_band": "25-34", "humanity_band": "balanced", "purchase_intent_prior": "mid"},
    }


def test_ask_aggregate_reports_yes_open_to_and_themes():
    rows = [_row("a1", "yes", factor="short and clear", theme="clarity"),
            _row("a2", "mixed", factor="too salesy", theme="tone"),
            _row("a3", "no", factor="sounds like spam", theme="tone"),
            _row("a4", "yes", factor="clear ask", theme="clarity")]
    agg = ASK.aggregate(rows, {"seed": 1})
    assert agg["headline"]["share"] == 0.5 and agg["open_to"]["share"] == 0.75
    assert agg["themes"][0]["value"] in ("clarity", "tone") and agg["themes_coded"] is True
    assert set(agg["verbatims"]) == {"yes", "mixed", "no"}
    assert "50% say yes" in agg["sentence"] and "75% are at least open" in agg["sentence"]
    values = {m.key: m.value(rows[1]["answer"]) for m in ASK.metrics}
    assert values["verdict"] == 0.0 and values["open_to"] == 1.0


def test_ask_aggregate_before_coding_uses_raw_factors():
    rows = [_row("a1", "yes", factor="Short and clear"), _row("a2", "no", factor="too long")]
    agg = ASK.aggregate(rows, {})
    assert agg["themes"] == [] and agg["themes_coded"] is False and agg["factors"]


def test_choice_aggregate_preference_and_head_to_head():
    def crow(aid, choice, second, factor=""):
        return {"agent_id": aid, "agent": {"name": aid, "role": "r", "avatar_color": ""},
                "answer": {"reasoning": "r", "choice": choice, "runner_up": second, "confidence": 70,
                           "key_factor": factor, "theme": factor},
                "segments": {"stance": "neutral", "age_band": "25-34", "humanity_band": "balanced", "purchase_intent_prior": "mid"}}
    # 14 / 4 / 2 of 20: B's interval clears A's, so the winner is settled. (7 / 2 / 1 of 10 would not be.)
    rows = [crow(f"a{i}", "B", "A", "warmer tone") for i in range(14)] + [crow(f"b{i}", "A", "C") for i in range(4)] + [crow(f"c{i}", "C", "B") for i in range(2)]
    spec = {"option_keys": ["A", "B", "C"], "option_labels": {"A": "Formal", "B": "Warm", "C": "Short"}}
    agg = CHOICE.aggregate(rows, spec)
    pref = {p["key"]: p for p in agg["preference"]}
    assert agg["winner"] == "B" and pref["B"]["share"] == 0.7 and pref["B"]["label"] == "Warm"
    assert pref["A"]["runner_up"] == 14
    assert agg["head_to_head"][0] == {"first": "B", "second": "A", "count": 14}
    assert agg["clear_winner"] is True
    assert agg["sentence"].startswith("Warm is preferred by 70%") and "warmer tone" in agg["sentence"]


# ── theme coding ──────────────────────────────────────────────────────────────

def test_code_factors_maps_every_factor_and_keeps_raw_words_for_misses(monkeypatch):
    async def fake_analyze(schema, system, user, **kw):
        # Unique, normalised factors are sent: 0 = "the 4-7pm price" (twice in the input),
        # 1 = "don't trust octopus", 2 = "something the model skipped" (left uncoded here).
        assert "0. the 4-7pm price" in user and "2. something the model skipped" in user
        return {"themes": [{"label": "peak-time cost", "items": [0]}, {"label": "trust in octopus", "items": [1]}]}
    monkeypatch.setattr("app.services.measurement.themes.analyze", fake_analyze)
    out = asyncio.run(themes.code_factors(
        ["The 4-7pm price", "don't trust octopus", "the 4-7PM price", "", "something the model skipped"],
        session_id="s", model="m"))
    assert out == ["peak-time cost", "trust in octopus", "peak-time cost", "", "something the model skipped"]


def test_apply_themes_writes_theme_onto_answers_and_reaggregates(lab_db, monkeypatch):
    Session, loop = lab_db
    monkeypatch.setattr("app.services.measurement.themes.AsyncSessionLocal", Session)
    session_id = str(uuid.uuid4())

    async def fake_analyze(schema, system, user, **kw):
        return {"themes": [{"label": "clarity", "items": [0, 1]}]}
    monkeypatch.setattr("app.services.measurement.themes.analyze", fake_analyze)

    async def run():
        async with Session() as db:
            db.add(AnalysisSession(id=session_id, title="T", query="q", status=SessionStatus.COMPLETE))
            agents = [_agent(session_id=session_id, name=f"A{i}") for i in range(2)]
            for a in agents:
                db.add(a)
            p = Probe(session_id=session_id, instrument="ask", schema_id="ask.v1", model="m", seed=1,
                      spec={"material": "x", "question": "q", "seed": 1}, status="complete")
            db.add(p)
            await db.flush()
            for a, f in zip(agents, ["clear ask", "very clear"]):
                db.add(ProbeAnswer(probe_id=p.id, session_id=session_id, agent_id=a.id,
                                   answer={"reasoning": "r", "verdict": "yes", "strength": 60, "feeling": 0.2, "key_factor": f}))
            await db.commit()
            pid = p.id
        await themes.apply_themes([pid], model="m")
        async with Session() as db:
            from sqlalchemy import select as sel
            probe = await db.get(Probe, pid)
            answers = (await db.execute(sel(ProbeAnswer).where(ProbeAnswer.probe_id == pid))).scalars().all()
        return probe, answers

    probe, answers = loop.run_until_complete(run())
    assert all(a.answer["theme"] == "clarity" for a in answers)
    assert probe.aggregates["themes"][0]["value"] == "clarity" and probe.aggregates["themes"][0]["count"] == 2


# ── end to end: choice design ─────────────────────────────────────────────────

def test_choice_experiment_runs_one_call_per_agent_and_reports_preference(lab_db, monkeypatch):
    Session, loop = lab_db
    monkeypatch.setattr("app.services.measurement.experiment.AsyncSessionLocal", Session)
    monkeypatch.setattr("app.services.measurement.themes.AsyncSessionLocal", Session)
    session_id = str(uuid.uuid4())
    calls = []

    async def fake_analyze(schema, system, user, **kw):
        if "themes" in schema["properties"]:
            return {"themes": [{"label": "warmer tone", "items": list(range(20))}]}
        calls.append(user)
        assert "OPTION A — Formal" in user and "OPTION B — Warm" in user
        assert schema["properties"]["choice"]["enum"] == ["A", "B"]
        n = len(calls)
        return {"reasoning": "r", "choice": "B" if n % 4 else "A", "runner_up": "A" if n % 4 else "B",
                "confidence": 70, "key_factor": "warmer tone"}

    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_analyze)
    monkeypatch.setattr("app.services.measurement.themes.analyze", fake_analyze)
    monkeypatch.setattr("app.services.measurement.probe._probe_kg_context", lambda *a, **k: _async("ENTITIES: none"))

    variants = [{"key": "A", "label": "Formal", "spec": {"material": "Dear customer…", "question": "Which would you open?"}},
                {"key": "B", "label": "Warm", "spec": {"material": "Hi there…", "question": "Which would you open?"}}]

    async def run():
        async with Session() as db:
            db.add(AnalysisSession(id=session_id, title="T", query="q", status=SessionStatus.COMPLETE))
            for i in range(8):
                db.add(_agent(session_id=session_id, name=f"A{i}"))
            e = Experiment(session_id=session_id, design="choice", instrument="ask", variants=variants,
                           spec={}, seed=3, model="m", status="queued")
            db.add(e)
            await db.flush()
            spec = exp_svc.compose_choice_spec(ASK, variants, {}, "Which would you open?", 3)
            db.add(Probe(session_id=session_id, instrument="choice", schema_id="choice.v1", spec=spec,
                         experiment_id=e.id, variant_key=exp_svc.CHOICE_ARM, seed=3, model="m", status="queued"))
            await db.commit()
            eid = e.id
        await exp_svc.run_experiment(eid)
        async with Session() as db:
            return await db.get(Experiment, eid)

    exp = loop.run_until_complete(run())
    assert exp.status == "complete", exp.error
    assert len(calls) == 8                                   # one call per agent, not per variant
    r = exp.results
    assert r["design"] == "choice" and r["winner"] == "B"
    pref = {p["key"]: p for p in r["preference"]}
    assert pref["B"]["successes"] == 6 and pref["A"]["successes"] == 2
    assert pref["B"]["themes"][0]["value"] == "warmer tone"
    assert r["verdict"].startswith("Warm is preferred by 75%")
    assert [a["n"] for a in r["arms"]] == [2, 6]


def test_within_experiment_codes_themes_once_across_arms(lab_db, monkeypatch):
    Session, loop = lab_db
    monkeypatch.setattr("app.services.measurement.experiment.AsyncSessionLocal", Session)
    monkeypatch.setattr("app.services.measurement.themes.AsyncSessionLocal", Session)
    session_id = str(uuid.uuid4())
    coding_calls = []

    async def fake_analyze(schema, system, user, **kw):
        if "themes" in schema["properties"]:
            coding_calls.append(user)
            return {"themes": [{"label": "clarity", "items": list(range(12))}]}
        return {"reasoning": "r", "verdict": "yes" if "Hi there" in user else "no", "strength": 50,
                "feeling": 0.0, "key_factor": "clear ask"}

    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_analyze)
    monkeypatch.setattr("app.services.measurement.themes.analyze", fake_analyze)
    monkeypatch.setattr("app.services.measurement.probe._probe_kg_context", lambda *a, **k: _async("ENTITIES: none"))
    variants = [{"key": "A", "label": "Formal", "spec": {"material": "Dear customer…", "question": "Open it?"}},
                {"key": "B", "label": "Warm", "spec": {"material": "Hi there…", "question": "Open it?"}}]

    async def run():
        async with Session() as db:
            db.add(AnalysisSession(id=session_id, title="T", query="q", status=SessionStatus.COMPLETE))
            for i in range(6):
                db.add(_agent(session_id=session_id, name=f"A{i}"))
            e = Experiment(session_id=session_id, design="within", instrument="ask", variants=variants,
                           spec={}, seed=3, model="m", status="queued")
            db.add(e)
            await db.flush()
            for v in variants:
                db.add(Probe(session_id=session_id, instrument="ask", schema_id="ask.v1", spec={**v["spec"], "seed": 3},
                             experiment_id=e.id, variant_key=v["key"], seed=3, model="m", status="queued"))
            await db.commit()
            eid = e.id
        await exp_svc.run_experiment(eid)
        async with Session() as db:
            return await db.get(Experiment, eid)

    exp = loop.run_until_complete(run())
    assert exp.status == "complete", exp.error
    assert len(coding_calls) == 1                            # once across both arms, not per arm
    cmp = exp.results["comparisons"][0]
    assert cmp["metrics"][0]["lift"]["mean"] == pytest.approx(1.0)
    assert cmp["flips"]["n"] == 6 and cmp["flips"]["reasons"][0]["value"] == "clarity"


# ── HTTP ──────────────────────────────────────────────────────────────────────

def test_http_ask_probe_and_choice_experiment(api_client, monkeypatch):
    client, Session = api_client
    monkeypatch.setattr("app.services.measurement.experiment.AsyncSessionLocal", Session)
    monkeypatch.setattr("app.services.measurement.themes.AsyncSessionLocal", Session)

    async def fake_analyze(schema, system, user, **kw):
        props = schema["properties"]
        if "themes" in props:
            return {"themes": [{"label": "clarity", "items": list(range(10))}]}
        if "choice" in props:
            return {"reasoning": "r", "choice": "B", "runner_up": "A", "confidence": 60, "key_factor": "clear"}
        return {"reasoning": "r", "verdict": "mixed", "strength": 40, "feeling": 0.1, "key_factor": "clear"}
    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_analyze)
    monkeypatch.setattr("app.services.measurement.themes.analyze", fake_analyze)

    listing = client.get("/api/v1/lab/instruments").json()["instruments"]
    by_key = {i["key"]: i for i in listing}
    assert by_key["ask"]["question_from"] == "question" and by_key["ask"]["inputs"][1]["suggestions"]
    assert by_key["choice"]["hidden"] is True

    session_id = client.post("/api/v1/sessions", json={"title": "T", "query": "q", "auto_research": False}).json()["id"]

    async def seed():
        async with Session() as db:
            for i in range(3):
                db.add(_agent(session_id=session_id, name=f"P{i}"))
            await db.commit()
    asyncio.run(seed())

    # A standalone Ask probe: themes coded and written onto answers.
    r = client.post(f"/api/v1/sessions/{session_id}/probes",
                    json={"instrument": "ask", "spec": {"material": "Hello", "question": "Open it?"}})
    assert r.status_code == 200, r.text
    got = client.get(f"/api/v1/sessions/{session_id}/probes/{r.json()['id']}").json()
    assert got["status"] == "complete" and got["aggregates"]["open_to"]["share"] == 1.0
    assert got["answers"][0]["answer"]["theme"] == "clarity"
    csv_text = client.get(f"/api/v1/sessions/{session_id}/probes/{r.json()['id']}/export.csv").text
    assert csv_text.splitlines()[0].endswith("key_factor,theme")

    # Missing question → 400 from the declaration.
    assert client.post(f"/api/v1/sessions/{session_id}/probes",
                       json={"instrument": "ask", "spec": {"material": "Hello", "question": ""}}).status_code == 400

    # The hidden instrument cannot be run directly as an experiment base.
    body = {"instrument": "choice", "design": "choice", "variants": [{"key": "A", "spec": {}}, {"key": "B", "spec": {}}]}
    assert client.post(f"/api/v1/sessions/{session_id}/experiments", json=body).status_code == 404

    body = {"instrument": "ask", "design": "choice", "question": "Which email would you open?",
            "variants": [{"key": "A", "label": "Formal", "spec": {"material": "Dear customer", "question": "x"}},
                         {"key": "B", "label": "Warm", "spec": {"material": "Hi there", "question": "x"}}]}
    est = client.post(f"/api/v1/sessions/{session_id}/experiments/estimate", json=body).json()
    assert est["calls"] == 3                                  # one call per agent
    created = client.post(f"/api/v1/sessions/{session_id}/experiments", json=body)
    assert created.status_code == 200, created.text
    eid = created.json()["id"]
    assert [p["variant_key"] for p in created.json()["probes"]] == ["all"]
    got = client.get(f"/api/v1/sessions/{session_id}/experiments/{eid}").json()
    assert got["status"] == "complete", got.get("error")
    assert got["results"]["design"] == "choice" and got["results"]["winner"] == "B"
    assert got["results"]["verdict"].startswith("Warm is preferred by 100%")
    csv_res = client.get(f"/api/v1/sessions/{session_id}/experiments/{eid}/export.csv")
    assert csv_res.status_code == 200 and "all_choice" in csv_res.text.splitlines()[0]
