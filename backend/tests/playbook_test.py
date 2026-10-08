"""Segmentation playbooks: the analyst's own method — approach, segments, variables, rules —
read from markdown and applied to a Studio build without overriding the analyst.

Run:  cd backend && pytest tests/playbook_test.py -q
"""
import asyncio
import json
import os
import re
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.agents import agent_factory  # noqa: E402
from app.services.agents.agent_builder import DIAL_KEYS  # noqa: E402
from app.services.population import playbook as pb  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _full(v=5):
    return {g: {k: v for k in keys} for g, keys in DIAL_KEYS.items()}


EXAMPLE = _run(pb.parse(pb.example(), use_model=False))


# ── reading the markdown ─────────────────────────────────────────────────────

def test_the_template_reader_gets_the_example_whole():
    p = EXAMPLE
    assert p["title"] == "Migraine HCPs in London" and p["geography"] == "Greater London"
    assert p["approach"]["primary"] == "behavioural" and p["approach"]["match_exactly"] == ["role", "care setting"]
    assert [s["name"] for s in p["segments"]][:2] == ["Headache specialists (tertiary)", "General neurologists"]
    assert all(s["share_mode"] == "given" for s in p["segments"]) and sum(s["share_pct"] for s in p["segments"]) == 100
    v = {x["key"]: x for x in p["variables"]}
    assert set(v) == {"commute_burden", "burnout", "formulary_pressure", "care_setting"}
    assert v["care_setting"]["kind"] == "category" and "GP practice" in v["care_setting"]["values"]
    gp = next(e for e in v["burnout"]["by_segment"] if e["segment"] == "Generalist GPs")
    assert (gp["low"], gp["high"]) == (7, 9)
    # the analyst's "Pushes" line becomes links to real fixed dials
    assert {"dial": "motivation.novelty", "direction": -1, "strength": 2} in v["burnout"]["links"]
    assert v["burnout"]["evidence_mode"] == "find" and v["commute_burden"]["evidence_mode"] == "none"
    # rules aimed at a segment by a short prefix land on the right segment
    assert {"segment": "Community pharmacists", "text": "see medication-overuse headache weekly and worry about it.", "section": "Rules of character"} in p["rules"]
    assert len(p["unsure"]) == 2


def test_variables_with_no_links_get_keyword_links_and_keys_never_shadow_a_fixed_dial():
    p = pb.normalise({"approach": {"primary": "attitudinal"}, "variables": [
        {"label": "Frustration", "kind": "dial", "low": "calm", "high": "furious"},
        {"label": "Commute time", "kind": "dial", "links": [{"dial": "not.a_dial", "direction": "up", "strength": 9}]},
    ]})
    a, b = p["variables"]
    assert a["key"] == "frustration_level"                       # "frustration" is a fixed sentiment dial
    assert all(ln["dial"] in pb.FIXED_PATHS for ln in b["links"]) and any(ln["dial"] == "friction.time_cost" for ln in b["links"])


def test_markdown_round_trip_keeps_what_the_analyst_wrote():
    again = pb.normalise(pb.heuristic_parse(pb.to_markdown(EXAMPLE)))
    assert [s["name"] for s in again["segments"]] == [s["name"] for s in EXAMPLE["segments"]]
    assert [(v["key"], v["kind"], v["by_segment"]) for v in again["variables"]] == [(v["key"], v["kind"], v["by_segment"]) for v in EXAMPLE["variables"]]
    assert {(ln["dial"], ln["direction"]) for ln in again["variables"][1]["links"]} == {(ln["dial"], ln["direction"]) for ln in EXAMPLE["variables"][1]["links"]}


def test_the_template_itself_parses_to_an_empty_but_valid_playbook():
    p = pb.normalise(pb.heuristic_parse(pb.template()))
    assert p["segments"] == [] and p["variables"] == [] and p["rules"] == []


# ── the plan keeps the analyst's segmentation ────────────────────────────────

def _seg(sid, name, share):
    return {"id": sid, "name": name, "share_pct": share, "stance": "direct", "description": "", "demographics": {}, "decision": "proposed"}


