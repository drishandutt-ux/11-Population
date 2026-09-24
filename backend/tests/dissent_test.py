"""Dissent, refusal and consensus drift (brief L3-06).

Four mechanisms: a bounded licence to say "I don't know", that refusal as a first-class Lab
answer, independent voices who never read the room, and the unanimity check.

Run:  cd backend && pytest tests/dissent_test.py -q
"""
import os
import sys
import uuid
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.models.session import AnalysisSession, SessionStatus  # noqa: E402
from app.models.measurement import Probe  # noqa: E402
from app.services.agents import agent_runner  # noqa: E402
from app.services.measurement import instruments, unanimity  # noqa: E402
from app.services.measurement import probe as probe_svc  # noqa: E402
from app.services.simulation import orchestrator  # noqa: E402

from tests.measurement_test import _agent, lab_db, api_client, _async  # noqa: E402,F401

ASK = instruments.get("ask")


# ── 1. the licence to not know, bounded ───────────────────────────────────────

def test_the_limits_block_names_what_this_twin_can_speak_to():
    agent = _agent(session_id="s", name="Ann")
    agent.role = "GP partner"
    agent.demographics = {"region": "Blackpool"}
    agent.character = {"information_diet": "NICE guidance and the local prescribing lead"}
    block = agent_runner._limits_block(agent)
    assert "GP partner" in block and "Blackpool" in block
    assert "NICE guidance and the local prescribing lead" in block


def test_the_licence_is_bounded_not_a_shrug():
    block = agent_runner._limits_block(_agent(session_id="s", name="Ann"))
    assert "DO NOT KNOW" in block                       # it may decline
    assert "not permission to shrug" in block           # but not on its own ground
    assert "call it a guess" in block                   # a labelled guess is allowed


def test_every_twin_prompt_carries_it():
    prompt = agent_runner._build_system_prompt(_agent(session_id="s", name="Ann"))
    assert "WHAT YOU ACTUALLY KNOW" in prompt
    probe_prompt = agent_runner._build_system_prompt(_agent(session_id="s", name="Ann"), task="probe")
    assert "WHAT YOU ACTUALLY KNOW" in probe_prompt      # the Lab measures the same person


# ── 2. refusal as a first-class Lab answer ────────────────────────────────────

def test_every_instrument_schema_gains_the_same_escape_hatch():
    schema = probe_svc.with_dont_know(ASK.schema_for({}))
    assert schema["properties"][probe_svc.CAN_ANSWER]["enum"] == ["yes", "no"]
    assert probe_svc.CAN_ANSWER in schema["required"] and probe_svc.WHY_NOT in schema["required"]
    # the instrument's own fields survive untouched
    assert "verdict" in schema["properties"] and "verdict" in schema["required"]


def test_the_rule_says_when_to_use_it():
    assert "no basis" in probe_svc.DONT_KNOW_RULE
    assert "Do NOT use it to avoid" in probe_svc.DONT_KNOW_RULE


def test_answered_reads_the_twins_own_flag():
    assert probe_svc.answered({"answer": {"verdict": "yes"}})                       # absent = answered
    assert probe_svc.answered({"answer": {probe_svc.CAN_ANSWER: "yes"}})
    assert not probe_svc.answered({"answer": {probe_svc.CAN_ANSWER: "no"}})


def test_the_refusal_block_reports_the_share_and_the_reasons():
    rows = [
        {"agent_id": "1", "answer": {probe_svc.CAN_ANSWER: "yes"}},
        {"agent_id": "2", "answer": {probe_svc.CAN_ANSWER: "no", probe_svc.WHY_NOT: "I don't live there"}},
        {"agent_id": "3", "answer": {probe_svc.CAN_ANSWER: "no", probe_svc.WHY_NOT: "I don't live there"}},
        {"agent_id": "4", "answer": {}},
    ]
    out = probe_svc.dont_know_block(rows)
    assert out["refused"] == 2 and out["n"] == 4 and out["share"] == 0.5
    assert out["reasons"][0]["value"] == "I don't live there" and out["reasons"][0]["count"] == 2
    assert {w["agent_id"] for w in out["who"]} == {"2", "3"}


