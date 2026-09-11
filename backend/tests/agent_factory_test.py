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


# ── the roster that prompted the fix ──────────────────────────────────────────

def test_role_head_strips_the_employer():
    from app.services.agents.agent_factory import role_head
    assert role_head("Urban Mobility Economist, Transport Policy Institute") == role_head(
        "Urban Mobility Economist, University of Leeds")
    assert role_head("Retired Police Sergeant, Sheffield") == role_head(
        "Retired Police Sergeant and Cycling Club Treasurer, Sheffield")
    assert role_head("NHS Radiographer, Leeds (Night Shifts)") == role_head(
        "NHS Radiographer, Night-Shift Worker, Leeds")
    assert role_head("Software Developer, Manchester") != role_head("Pharmacy Technician, Nottingham")


def test_same_job_similar_age_is_a_clone_even_under_another_name():
    kept, dupes = split_duplicates([
        _p("Dr. Priya Mehta", "Urban Mobility Economist, Transport Policy Institute", age=38),
        _p("Dr. Priya Menon", "Urban Mobility Economist, Transport Policy Research Centre", age=39),
    ])
    assert len(kept) == 1 and len(dupes) == 1


def test_real_before_roster_collapses_its_clone_clusters():
    """The 25-agent survey-seeded spawn that prompted this work. Whole-role matching caught
    one duplicate; job-title matching catches the economist, radiographer and sergeant
    clusters too."""
    roster = [
        _p("Dr. Priya Mehta", "Urban Mobility Economist, Transport Policy Institute", 38),
        _p("Dr. Priya Mehta", "Urban Mobility Economist, University of Leeds", 38),
        _p("Dr. Priya Menon", "Urban Mobility Economist, Transport Policy Research Centre", 39),
        _p("Marcus Osei", "NHS Radiographer, Leeds (Night Shifts)", 34),
        _p("Tamsin Gallagher", "NHS Radiographer, Night-Shift Worker, Leeds", 33),
        _p("Sandra Okonkwo", "Retired Police Sergeant, Sheffield", 49),
        _p("Tom Haskell", "Retired Police Sergeant and Cycling Club Treasurer, Sheffield", 49),
        _p("Jamie Kowalski", "Software Developer, Manchester (Remote-Hybrid)", 31),
        _p("Rachel Ndegwa", "Pharmacy Technician, Nottingham", 39),
    ]
    kept, dupes = split_duplicates(roster)
    names = [d["name"] for d in kept]
    assert len(dupes) == 4, [d["name"] for d in dupes]
    assert names == ["Dr. Priya Mehta", "Marcus Osei", "Sandra Okonkwo", "Jamie Kowalski", "Rachel Ndegwa"]


def test_a_genuinely_different_person_with_the_same_job_survives():
    """Two software developers a generation apart are two people, not one persona twice."""
    kept, dupes = split_duplicates([
        _p("A Person", "Software Developer, Manchester", 31),
        _p("B Person", "Software Developer, Bristol", 44),
    ])
    assert len(kept) == 2 and not dupes