def test_apply_to_plan_keeps_names_and_stated_shares_and_drops_extras():
    planned = [_seg("s1", "generalist GPs", 30), _seg("s2", "Hospital pharmacists", 10), _seg("s3", "General neurologists", 25)]
    segs, notes = pb.apply_to_plan(planned, EXAMPLE)
    by = {s["name"]: s for s in segs}
    assert list(by) == [s["name"] for s in EXAMPLE["segments"]]           # the analyst's six, in their order
    assert by["Generalist GPs"]["share_pct"] == 50 and by["Generalist GPs"]["id"] == "s1"   # the planner's version, the analyst's share
    assert by["Headache specialist nurses"]["rationale"] == "From the analyst's playbook."
    assert any("Hospital pharmacists" in n for n in notes) and any("Headache specialist nurses" in n for n in notes)
    assert len({s["id"] for s in segs}) == len(segs)


def test_without_segments_the_plan_is_untouched():
    p = dict(EXAMPLE, segments=[])
    planned = [_seg("s1", "Anyone", 100)]
    assert pb.apply_to_plan(planned, p) == (planned, [])


# ── per-twin values ──────────────────────────────────────────────────────────

def _fitted(name):
    seg = {"id": "s1", "name": name, "playbook_segment": name}
    pb.ensure_fits(EXAMPLE, [seg])
    return seg


def test_values_are_drawn_inside_the_segment_range_and_repeat_on_a_rebuild():
    seg = _fitted("Generalist GPs")
    assert seg["playbook_fit"]["ranges"]["burnout"] == [7, 9] and seg["playbook_fit"]["values"]["care_setting"] == ["GP practice"]
    slots = pb.draw_slots(EXAMPLE, seg, 40, "x")
    burn = [s["dials"]["burnout"] for s in slots]
    assert all(7 <= b <= 9 for b in burn) and len(set(burn)) > 1                 # spread, not everyone a 7
    assert {s["facets"]["care_setting"] for s in slots} == {"GP practice"}
    assert pb.draw_slots(EXAMPLE, seg, 40, "x") == slots and pb.draw_slots(EXAMPLE, seg, 40, "y") != slots


def test_category_labels_spread_evenly_over_the_segments_labels():
    seg = _fitted("General neurologists")
    labels = [s["facets"]["care_setting"] for s in pb.draw_slots(EXAMPLE, seg, 10, "x")]
    assert labels.count("tertiary headache centre") == 5 and labels.count("district general hospital") == 5


def test_links_push_the_fixed_dials_and_five_moves_nothing():
    assert pb.link_shifts(EXAMPLE, {"burnout": 5}) == {}
    hi = pb.link_shifts(EXAMPLE, {"burnout": 10})
    assert hi["sentiment.frustration"] == 2 and hi["motivation.novelty"] == -2
    lo = pb.link_shifts(EXAMPLE, {"burnout": 0})
    assert lo["sentiment.frustration"] == -2
    both = pb.link_shifts(EXAMPLE, {"burnout": 10, "commute_burden": 10})       # time cost pushed by both, capped
    assert both["friction.time_cost"] == 4
    d = {"dials": dict(_full(5), dynamic={"burnout": 10})}
    pb.apply_links(EXAMPLE, [d])
    assert d["dials"]["sentiment"]["frustration"] == 7 and d["dials"]["motivation"]["novelty"] == 3


def test_pin_overwrites_the_writer_and_adds_the_segments_rules():
    seg = _fitted("Generalist GPs")
    slots = [{"dials": {"burnout": 8}, "facets": {"care_setting": "GP practice"}}]
    d = {"dials": {"dynamic": {"burnout": 2}}, "facets": {"care_setting": "community pharmacy"}}
    pb.pin(EXAMPLE, seg, slots, [d])
    assert d["dials"]["dynamic"]["burnout"] == 8 and d["facets"]["care_setting"] == "GP practice"
    rules = d["character"]["playbook_rules"]
    assert any("10-minute appointments" in r for r in rules)
    assert any(r.startswith("Your burnout is 8/10") for r in rules)
    assert not any("medication-overuse" in r for r in rules)                  # the pharmacists' rule is theirs


def test_the_persona_prompt_renders_the_rules():
    from app.services.agents.agent_runner import _character_block
    agent = type("A", (), {"character": {"playbook_rules": ["Your burnout is 8/10: short, tired answers"]}})()
    assert "YOUR SITUATION AND HOW IT SHOWS" in _character_block(agent) and "short, tired answers" in _character_block(agent)


# ── dials, facets, searches, report ──────────────────────────────────────────

