"""Persona curation: cross-batch duplicates and survey fidelity.

Run:  cd backend && pytest tests/agent_factory_test.py -q
No network — the dedup and prompt-assembly logic is pure.

Both regressions were found by reading a real Pro spawn seeded with a 24-respondent survey:
the roster contained two identical 38-year-old urban mobility economists, and half the
"direct" group were invented analysts who were never in the panel.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.agents.agent_factory import (  # noqa: E402
    SURVEY_CHAR_LIMIT, _mirror_block, split_duplicates, uniquify_names,
)


def _p(name, role, age=38, stance="direct", humanity=0):
    return {"name": name, "role": role, "age": age, "stance": stance, "humanity": humanity}


# ── cross-batch duplicates ────────────────────────────────────────────────────

def test_identical_persona_from_two_batches_is_caught():
    kept, dupes = split_duplicates([
        _p("Dr. Priya Mehta", "Urban Mobility Economist"),
        _p("Marcus Osei", "NHS Radiographer", age=34),
        _p("Dr. Priya Mehta", "Urban Mobility Economist"),
    ])
    assert [d["name"] for d in kept] == ["Dr. Priya Mehta", "Marcus Osei"]
    assert len(dupes) == 1


def test_same_job_same_age_under_a_different_name_is_still_a_duplicate():
    """The failure mode isn't only repeated names — it's the same archetype twice."""
    kept, dupes = split_duplicates([
        _p("Dr. Priya Mehta", "Urban Mobility Economist", age=38),
        _p("Dr. Anita Rao", "urban mobility economist", age=38),
    ])
    assert len(kept) == 1 and len(dupes) == 1


def test_same_role_at_a_different_age_is_kept():
    kept, dupes = split_duplicates([
        _p("A Person", "Software Developer", age=31),
        _p("B Person", "Software Developer", age=44),
    ])
    assert len(kept) == 2 and not dupes


def test_nameless_and_malformed_entries_are_dropped():
    kept, _ = split_duplicates([_p("", "Role"), {"role": "x"}, "not a dict", _p("Real", "Role")])
    assert [d["name"] for d in kept] == ["Real"]


def test_dedup_preserves_order():
    kept, _ = split_duplicates([_p("A", "r1"), _p("B", "r2", age=40), _p("C", "r3", age=50)])
    assert [d["name"] for d in kept] == ["A", "B", "C"]


def test_uniquify_names_is_the_fallback_when_repair_fails():
    out = uniquify_names([_p("Dr. Priya Mehta", "r1"), _p("Dr. Priya Mehta", "r2"), _p("Dr. Priya Mehta", "r3")])
    names = [d["name"] for d in out]
    assert len(set(names)) == 3, names
    assert names[0] == "Dr. Priya Mehta"


# ── survey fidelity ───────────────────────────────────────────────────────────

def test_mirror_block_overrides_the_stance_quota():
    """The survey and the stance sliders are competing sources of truth for who the
    population is; mirroring makes the panel win."""
    block = _mirror_block(16)
    assert "REAL PANEL" in block
    assert "Ignore any requested stance percentages" in block
    assert "Do NOT invent domain experts" in block
    assert "16" in block


def test_survey_limit_is_a_single_shared_number():
    """The frontend trims to this same number and says so, instead of the file being cut at
    12,000 in the browser and again at 8,000 on the server with nothing reported."""
    assert SURVEY_CHAR_LIMIT == 8000