def test_a_refusal_is_kept_out_of_the_denominator_and_reported_beside_it(lab_db, monkeypatch):
    """The whole point: a twin with no basis must not be forced into the share we quote."""
    Session, loop = lab_db
    session_id = str(uuid.uuid4())
    seen = []

    async def fake_analyze(schema, system, user, **kw):
        seen.append(system)
        n = len(seen)
        if n <= 2:      # two twins say it is not theirs to answer
            return {"reasoning": "not mine", "verdict": "yes", "strength": 5, "feeling": 0,
                    "key_factor": "x", probe_svc.CAN_ANSWER: "no", probe_svc.WHY_NOT: "I have never used one"}
        return {"reasoning": "r", "verdict": "yes", "strength": 8, "feeling": 1, "key_factor": "price",
                probe_svc.CAN_ANSWER: "yes", probe_svc.WHY_NOT: ""}

    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_analyze)
    monkeypatch.setattr("app.services.measurement.probe._probe_kg_context", lambda *a, **k: _async("ENTITIES: none"))
    monkeypatch.setattr("app.services.measurement.themes.analyze", fake_analyze)

    async def run():
        async with Session() as db:
            db.add(AnalysisSession(id=session_id, title="T", query="q", status=SessionStatus.COMPLETE))
            for i in range(6):
                db.add(_agent(session_id=session_id, name=f"A{i}"))
            p = Probe(session_id=session_id, instrument="ask", schema_id=ASK.schema_id(),
                      spec={"material": "m", "question": "Would you open this?"}, seed=1, model="m", status="queued")
            db.add(p)
            await db.commit()
            pid = p.id
        await probe_svc.run_probe(pid)
        async with Session() as db:
            return await db.get(Probe, pid)

    probe = loop.run_until_complete(run())
    agg = probe.aggregates
    assert agg["dont_know"]["refused"] == 2 and agg["dont_know"]["share"] == round(2 / 6, 4)
    assert agg["dont_know"]["reasons"][0]["value"] == "I have never used one"
    assert agg["headline"]["n"] == 4                       # the four who had a view
    assert probe.answer_count == 6                          # but everyone who responded is counted
    # The rule reached the twins, on top of the instrument's own directive.
    assert probe_svc.DONT_KNOW_RULE.strip()[:40] in seen[0]


# ── 3. independent voices ─────────────────────────────────────────────────────

def _ids(n):
    return [SimpleNamespace(id=f"agent-{k}") for k in range(n)]


def test_a_share_of_twins_never_read_the_room():
    picked = orchestrator._independent_ids(_ids(400), 0.3)
    assert 0.2 < len(picked) / 400 < 0.4


def test_the_same_twins_stay_independent_across_phases():
    agents = _ids(200)
    assert orchestrator._independent_ids(agents, 0.3) == orchestrator._independent_ids(agents, 0.3)


def test_the_share_can_be_turned_off_or_up():
    assert orchestrator._independent_ids(_ids(50), 0) == set()
    assert len(orchestrator._independent_ids(_ids(50), 1)) == 50


def test_reading_the_room_comes_with_a_dissent_rule():
    assert "Agreeing adds nothing" in agent_runner._DISSENT_RULE
    assert "even if you are the only one" in agent_runner._DISSENT_RULE
    assert "never adopt a position because it" in agent_runner._DISSENT_RULE


# ── 4. the unanimity check ────────────────────────────────────────────────────

def _segments(*shares, key="stance", n=10):
    return {key: [{"segment": key, "value": f"g{k}", "share": v, "n": n} for k, v in enumerate(shares)]}


def test_a_lopsided_result_with_no_spread_between_groups_is_flagged():
    out = unanimity.check({"share": 0.95, "n": 40}, _segments(0.96, 0.94, 0.95), n=40)
    assert out["flagged"] and "95%" in out["reason"]
    assert out["widest_spread"] <= unanimity.FLAT


def test_a_lopsided_result_is_fine_when_the_groups_actually_differ():
    out = unanimity.check({"share": 0.9, "n": 40}, _segments(1.0, 0.55), n=40)
    assert out["flagged"] is False


def test_a_split_room_is_never_flagged():
    out = unanimity.check({"share": 0.55, "n": 40}, _segments(0.56, 0.54), n=40)
    assert out["flagged"] is False


def test_unanimous_the_other_way_is_just_as_suspicious():
    out = unanimity.check({"share": 0.03, "n": 40}, _segments(0.03, 0.02, 0.04), n=40)
    assert out["flagged"] and out["top_share"] == 0.97


def test_tiny_buckets_are_not_a_split():
    # Two buckets of one agent each cannot tell us the population disagreed.
    out = unanimity.check({"share": 0.95, "n": 40}, _segments(1.0, 0.0, n=1), n=40)
    assert out is None


def test_prior_dials_are_not_treated_as_people():
    # purchase_intent_prior is a dial, not a group of people: it cannot vouch for disagreement.
    out = unanimity.check({"share": 0.95, "n": 40}, _segments(0.95, 0.95, key="purchase_intent_prior"), n=40)
    assert out is None


def test_nothing_to_say_without_a_share_or_splits():
    assert unanimity.check(None, {}) is None
    assert unanimity.check({"share": 0.9}, {}) is None