def test_pinned_dials_come_first_and_the_models_repeats_are_dropped():
    pinned = pb.dial_definitions(EXAMPLE)
    assert [d["key"] for d in pinned] == ["commute_burden", "burnout", "formulary_pressure"]
    model = [{"key": "burnout", "label": "Burnout"}, {"key": "travel_burden", "label": "Commute burden"}, {"key": "waiting_list_pressure", "label": "Waiting-list pressure"}]
    merged = pb.merge_dials(pinned, model)
    assert [d["key"] for d in merged] == ["commute_burden", "burnout", "formulary_pressure", "waiting_list_pressure"]
    facets = pb.merge_facets(pb.facet_definitions(EXAMPLE), [{"key": "place", "label": "Where they live", "attribute": "region"}, {"key": "age_band", "label": "Age band", "attribute": "age"}])
    assert [f["key"] for f in facets] == ["place", "care_setting", "age_band"]


def test_gather_targets_hunt_what_the_analyst_asked_for():
    ts = pb.gather_targets(EXAMPLE, "London", ["ons", "nhs"])
    assert ts[0]["playbook"] == "burnout" and "NHS Staff Survey" in ts[0]["queries"][0]["query"]
    assert any(t["playbook"] == "segments" for t in ts) and len(ts) <= 3


