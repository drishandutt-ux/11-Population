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
    assert SURVEY_CHAR_LIMIT == 40000


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


def test_role_head_splits_on_a_slash_descriptor():
    """Pro spawns write roles as "Job / Descriptor"; two sergeants described differently are
    still two sergeants. This pair (both aged 49) survived the first version of the fix."""
    from app.services.agents.agent_factory import role_head
    assert role_head("Retired Police Sergeant / Sceptical Cyclist") == role_head(
        "Retired Police Sergeant / Ownership-Minded Cyclist")

    kept, dupes = split_duplicates([
        _p("Donal Fahy", "Retired Police Sergeant / Sceptical Cyclist", 49, stance="indirect"),
        _p("Roy Stanton", "Retired Police Sergeant / Ownership-Minded Cyclist", 49, stance="neutral"),
    ])
    assert len(kept) == 1 and len(dupes) == 1


def test_same_trade_a_generation_apart_still_survives():
    """Two print shop owners 15 years apart are plausibly two people — the age window is what
    separates a clone from a coincidence."""
    kept, dupes = split_duplicates([
        _p("Oliver Parrish", "Print Shop Owner / Self-Maintaining Cyclist", 42),
        _p("Gordon Baird", "Print Shop Owner / Committed Cyclist and DIY Mechanic", 57),
    ])
    assert len(kept) == 2 and not dupes


# ── a batch cut off at the output cap is topped up ────────────────────────────
# Local SimBench run 2026-10-28: a Haiku spawn:plan call asked for 10 personas, stopped at
# exactly max_tokens, the salvage parser kept the finished ones and the lineup ended at 8.

def _stub_plan_writer(monkeypatch, short_by: int):
    """Stub the persona writer: a first call returns `short_by` fewer personas than it was
    asked for, plus a half-written one (the shape of a max_tokens cut); top-ups are whole."""
    import asyncio
    import json
    import re
    from app.services.agents import agent_factory

    async def fake_rag(session_id):
        return session_id

    async def fake_query(rag, query, mode="hybrid"):
        return "kg"

    calls: list[tuple[str, int]] = []

    async def fake_create(client, *, session_id=None, label="", **kw):
        n = int(re.search(r"Create (\d+) distinct personas", kw["messages"][0]["content"]).group(1))
        calls.append((label, n))
        give = n if label.endswith(":topup") else max(0, n - short_by)
        people = [{"name": f"Person {len(calls)}-{k}", "age": 30 + k, "role": f"Job {len(calls)}-{k}", "background": "b",
                   "stance": "neutral", "humanity": 30, "gender": "female", "region": "Leeds", "dials": {}} for k in range(give)]
        text = json.dumps(people)
        stop = "end_turn"
        if give < n:
            text = text[:-1] + ', {"name": "Cut Off", "age": 4'   # the tail a truncated reply ends on
            stop = "max_tokens"

        class R:
            content = [type("T", (), {"text": text})()]
            stop_reason = stop
        return R()

    monkeypatch.setattr(agent_factory, "get_lightrag", fake_rag)
    monkeypatch.setattr(agent_factory, "query_rag", fake_query)
    monkeypatch.setattr(agent_factory, "tracked_messages_create", fake_create)
    return asyncio, agent_factory, calls


def test_truncated_plan_batch_is_topped_up_to_the_count_asked(monkeypatch):
    asyncio, agent_factory, calls = _stub_plan_writer(monkeypatch, short_by=2)
    seg = {"id": "a", "name": "Seg A", "count": 10, "stance": "neutral", "demographics": {}, "sentiment": {}}
    profiles = asyncio.new_event_loop().run_until_complete(
        agent_factory.generate_agents_from_plan("s", "q", [seg], {}, mode="fast"))
    assert len(profiles) == 10
    assert "Cut Off" not in {p.name for p in profiles}
    assert len({p.name for p in profiles}) == 10
    # Batches of six and four, each two short, each topped up with exactly the two missing.
    first = [n for label, n in calls if label == "spawn:plan"]
    topups = [n for label, n in calls if label == "spawn:plan:topup"]
    assert sorted(first) == [4, 6] and max(first) <= agent_factory._PLAN_BATCH_SIZE
    assert topups == [2, 2]


def test_a_top_up_is_asked_for_once_not_in_a_loop(monkeypatch):
    """If the top-up also comes back short the build moves on with what it has."""
    asyncio, agent_factory, calls = _stub_plan_writer(monkeypatch, short_by=2)
    from app.services.agents import agent_factory as af

    real = af.tracked_messages_create

    async def always_short(client, *, label="", **kw):
        return await real(client, label=label.replace(":topup", ""), **kw)   # top-ups truncate too

    monkeypatch.setattr(af, "tracked_messages_create", always_short)
    seg = {"id": "a", "name": "Seg A", "count": 6, "stance": "neutral", "demographics": {}, "sentiment": {}}
    profiles = asyncio.new_event_loop().run_until_complete(
        af.generate_agents_from_plan("s", "q", [seg], {}, mode="fast"))
    assert len(calls) == 2           # the batch and one top-up, no third call
    assert len(profiles) == 4        # 4 from the batch; the 2-slot top-up lost both to the same cut


def test_spawn_output_budget_stays_under_the_sdk_non_streaming_ceiling():
    """The SDK refuses a non-streaming request whose max_tokens implies more than 10 minutes
    (60 * 60 * max_tokens / 128_000 > 600, i.e. above ~21,333)."""
    from app.services.agents import agent_factory
    assert 12000 < agent_factory._SPAWN_MAX_TOKENS <= 21333


def test_parse_report_says_which_persona_failed_and_why():
    from app.services.agents.agent_factory import parse_report
    raw = '[{"name": "A", "age": 30}, {"name": "B", "background": "she said "no" twice", "age": 41}, {"name": "C", "age'
    line = parse_report(raw)
    assert line.startswith("1 objects parsed, 2 unparseable")
    assert "no" in line


def test_duplicate_repair_asks_in_batches_the_writer_can_finish(monkeypatch):
    """Ten clones once went to the writer in one call and hit the output cap."""
    asyncio, agent_factory, calls = _stub_plan_writer(monkeypatch, short_by=0)
    real = agent_factory.tracked_messages_create

    async def clones_first(client, *, label="", **kw):
        resp = await real(client, label=label, **kw)
        if label == "spawn:plan":   # every first-round persona is the same person
            import json
            people = json.loads(resp.content[0].text)
            for k, p in enumerate(people):
                p.update(name=f"Clone {k}", role="Same Job", age=40)
            resp.content[0].text = json.dumps(people)
        return resp

    monkeypatch.setattr(agent_factory, "tracked_messages_create", clones_first)
    seg = {"id": "a", "name": "Seg A", "count": 12, "stance": "neutral", "demographics": {}, "sentiment": {}}
    asyncio.new_event_loop().run_until_complete(agent_factory.generate_agents_from_plan("s", "q", [seg], {}, mode="fast"))
    repairs = [n for label, n in calls if label.startswith("spawn:plan:repair")]
    assert sum(repairs) == 11, repairs                                  # twelve clones: one kept, eleven rewritten
    assert max(repairs) <= agent_factory._PLAN_BATCH_SIZE, repairs
