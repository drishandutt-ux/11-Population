"""Tests for the Survey instrument: the form → schema, validation, per-type aggregation,
theme coding of open questions, and the HTTP run.

Run:  cd backend && pytest tests/survey_test.py -q
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.measurement import instruments  # noqa: E402
from app.services.measurement import probe as probe_svc  # noqa: E402
from app.services.measurement.instruments.survey import TEMPLATES, normalise, schema_for, validate  # noqa: E402

from tests.measurement_test import _agent, api_client  # noqa: E402,F401

SV = instruments.get("survey")

FORM = {
    "title": "About this email",
    "questions": [
        {"key": "open", "type": "yesno", "text": "Would you open it?", "primary": True},
        {"key": "read", "type": "single", "text": "How far would you read?", "options": ["all", "some", "none"]},
        {"key": "who", "type": "multi", "text": "Who is it for?", "options": ["me", "my family", "nobody"]},
        {"key": "score", "type": "scale", "text": "Rate it", "min": 1, "max": 5, "min_label": "poor", "max_label": "great"},
        {"key": "spend", "type": "number", "text": "How much would you spend?"},
        {"key": "why", "type": "text", "text": "Why?"},
        {"key": "tone", "type": "grid", "text": "It is…", "rows": ["Clear", "Pushy"], "columns": ["agree", "neutral", "disagree"]},
    ],
}


def test_form_becomes_a_typed_schema_with_reasoning_first():
    schema = schema_for(FORM)
    props = schema["properties"]
    assert list(props)[0] == "reasoning"
    assert props["open"]["enum"] == ["yes", "no"]
    assert props["read"]["enum"] == ["all", "some", "none"]
    assert props["who"]["type"] == "array" and props["who"]["items"]["enum"] == ["me", "my family", "nobody"]
    assert props["score"]["type"] == "integer" and "from 1 to 5" in props["score"]["description"]
    assert props["spend"]["type"] == "number"
    assert props["why"]["type"] == "string"
    assert list(props["tone"]["properties"]) == ["clear", "pushy"]
    assert SV.schema_for(FORM) == schema


def test_questionnaire_is_rendered_for_the_agent_and_fingerprinted():
    q = SV.question_for(FORM)
    assert "SURVEY: About this email" in q and "1. Would you open it? [yes / no]" in q
    assert "choose all that apply" in q and "for each of: Clear; Pushy" in q
    assert probe_svc.prompt_hash(SV, FORM) != probe_svc.prompt_hash(SV, {**FORM, "title": "Other"})


def test_validation_catches_the_obvious_mistakes():
    assert validate({"questions": []}) == ["Add at least one question."]
    errs = validate({"questions": [
        {"key": "a", "type": "single", "text": "", "options": ["x"]},
        {"key": "a", "type": "scale", "text": "s", "min": 5, "max": 1},
        {"key": "g", "type": "grid", "text": "g", "rows": [], "columns": ["1"]},
    ]})
    assert any("no text" in e for e in errs) and any("two options" in e for e in errs)
    assert any("used twice" in e for e in errs) and any("max must be above" in e for e in errs)
    assert any("grid" in e for e in errs)
    assert validate(FORM) == []
    assert all(validate({"questions": t["questions"]}) == [] for t in TEMPLATES)


def test_normalise_gives_stable_keys_and_defaults():
    qs = normalise([{"type": "scale", "text": "x"}, {"type": "bogus", "text": "y", "options": [" a ", "", "b"]}])
    assert qs[0]["key"] == "q1" and qs[0]["min"] == 1 and qs[0]["max"] == 5
    assert qs[1]["key"] == "q2" and qs[1]["type"] == "single" and qs[1]["options"] == ["a", "b"]


def _row(i, **ans):
    base = {"reasoning": "r", "open": "yes" if i % 3 else "no", "read": ["all", "some", "none"][i % 3],
            "who": ["me"] + (["my family"] if i % 2 else []), "score": 1 + (i % 5), "spend": 10.0 * (i + 1),
            "why": "clear and short" if i % 2 else "too pushy", "tone": {"clear": "agree", "pushy": "disagree" if i % 2 else "agree"}}
    base.update(ans)
    return {"agent_id": f"a{i:02d}", "agent": {"name": f"A{i}", "role": "r", "avatar_color": ""},
            "answer": base, "segments": {"stance": "direct" if i % 2 else "neutral", "age_band": "25-34",
                                         "humanity_band": "balanced", "purchase_intent_prior": "mid"}}


def test_aggregate_per_question_type():
    rows = [_row(i) for i in range(12)]
    agg = SV.aggregate(rows, {**FORM, "seed": 1})
    assert agg["n"] == 12 and agg["title"] == "About this email" and agg["primary"] == "open"
    q = {x["key"]: x for x in agg["questions"]}

    assert q["open"]["type"] == "yesno" and [d["value"] for d in q["open"]["distribution"]] == ["yes", "no"]
    assert q["open"]["distribution"][0]["count"] == 8 and q["open"]["headline"]["value"] == "yes"
    assert agg["headline"]["metric"] == "open" and agg["headline"]["successes"] == 8
    assert set(agg["segments"]) >= {"stance"}

    assert [d["value"] for d in q["read"]["distribution"]] == ["all", "some", "none"]          # form order kept
    who = {d["value"]: d["count"] for d in q["who"]["distribution"]}
    assert who["me"] == 12 and who["my family"] == 6 and who["nobody"] == 0 and q["who"]["mean_selected"] == 1.5

    assert q["score"]["mean"]["mean"] == pytest.approx(2.75)   # 1,2,3,4,5,1,2,3,4,5,1,2
    assert [d["value"] for d in q["score"]["distribution"]] == ["1", "2", "3", "4", "5"]         # one bucket per point
    assert q["score"]["top_two_box"]["successes"] == 4 and q["score"]["bottom_two_box"]["successes"] == 6

    assert q["spend"]["mean"]["mean"] == pytest.approx(65.0) and len(q["spend"]["distribution"]) == 8

    assert q["why"]["themes"] == [] and q["why"]["themes_coded"] is False and len(q["why"]["responses"]) == 12
    tone = {r["key"]: r for r in q["tone"]["rows"]}
    assert q["tone"]["columns"] == ["agree", "neutral", "disagree"]
    assert tone["clear"]["distribution"][0]["count"] == 12 and tone["pushy"]["distribution"][2]["count"] == 6
    assert all(x["sentence"] for x in agg["questions"])


def test_coded_themes_feed_the_open_question():
    rows = [_row(i, **{"why__theme": "clarity" if i % 2 else "tone"}) for i in range(6)]
    q = {x["key"]: x for x in SV.aggregate(rows, FORM)["questions"]}
    assert q["why"]["themes_coded"] and {d["value"] for d in q["why"]["themes"]} == {"clarity", "tone"}
    assert q["why"]["responses"][1]["theme"] == "clarity"


def test_aggregate_survives_missing_and_odd_answers():
    rows = [_row(0, who="me", tone="agree", score="high", spend=None)]
    agg = SV.aggregate(rows, FORM)
    q = {x["key"]: x for x in agg["questions"]}
    assert q["score"]["mean"]["n"] == 0 and q["spend"]["mean"]["n"] == 0
    assert q["who"]["distribution"][0]["count"] == 0 and q["tone"]["rows"][0]["n"] == 0


def test_http_survey_run_codes_themes_and_exports(api_client, monkeypatch):
    client, Session = api_client
    monkeypatch.setattr("app.services.measurement.themes.AsyncSessionLocal", Session)

    async def fake_analyze(schema, system, user, **kw):
        props = schema["properties"]
        if "themes" in props:
            return {"themes": [{"label": "clarity", "items": list(range(20))}]}
        assert "SURVEY: About this email" in user and "tone" in props
        return {"reasoning": "r", "open": "yes", "read": "all", "who": ["me"], "score": 4, "spend": 12.5,
                "why": "clear and short", "tone": {"clear": "agree", "pushy": "disagree"}}
    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_analyze)
    monkeypatch.setattr("app.services.measurement.themes.analyze", fake_analyze)

    listing = {i["key"]: i for i in client.get("/api/v1/lab/instruments").json()["instruments"]}
    assert listing["survey"]["form"] == "survey" and [t["key"] for t in listing["survey"]["templates"]][:2] == ["reaction", "email"]
    assert listing["ask"]["hidden"] is True

    session_id = client.post("/api/v1/sessions", json={"title": "T", "query": "q", "auto_research": False}).json()["id"]

    async def seed():
        async with Session() as db:
            for i in range(3):
                db.add(_agent(session_id=session_id, name=f"P{i}"))
            await db.commit()
    asyncio.run(seed())

    bad = client.post(f"/api/v1/sessions/{session_id}/probes",
                      json={"instrument": "survey", "spec": {"questions": [{"type": "single", "text": "x", "options": ["only one"]}]}})
    assert bad.status_code == 400 and "two options" in bad.text

    r = client.post(f"/api/v1/sessions/{session_id}/probes", json={"instrument": "survey", "spec": FORM})
    assert r.status_code == 200, r.text
    got = client.get(f"/api/v1/sessions/{session_id}/probes/{r.json()['id']}").json()
    assert got["status"] == "complete" and got["aggregates"]["n"] == 3
    q = {x["key"]: x for x in got["aggregates"]["questions"]}
    assert q["why"]["themes"][0]["value"] == "clarity" and q["open"]["distribution"][0]["share"] == 1.0
    assert got["answers"][0]["answer"]["why__theme"] == "clarity"

    csv_text = client.get(f"/api/v1/sessions/{session_id}/probes/{r.json()['id']}/export.csv").text
    header = csv_text.splitlines()[0]
    assert header.endswith("reasoning,open,read,who,score,spend,why,tone") and len(csv_text.strip().splitlines()) == 4
