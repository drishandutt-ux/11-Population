"""Tests for Forms (2026-10-06): the Lab brief's store and staleness, and the three ways to a
questionnaire — import (model and heuristic), write-for-me and the brainstorm chat — all
ending in a form the Survey instrument can run.

Run:  cd backend && pytest tests/forms_test.py -q
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.measurement import forms, lab_brief  # noqa: E402
from app.services.measurement.instruments.survey import validate  # noqa: E402

from tests.measurement_test import _agent, api_client  # noqa: E402,F401


def test_clean_form_makes_whatever_the_model_returns_runnable():
    f = forms.clean_form({
        "title": " Switching ",
        "questions": [
            {"key": "a", "type": "single", "text": "Which?", "options": ["only one"]},     # too few options → open text
            {"key": "a", "type": "scale", "text": "Rate", "min": 5, "max": 1},            # duplicate key, inverted scale
            {"key": "g", "type": "grid", "text": "Agree?", "rows": ["Clear"], "columns": []},  # grid with no columns → Likert
            {"type": "yesno", "text": "Yes?", "primary": True},
            {"type": "number", "text": ""},                                                # no text → dropped
            {"type": "nonsense", "text": "Odd", "options": ["x", "y"]},                    # unknown type → single
        ],
        "notes": ["kept"],
    })
    keys = [q["key"] for q in f["questions"]]
    assert len(keys) == len(set(keys)) == 5
    assert f["questions"][0]["type"] == "text" and any("no options" in n for n in f["notes"])
    assert f["questions"][1]["type"] == "scale" and f["questions"][1]["min"] < f["questions"][1]["max"]
    assert f["questions"][2]["columns"][0] == "strongly agree"
    assert sum(1 for q in f["questions"] if q["primary"]) == 1 and f["questions"][3]["primary"]
    assert f["questions"][4]["type"] == "single"
    assert f["title"] == "Switching" and f["problems"] == [] and validate({"questions": f["questions"]}) == []


def test_clean_form_picks_one_primary_when_none_or_many():
    none = forms.clean_form({"questions": [{"type": "text", "text": "Why?"}, {"type": "yesno", "text": "Would you?"}]})
    assert [q["primary"] for q in none["questions"]] == [False, True]      # first closed question leads
    many = forms.clean_form({"questions": [{"type": "yesno", "text": "A", "primary": True}, {"type": "yesno", "text": "B", "primary": True}]})
    assert [q["primary"] for q in many["questions"]] == [True, False]
    assert forms.clean_form({})["problems"] == ["Add at least one question."]


def test_heuristic_parse_reads_a_pasted_list():
    h = forms.heuristic_parse(
        "Commuter survey\n"
        "1. Would you switch to the e-bike? yes/no\n"
        "2) Why or why not?\n"
        "Q3: Which matter most? (tick all that apply)\n"
        "- price\n- theft cover\n- the weather\n"
        "4. On a scale of 1 to 10, how likely are you to try it?\n"
        "5. Which one plan would you pick?\n(a) monthly\n(b) annual\n"
    )
    qs = h["questions"]
    assert h["title"] == "Commuter survey" and len(qs) == 5
    assert qs[0]["type"] == "yesno" and qs[1]["type"] == "text"
    assert qs[2]["type"] == "multi" and qs[2]["options"] == ["price", "theft cover", "the weather"]
    assert qs[3]["type"] == "scale" and (qs[3]["min"], qs[3]["max"]) == (1, 10)
    assert qs[4]["type"] == "single" and qs[4]["options"] == ["monthly", "annual"]
    assert forms.clean_form(h)["problems"] == []


def test_history_ends_on_the_users_turn_and_merges_runs():
    h = forms._history([
        {"role": "assistant", "content": "hello"},           # a leading assistant turn is dropped
        {"role": "user", "content": "hi"},
        {"role": "user", "content": "again"},                # merged into one user turn
        {"role": "assistant", "content": "yes"},
        {"role": "user", "content": "draft it"},
    ])
    assert [m["role"] for m in h] == ["user", "assistant", "user"] and h[0]["content"] == "hi\n\nagain"
    assert forms._history([{"role": "assistant", "content": "x"}]) == []
    assert forms._history([{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}]) == []


def test_opening_names_the_briefs_top_challenge():
    o = forms.opening({"challenges": [{"title": "Price tolerance"}, {"title": "Theft worry"}]}, "q", has_form=False)
    assert "Price tolerance" in o["reply"] and o["chips"][0].startswith("Draft: Price tolerance")
    assert forms.opening(None, "q", has_form=True)["chips"][-1] == "Run it"


def test_brief_prompt_and_form_prompt_render():
    text = lab_brief.brief_for_prompt({"summary": "S", "challenges": [{"title": "T", "why": "W", "measure": "M"}], "vocabulary": ["dear", "faff"]})
    assert "T: W → measure: M" in text and "dear, faff" in text
    assert lab_brief.brief_for_prompt(None) == ""
    fp = forms.form_for_prompt({"title": "F", "questions": [{"key": "k", "type": "scale", "text": "Rate", "min": 1, "max": 7, "primary": True}]})
    assert "[k] (scale · primary) Rate" in fp and "scale 1–7" in fp
    assert forms.form_for_prompt({}) == "(the form is empty)"


FORM = {"title": "Switching", "intro": "", "questions": [
    {"key": "switch", "type": "yesno", "text": "Would you switch?", "primary": True, "why": "the decision"},
    {"key": "why", "type": "text", "text": "Why?"},
]}


def test_http_brief_builds_goes_stale_and_feeds_the_forms_calls(api_client, monkeypatch):
    client, Session = api_client
    sid = client.post("/api/v1/sessions", json={"title": "T", "query": "Would commuters switch to an e-bike subscription?", "auto_research": False}).json()["id"]

    calls = []

    async def fake_analyze(schema, system, user, **kw):
        calls.append((kw.get("label"), system, user, kw.get("messages")))
        label = kw.get("label")
        if label == "lab_brief":
            assert "THE QUESTION: Would commuters" in user
            return {"summary": "A session about e-bikes.", "population": "Commuters.", "what_we_know": ["Theft is the worry [evidence]"],
                    "tensions": ["Price vs convenience"], "challenges": [{"title": "Price tolerance", "why": "unmeasured", "measure": "a walk-away price"}],
                    "already_measured": [], "vocabulary": ["faff"], "gaps": ["older riders"]}
        if label == "forms_generate":
            assert "Lab brief" in user and "THE ANALYST'S GOAL: price" in user
            return {**FORM, "rationale": "because", "covers": ["Price tolerance"], "notes": []}
        if label == "forms_import":
            return {"title": "Imported", "intro": "", "questions": [{"key": "q1", "type": "single", "text": "Pick", "options": ["a", "b"], "primary": True}], "notes": ["dropped the consent line"]}
        if label == "forms_chat":
            assert kw["messages"][-1]["role"] == "user" and "Lab brief" in system and "THE FORM ON SCREEN" in system
            return {"reply": "Drafted two questions on price.", "chips": ["Run it", "Add a why"], "form_changed": True, "form": FORM, "change_note": "added 2"}
        raise AssertionError(label)

    monkeypatch.setattr("app.services.measurement.lab_brief.analyze", fake_analyze)
    monkeypatch.setattr("app.services.measurement.forms.analyze", fake_analyze)

    # Nothing yet: stale, no brief.
    g = client.get(f"/api/v1/sessions/{sid}/lab/brief").json()
    assert g["brief"] is None and g["stale"] is True and g["status"] == "none"

    # Build → ready and current; a second POST without force returns it without another call.
    b = client.post(f"/api/v1/sessions/{sid}/lab/brief", json={}).json()
    assert b["status"] == "ready" and b["stale"] is False and b["brief"]["challenges"][0]["title"] == "Price tolerance"
    assert b["brief"]["question"].startswith("Would commuters") and b["built_at"]
    n = len(calls)
    assert client.post(f"/api/v1/sessions/{sid}/lab/brief", json={}).json()["stale"] is False and len(calls) == n

    # The session moves on (a population appears) → the stored brief reads as stale; force rebuilds.
    async def seed():
        async with Session() as db:
            for k in range(3):
                db.add(_agent(session_id=sid, name=f"P{k}"))
            await db.commit()
    asyncio.run(seed())
    assert client.get(f"/api/v1/sessions/{sid}/lab/brief").json()["stale"] is True
    assert client.post(f"/api/v1/sessions/{sid}/lab/brief", json={"force": True}).json()["stale"] is False
    assert "THE ROSTER: 3 twins" in calls[-1][2]

    # Write it for me: the brief and the goal reach the prompt; the form comes back runnable.
    gen = client.post(f"/api/v1/sessions/{sid}/forms/generate", json={"goal": "price", "length": "short"}).json()
    assert [q["key"] for q in gen["questions"]] == ["switch", "why"] and gen["questions"][0]["primary"] and gen["problems"] == []
    assert gen["questions"][0]["why"] == "the decision" and gen["grounded"] is True and gen["covers"] == ["Price tolerance"]

    # Import pasted text via the model.
    imp = client.post(f"/api/v1/sessions/{sid}/forms/import", json={"text": "1. Pick\n- a\n- b"}).json()
    assert imp["title"] == "Imported" and imp["questions"][0]["options"] == ["a", "b"] and imp["notes"] == ["dropped the consent line"]
    assert client.post(f"/api/v1/sessions/{sid}/forms/import", json={"text": "  "}).status_code == 400

    # The chat: no history → the opening, written from the brief with no model call.
    n = len(calls)
    o = client.post(f"/api/v1/sessions/{sid}/forms/chat", json={"messages": [], "form": None}).json()
    assert "Price tolerance" in o["reply"] and o["form"] is None and len(calls) == n
    # A turn: the reply, the chips and the changed form.
    c = client.post(f"/api/v1/sessions/{sid}/forms/chat", json={"messages": [{"role": "user", "content": "draft something on price"}], "form": {"title": "", "questions": []}}).json()
    assert c["form_changed"] is True and c["form"]["questions"][0]["key"] == "switch" and c["chips"] == ["Run it", "Add a why"]
    assert c["change_note"] == "added 2"

    # The result of every path runs as an ordinary survey probe.
    assert client.post(f"/api/v1/sessions/{sid}/probes/estimate", json={"instrument": "survey", "spec": {"title": gen["title"], "questions": gen["questions"]}}).json()["agent_count"] == 3


def test_http_import_falls_back_to_the_heuristic_when_the_model_fails(api_client, monkeypatch):
    client, _ = api_client
    sid = client.post("/api/v1/sessions", json={"title": "T", "query": "Q?", "auto_research": False}).json()["id"]

    async def boom(*a, **k):
        raise RuntimeError("model down")
    monkeypatch.setattr("app.services.measurement.forms.analyze", boom)

    imp = client.post(f"/api/v1/sessions/{sid}/forms/import", json={"text": "Survey\n1. Would you? yes/no\n2. Why?"}).json()
    assert [q["type"] for q in imp["questions"]] == ["yesno", "text"] and any("without the model" in n for n in imp["notes"])

    # The file route reads the document then goes the same way.
    r = client.post(f"/api/v1/sessions/{sid}/forms/import/file", files={"file": ("q.txt", b"1. Would you? yes/no\n2. Which?\n- a\n- b", "text/plain")})
    assert r.status_code == 200 and r.json()["filename"] == "q.txt" and r.json()["questions"][1]["options"] == ["a", "b"]


def test_chat_keeps_the_form_when_a_change_would_empty_it(api_client, monkeypatch):
    client, _ = api_client
    sid = client.post("/api/v1/sessions", json={"title": "T", "query": "Q?", "auto_research": False}).json()["id"]

    async def fake(schema, system, user, **kw):
        if kw.get("label") == "lab_brief":
            return {"summary": "s", "population": "", "what_we_know": [], "tensions": [], "challenges": [], "already_measured": [], "vocabulary": [], "gaps": []}
        return {"reply": "Cleared it.", "chips": [], "form_changed": True, "form": {"title": "", "intro": "", "questions": []}, "change_note": "cleared"}
    monkeypatch.setattr("app.services.measurement.lab_brief.analyze", fake)
    monkeypatch.setattr("app.services.measurement.forms.analyze", fake)

    c = client.post(f"/api/v1/sessions/{sid}/forms/chat", json={"messages": [{"role": "user", "content": "clear it"}], "form": FORM}).json()
    assert c["form_changed"] is False and c["form"] is None and c["reply"] == "Cleared it."