def test_fit_falls_back_to_the_analysts_ranges_when_the_model_fails(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("no model")
    monkeypatch.setattr(pb, "analyze", boom)
    segs, _ = pb.apply_to_plan([_seg("s1", "Generalist GPs", 50)], EXAMPLE)
    out = _run(pb.fit("s", EXAMPLE, segs, ""))
    gp = next(s for s in segs if s["name"] == "Generalist GPs")
    assert out["checks"] == [] and out["fits"][gp["id"]]["ranges"]["formulary_pressure"] == [8, 10]


def test_fit_keeps_the_analysts_numbers_over_the_models_reading(monkeypatch):
    segs, _ = pb.apply_to_plan([_seg("s1", "Generalist GPs", 50)], EXAMPLE)
    gp = next(s for s in segs if s["name"] == "Generalist GPs")

    async def fake(schema, system, user, **k):
        return {"segments": [{"segment_id": gp["id"], "values": [{"variable": "burnout", "low": 2, "high": 4, "categories": []}]}],
                "checks": [{"item": "Generalist GPs share 50%", "kind": "segment_share", "status": "contradicted", "note": "GPs are 35% of the panel frame", "source": "NHS Digital"}]}
    monkeypatch.setattr(pb, "analyze", fake)
    out = _run(pb.fit("s", EXAMPLE, segs, "material"))
    assert out["fits"][gp["id"]]["ranges"]["burnout"] == [7, 9]
    assert out["checks"][0]["status"] == "contradicted"
    summary = pb.plan_summary(EXAMPLE, out["checks"])
    assert "FLAG" in pb.report_block(summary) and "kept" in pb.report_block(summary)
    assert "Burnout" in summary["hypotheses"]


# ── a stubbed build writes twins with the analyst's forces ───────────────────

def test_generate_from_plan_draws_pins_and_links(monkeypatch):
    async def fake_rag(session_id):
        return "rag"

    async def fake_query(rag, q, mode="hybrid"):
        return "summary"

    prompts = []

    async def fake_create(client, *, session_id=None, label="", **kw):
        prompt = kw["messages"][0]["content"]
        prompts.append(prompt)
        n = int(re.search(r"Create (\d+) distinct personas", prompt).group(1))
        out = [{"name": f"Dr {k} {len(prompts)}", "age": 40 + k, "role": f"GP {k}", "background": "b", "stance": "direct", "humanity": 30, "dials": dict(_full(5), dynamic={"burnout": 1}),
                "region": "Hackney", "gender": "female", "income_band": "high", "education": "postgraduate", "occupation": f"GP {k}"} for k in range(n)]

        class R:  # noqa: D401
            content = [type("T", (), {"text": json.dumps(out)})()]
        return R()

    monkeypatch.setattr(agent_factory, "get_lightrag", fake_rag)
    monkeypatch.setattr(agent_factory, "query_rag", fake_query)
    monkeypatch.setattr(agent_factory, "tracked_messages_create", fake_create)
    seg = dict(_seg("s1", "Generalist GPs", 100), count=12, playbook_segment="Generalist GPs", humanity_hint="tempered")
    pb.ensure_fits(EXAMPLE, [seg])
    dyn = pb.dial_definitions(EXAMPLE)
    profiles = _run(agent_factory.generate_agents_from_plan("s", "New migraine preventive?", [seg], {"playbook": EXAMPLE, "dynamic_dials": dyn}, mode="fast"))
    assert len(profiles) == 12
    assert "ANALYST'S PLAYBOOK VALUES" in prompts[0] and "Burnout" in prompts[0]
    for p in profiles:
        b = p.dials["dynamic"]["burnout"]
        assert 7 <= b <= 9 and 8 <= p.dials["dynamic"]["formulary_pressure"] <= 10      # the drawn value, not the writer's 1
        assert p.demographics["facets"]["care_setting"] == "GP practice"
        # links pushed the fixed dials: novelty only by burnout (7-9 → −1/−2); frustration by burnout up
        # and a short commute (3-6) down, so it can net to nothing but never below the writer's 5
        assert p.dials["motivation"]["novelty"] < 5 and p.dials["sentiment"]["frustration"] >= 5
        assert any("10-minute appointments" in r for r in p.character["playbook_rules"])
    # two batches of the same segment draw different values (seeded per batch, not per snapshot)
    first, second = [p.dials["dynamic"]["commute_burden"] for p in profiles[:10]], [p.dials["dynamic"]["commute_burden"] for p in profiles[10:]]
    assert first[:2] != second or len(set(first)) > 1


# ── HTTP: library, parse, and a build that follows the playbook ──────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.core.database as dbm
    from app.core.config import get_settings
    import app.models.report, app.models.preset, app.models.kg, app.models.population, app.models.archetype  # noqa: F401
    from app.services.population import builder
    from app.services.agents import dynamic_dials as dyn_mod

    monkeypatch.setattr(get_settings(), "app_supabase_url", "")
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/pb.db")
    Session = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(dbm, "engine", eng)
    monkeypatch.setattr(dbm, "AsyncSessionLocal", Session)
    monkeypatch.setattr(dbm, "_sqlite", True)
    seen = {}

    async def fake_analyze(schema, system, user, **kw):
        props = schema.get("properties", {})
        if "target_population" in props:
            seen["detect"] = user
            return {"topic": "t", "decision": "d", "geography": "London", "target_population": "HCPs", "population_kind": "professionals", "segments_hinted": [],
                    "demographic_signals": [], "sentiment_signals": [], "gaps": [], "confidence": 70, "dials": {}}
        if "questions" in props:
            return {"questions": [], "note": "ok"}
        if "segments" in props:
            seen["plan"] = user
            mk = lambda sid, name, share: {"id": sid, "name": name, "share_pct": share, "stance": "direct", "description": "d", "age_min": 30, "age_max": 60, "gender_female_pct": 50,
                                           "regions": ["London"], "income_band": "high", "education": "postgraduate", "occupations": ["doctor"], "mood": "mixed", "temperature": 5,
                                           "top_emotions": [], "arguments": [], "evidence": [], "rationale": "r", "humanity_hint": "expert"}
            return {"segments": [mk("s1", "Generalist GPs", 40), mk("s2", "Practice managers", 20), mk("s3", "Community pharmacists", 40)],
                    "rationale": "r", "assumptions": [], "evidence_coverage": "c"}
        return {}

    async def fake_fit(schema, system, user, **kw):
        return {"segments": [], "checks": [{"item": "Generalist GPs share 50%", "kind": "segment_share", "status": "contradicted", "note": "the brief puts GPs at 35%", "source": "brief"}]}

    async def no_model(*a, **k):
        raise RuntimeError("offline")

    async def fake_pick(*a, **k):
        return [{"key": "place", "label": "Where they live", "kind": "attribute", "attribute": "region", "why": "", "values_hint": []}]

    async def fake_dials(*a, **k):
        return [{"key": "waiting_list_pressure", "label": "Waiting-list pressure", "why": "w", "low": "l", "high": "h"}]

    monkeypatch.setattr(builder, "analyze", fake_analyze)
    monkeypatch.setattr(pb, "analyze", lambda schema, *a, **k: (fake_fit if "checks" in schema.get("properties", {}) else no_model)(schema, *a, **k))
    monkeypatch.setattr(builder.facets_mod, "pick_facets", fake_pick)
    monkeypatch.setattr(dyn_mod, "pick_dials", fake_dials)
    dyn_mod._CACHE.clear()

    async def _get_db():
        async with Session() as s:
            yield s

    from fastapi.testclient import TestClient
    from app.main import app
    app.dependency_overrides[dbm.get_db] = _get_db
    with TestClient(app) as c:
        c.seen = seen
        yield c
    app.dependency_overrides.clear()


def _wait(client, sid, until, timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        b = client.get(f"/api/v1/sessions/{sid}/population/builds/latest").json()["build"]
        if b and until(b):
            return b
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_library_round_trip(client):
    t = client.get("/api/v1/playbooks/template").json()
    assert "## Approach" in t["template"] and "Migraine" in t["example"]
    parsed = client.post("/api/v1/playbooks/parse", json={"markdown": t["example"]}).json()["playbook"]
    assert parsed["parsed_by"] == "template" and len(parsed["segments"]) == 6
    assert client.post("/api/v1/playbooks/parse", json={"markdown": "  "}).status_code == 400
    # edit what was understood (drop a link), save: the analyst's text is kept as written and the
    # confirmed settings are appended as "Studio settings" (3 dial variables → 3 more Pushes lines)
    parsed["variables"][1]["links"] = parsed["variables"][1]["links"][:1]
    saved = client.post("/api/v1/playbooks", json={"playbook": parsed, "edited": True}).json()
    assert saved["title"] == "Migraine HCPs in London" and saved["markdown"].startswith(t["example"].rstrip())
    assert "## Studio settings" in saved["markdown"] and saved["markdown"].count("- **Pushes:**") == 4
    assert [s["heading"] for s in saved["view"]][:3] == ["About this playbook", "Migraine HCPs in London — segmentation playbook", "Approach"]
    # reading the saved file again: the settings win over the original text
    again = client.post("/api/v1/playbooks/parse", json={"markdown": saved["markdown"]}).json()["playbook"]
    assert len(next(v for v in again["variables"] if v["key"] == "burnout")["links"]) == 1
    lst = client.get("/api/v1/playbooks").json()["playbooks"]
    assert len(lst) == 1 and lst[0]["segments"] == 6 and lst[0]["variables"] == 4
    upd = client.put(f"/api/v1/playbooks/{saved['id']}", json={"markdown": t["example"].replace("Migraine HCPs in London", "Migraine HCPs v2")}).json()
    assert upd["title"] == "Migraine HCPs v2"
    assert client.get(f"/api/v1/playbooks/{saved['id']}").json()["playbook"]["id"] == saved["id"]
    md = client.post("/api/v1/playbooks/render", json={"playbook": parsed}).json()["markdown"]
    assert md.rstrip() == t["example"].rstrip()                      # not edited → the file exactly as written
    assert client.delete(f"/api/v1/playbooks/{saved['id']}").json() == {"deleted": True}
    assert client.get("/api/v1/playbooks").json()["playbooks"] == []


def test_a_build_follows_the_playbook_and_flags_without_overriding(client):
    parsed = client.post("/api/v1/playbooks/parse", json={"markdown": pb.example()}).json()["playbook"]
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "Will London HCPs adopt a new migraine preventive?", "auto_research": False}).json()["id"]
    r = client.post(f"/api/v1/sessions/{sid}/population/builds", json={"mode": "fast", "count": 40, "constraints": {"skip_questions": True, "playbook": parsed},
                                                                       "sources": {"quant": False, "quant_sources": []}})
    assert r.status_code == 200, r.text
    b = _wait(client, sid, lambda b: b["status"] in ("awaiting_review", "error"))
    assert b["status"] == "awaiting_review", b.get("error")
    assert "ANALYST'S SEGMENTATION PLAYBOOK" in client.seen["detect"] and "use exactly these" in client.seen["plan"]
    segs = {s["name"]: s for s in b["plan"]["segments"]}
    assert list(segs) == [s["name"] for s in parsed["segments"]]                     # practice managers dropped, missing ones written
    assert segs["Generalist GPs"]["share_pct"] == 50                                  # the evidence said 35%: flagged, not applied
    assert segs["Generalist GPs"]["playbook_fit"]["ranges"]["burnout"] == [7, 9]
    assert [d["key"] for d in b["plan"]["dynamic_dials"]][:3] == ["commute_burden", "burnout", "formulary_pressure"]
    assert "waiting_list_pressure" in [d["key"] for d in b["plan"]["dynamic_dials"]]
    assert [f["key"] for f in b["plan"]["facets"]] == ["place", "care_setting"]
    assert b["plan"]["playbook"]["checks"][0]["status"] == "contradicted"
    msgs = [e["message"] for e in b["log"]]
    assert any(m.startswith("Following your segmentation playbook") for m in msgs)
    assert any("Flag · the evidence disagrees" in m for m in msgs)
    assert any("Dropped segments the planner added" in m and "Practice managers" in m for m in msgs)


