"""Answer engines (2026-10-28): a twin's answer from its own setup, not the model's view of its group.

Run:  cd backend && pytest tests/answer_engines_test.py -q
No network — the model is stubbed.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.measurement import answer_engines as eng  # noqa: E402
from tests.measurement_test import _agent, api_client  # noqa: E402,F401

QUESTION = {"key": "q", "type": "single", "text": "How often do you attend religious services?",
            "options": ["Weekly", "Sometimes", "Never"], "likelihood": True}
MAP = {"base": {"o1": 20, "o2": 40, "o3": 40},
       "effects": {"religiosity": {"o1": 3, "o2": 0, "o3": -3}, "age": {"o1": 1, "o2": 0, "o3": -1}}}


def _with(att, **kw):
    a = _agent(**kw)
    a.demographics = {"gender": "female", "income_band": "middle", "education": "degree", "attitudes": att}
    return a


def test_the_reference_adult_gets_the_base_and_a_devout_twin_moves_towards_weekly():
    m = eng.clean_map(MAP, 3)
    ref, _ = eng.apply_map(m, {"religiosity": 5.0, "age": 45.0})
    assert abs(ref["o1"] - 20) < 0.5 and abs(ref["o3"] - 40) < 0.5
    devout, top = eng.apply_map(m, {"religiosity": 10.0, "age": 70.0})
    secular, _ = eng.apply_map(m, {"religiosity": 0.0, "age": 25.0})
    assert devout["o1"] > ref["o1"] > secular["o1"] and secular["o3"] > devout["o3"]
    assert top[0] == "religiosity"


def test_the_pooled_answer_follows_who_is_in_the_population():
    """The point of the engine: two populations with the same map but different members give
    different answers — the composition, not the model's view of the group, moves the result."""
    m = eng.clean_map(MAP, 3)
    devout = [_with({"religiosity": v}) for v in (8, 9, 10, 7)]
    secular = [_with({"religiosity": v}) for v in (0, 1, 2, 3)]
    pool = lambda people: sum(eng.map_answer({"q": m}, a)["q"]["o1"] for a in people) / len(people)  # noqa: E731
    assert pool(devout) > 2 * pool(secular)


def test_effects_are_clamped_and_missing_facts_sit_at_the_reference():
    m = eng.clean_map({"base": {"o1": 50, "o2": 50}, "effects": {"religiosity": {"o1": 40, "o2": -40}}}, 2)
    assert m["effects"]["religiosity"]["o1"] == eng.MAX_EFFECT
    nothing, top = eng.apply_map(m, {})
    assert nothing == {"o1": 50.0, "o2": 50.0} and top == []


def test_strict_message_drops_the_group_topic_and_puts_the_twins_facts_beside_the_question():
    from app.services.measurement import instruments
    from app.services.measurement.probe import _build_user_message
    inst = instruments.get("survey")
    a = _with({"religiosity": 9, "left_right": 7})
    spec = {"questions": [QUESTION], "answer_engine": "strict", "context": {"kg": False}}
    msg = _build_user_message(agent=a, instrument=inst, spec=spec, query="Life as seen by Catholics in Brazil", kg_context="", said=[], decided=[])
    assert "THE TOPIC" not in msg and "Catholics in Brazil" not in msg
    assert "YOUR FACTS" in msg and "How religious: 9/10" in msg
    persona = _build_user_message(agent=a, instrument=inst, spec={**spec, "answer_engine": "persona"}, query="Life as seen by Catholics in Brazil",
                                  kg_context="", said=[], decided=[])
    assert "THE TOPIC" in persona and "YOUR FACTS" not in persona
    assert "facts_used" in eng.with_facts_used({"type": "object", "properties": {}, "required": []})["required"]


def test_map_engine_answers_every_twin_from_one_call(api_client, monkeypatch):
    client, Session = api_client
    calls = []

    async def fake_llm(schema, system, user, **kw):
        calls.append(kw.get("label"))
        return MAP
    monkeypatch.setattr("app.services.evidence.llm.analyze", fake_llm)

    sid = client.post("/api/v1/sessions", json={"title": "T", "query": "Religion in Brazil", "auto_research": False}).json()["id"]

    async def seed():
        async with Session() as db:
            for k, r in enumerate((0, 2, 8, 10)):
                a = _with({"religiosity": r}, session_id=sid, name=f"P{k}")
                db.add(a)
            await db.commit()
    asyncio.run(seed())
    spec = {"questions": [QUESTION], "answer_engine": "map", "engine_context": {"country": "Brazil", "year": "2023"}}
    pid = client.post(f"/api/v1/sessions/{sid}/probes", json={"instrument": "survey", "spec": spec}).json()["id"]
    got = client.get(f"/api/v1/sessions/{sid}/probes/{pid}?include_answers=true").json()
    assert got["status"] == "complete" and got["answer_count"] == 4
    assert calls == ["probe:map"]                                   # one call for the question, none per twin
    weekly = sorted(a["answer"]["_dist"]["q"]["o1"] for a in got["answers"])
    assert weekly[-1] > 3 * weekly[0]                               # the devout twin, not the model, set the answer
    assert all(a["answer"]["_engine"] == "map" and a["answer"]["q"] in QUESTION["options"] for a in got["answers"])


def test_persona_writer_keeps_core_attitudes_on_the_twin():
    from app.services.agents.agent_factory import profile_from_dict
    p = profile_from_dict({"name": "A", "age": 40, "role": "r", "attitudes": {"religiosity": 12, "left_right": "3", "junk": 5}}, "s", "#000")
    assert p.demographics["attitudes"] == {"religiosity": 10, "left_right": 3}
    assert p.demographics["attitudes_from"] == "written"
