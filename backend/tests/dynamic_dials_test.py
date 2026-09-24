"""Dynamic dials (brief L3-04): the question's own dials, chosen by the model and tuned per twin.

Run:  cd backend && pytest tests/dynamic_dials_test.py -q
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.agents import dynamic_dials as dyn  # noqa: E402
from app.services.agents import archetypes as ar  # noqa: E402
from app.services.agents.agent_builder import DIAL_KEYS, clean_fixed_dials, with_dynamic  # noqa: E402

DIALS = [
    {"key": "formulary_pressure", "label": "Formulary pressure", "why": "What the local list lets them do.", "low": "no constraint", "high": "blocked in practice"},
    {"key": "transport_friction", "label": "Transport friction", "why": "How hard it is to get there.", "low": "door to door", "high": "two buses and a wait"},
]


def test_definitions_are_slugged_deduped_and_cannot_shadow_a_fixed_dial():
    out = dyn.clean_definitions([
        {"key": "Formulary Pressure", "label": "Formulary pressure", "why": "w", "low": "l", "high": "h"},
        {"key": "formulary_pressure", "label": "again", "why": "w", "low": "l", "high": "h"},   # duplicate
        {"key": "anger", "label": "Anger", "why": "w", "low": "l", "high": "h"},                # already a fixed dial
        {"label": "Transport friction", "why": "w", "low": "l", "high": "h"},                   # key from the label
    ])
    assert [d["key"] for d in out] == ["formulary_pressure", "transport_friction"]


def test_definitions_are_capped():
    many = [{"key": f"d{k}", "label": f"D{k}", "why": "w", "low": "l", "high": "h"} for k in range(30)]
    assert len(dyn.clean_definitions(many)) == dyn.MAX_DIALS


def test_values_are_filtered_to_the_defined_dials_and_clamped():
    vals = dyn.clean_values({"formulary_pressure": 12, "transport_friction": "3", "invented": 9, "anger": 8}, DIALS)
    assert vals == {"formulary_pressure": 10, "transport_friction": 3}


def test_attach_moves_the_writers_values_into_the_dial_profile():
    d = {"name": "X", "dials": {"sentiment": {"anger": 7}}, "dynamic": {"formulary_pressure": 8, "nope": 1}}
    out = dyn.attach(d, DIALS)
    assert out["dials"]["dynamic"] == {"formulary_pressure": 8}
    assert out["dials"]["sentiment"] == {"anger": 7}     # the fixed dials are untouched
    assert "dynamic" not in out                           # the top-level key is consumed


def test_attach_is_a_no_op_when_the_session_has_no_dynamic_dials():
    d = {"name": "X", "dials": {"sentiment": {"anger": 7}}, "dynamic": {"whatever": 3}}
    assert dyn.attach(d, [])["dials"] == {"sentiment": {"anger": 7}}


def test_prompt_and_schema_blocks_are_empty_without_dials():
    assert dyn.prompt_block([]) == "" and dyn.schema_block([]) == ""
    assert "formulary_pressure" in dyn.prompt_block(DIALS) and "two buses" in dyn.prompt_block(DIALS)
    assert '"formulary_pressure":0' in dyn.schema_block(DIALS)


def test_guidance_states_the_end_the_twin_is_at():
    g = dyn.guidance(DIALS, {"formulary_pressure": 9, "transport_friction": 1, "unknown": 5})
    assert "Formulary pressure: 9/10 — blocked in practice" in g
    assert "Transport friction: 1/10 — door to door" in g
    assert "unknown" not in g
    assert dyn.guidance(DIALS, {}) == ""


def test_values_of_reads_an_existing_profile():
    dials = {"sentiment": {"anger": 7}, "dynamic": {"formulary_pressure": 6, "left_over": 4}}
    assert dyn.values_of(dials) == {"formulary_pressure": 6, "left_over": 4}      # no filter: keep both
    assert dyn.values_of(dials, DIALS) == {"formulary_pressure": 6}               # filtered to this session


def test_an_authored_profile_keeps_its_dynamic_values_beside_the_112():
    full = {g: {k: 5 for k in keys} for g, keys in DIAL_KEYS.items()}
    full["dynamic"] = {"formulary_pressure": 9}
    stored = with_dynamic(clean_fixed_dials(full), dyn.values_of(full))
    assert stored["dynamic"] == {"formulary_pressure": 9}
    assert stored["sentiment"]["anger"] == 5


def test_a_cast_persona_stays_within_drift_of_the_moulds_dynamic_dials():
    prior = {"dynamic": {"formulary_pressure": 8, "transport_friction": 2}}
    got = {"dynamic": {"formulary_pressure": 1, "transport_friction": 3, "extra": 7}}
    out = ar._enforce_dynamic(prior, got)
    assert out["formulary_pressure"] == 8 - ar.DIAL_DRIFT    # pulled back to the mould
    assert out["transport_friction"] == 3                    # inside the band, left alone
    assert out["extra"] == 7                                 # not in the mould: the writer's value stands


def test_a_mould_authored_for_another_question_does_not_erase_the_new_dials():
    out = ar._enforce_dynamic({}, {"dynamic": {"formulary_pressure": 6}})
    assert out == {"formulary_pressure": 6}