def test_a_segment_never_takes_a_neighbours_range_or_rules_from_a_shared_word():
    """Seen in the local run: 'GPs with an extended role in headache' was drawn from the Generalist
    GPs' burnout range (7-9, not the 6-8 written for it) and the nurses from the specialists'."""
    gpwer, nurses = _fitted("GPs with an extended role in headache"), _fitted("Headache specialist nurses")
    assert gpwer["playbook_fit"]["ranges"]["burnout"] == [6, 8] and gpwer["playbook_fit"]["ranges"]["formulary_pressure"] == [5, 8]
    assert nurses["playbook_fit"]["ranges"]["commute_burden"] == [5, 8]
    assert pb._rules_for(EXAMPLE, gpwer) == [] and pb._rules_for(EXAMPLE, nurses) == []
    # a plan segment the analyst did not name finds its entry only by a strict match
    planner_named = {"id": "x", "name": "Generalist GPs (inner London)"}
    pb.ensure_fits(EXAMPLE, [planner_named])
    assert planner_named["playbook_fit"]["ranges"]["burnout"] == [7, 9]


def test_a_small_segment_still_spans_its_range():
    seg = _fitted("GPs with an extended role in headache")
    burn = [s["dials"]["burnout"] for s in pb.draw_slots(EXAMPLE, seg, 5, "x")]
    assert set(burn) == {6, 7, 8}


# ── nothing the analyst wrote is dropped ─────────────────────────────────────

FREEFORM = pb.example().replace(
    "| Segment | Share | Who they are | Source for share |\n|---|---|---|---|",
    "| Segment | Share | Who they are | Source for share | Typical channel |\n|---|---|---|---|---|").replace(
    "| find |\n| General neurologists", "| find | conferences |\n| General neurologists").replace(
    "- **Evidence:** find — NICE TA", "- **Pharma contact:** reps are not seen in most practices\n- **Evidence:** find — NICE TA") + """

## Decision-making unit

- GPs defer to the ICB medicines-optimisation pharmacist on anything new.

## Generalist GPs — a day in the life

Back-to-back 10-minute slots, 40 patients a day, admin until 8pm.
"""


def test_sections_columns_and_fields_the_template_has_no_slot_for_are_kept():
    p = _run(pb.parse(FREEFORM, use_model=False))
    ex = {e["heading"]: e for e in p["extras"]}
    assert "ICB medicines-optimisation pharmacist" in ex["Decision-making unit"]["text"] and ex["Decision-making unit"]["applies_to"] == ""
    assert ex["Generalist GPs — a day in the life"]["applies_to"] == "Generalist GPs"
    assert p["segments"][0]["attributes"] == {"Typical channel": "conferences"}
    assert next(v for v in p["variables"] if v["key"] == "formulary_pressure")["notes"] == {"pharma contact": "reps are not seen in most practices"}
    assert "Decision-making unit" in p["source_markdown"]
    view = {s["heading"]: s["uses"] for s in pb.annotate_sections(p)}
    assert view["Burnout"]["variables"] == ["burnout"] and view["Decision-making unit"]["extras"] == [0]


def test_a_free_form_document_loses_nothing_even_when_no_reader_understands_it():
    md = "# Pharmacists in Leeds\n\nThey are split by how much they rely on the wholesaler.\n\n## Who calls the shots\n\nThe superintendent.\n"
    p = _run(pb.parse(md, use_model=False))
    texts = " ".join(e["text"] for e in p["extras"])
    assert "wholesaler" in texts and "superintendent" in texts


def test_the_planner_and_each_twin_get_what_was_kept():
    p = _run(pb.parse(FREEFORM, use_model=False))
    block = pb.prompt_block(p)
    assert "Decision-making unit" in block and "Typical channel: conferences" in block and "THE PLAYBOOK AS THE ANALYST WROTE IT" in block
    gp = {"id": "s1", "name": "Generalist GPs", "playbook_segment": "Generalist GPs"}
    nurse = {"id": "s2", "name": "Headache specialist nurses", "playbook_segment": "Headache specialist nurses"}
    assert any("40 patients a day" in c for c in pb.segment_context(p, gp))
    assert not any("40 patients a day" in c for c in pb.segment_context(p, nurse))
    assert any("ICB medicines-optimisation" in c for c in pb.segment_context(p, nurse))
    d = {"dials": {}}
    pb.pin(p, gp, [], [d])
    assert any("40 patients" in c for c in d["character"]["playbook_context"])
    from app.services.agents.agent_runner import _character_block
    assert "WHAT IS TRUE OF PEOPLE LIKE YOU" in _character_block(type("A", (), {"character": d["character"]})())
