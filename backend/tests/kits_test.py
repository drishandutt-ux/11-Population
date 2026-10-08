"""Tests for population kits and benchmarks: reading a pollster's crosstab, drawing agents from
a kit, enforcing a card on a written persona, Forms routing / caps, and scoring a run.

Run:  cd backend && pytest tests/kits_test.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.kits import benchmark, cast, crosstab, registry  # noqa: E402
from app.services.measurement.instruments.survey import aggregate, normalise, question_for, schema_for, validate  # noqa: E402
from tests.measurement_test import api_client  # noqa: E402,F401

GROUP = ["", "", "Gender", "", "Segment", ""]
LABELS = ["Q", "All", "Male", "Female", "Left", "Right"]


def _sheet():
    return [
        ["Q"], ["Which do you prefer?"], GROUP, LABELS,
        ["Tea", "0.6", "0.5", "0.7", "0.8", "0.4"],
        ["Coffee", "0.4", "0.5", "0.3", "0.2", "0.6"],
        ["Net", "0.2", "0", "0.4", "0.6", "-0.2"],
        ["Weighted N", "100", "50", "50", "50", "50"],
        ["Unweighted N", "100", "48", "52", "51", "49"],
        ["Weight", "Weight"],
    ]


def test_crosstab_block_reads_columns_bases_and_flags_rollups():
    s = crosstab.parse_sheet("Q", _sheet())
    assert s["question"] == "Which do you prefer?"
    t = s["tables"][0]
    assert [c["key"] for c in t["columns"]] == ["All", "Gender: Male", "Gender: Female", "Segment: Left", "Segment: Right"]
    assert crosstab.table_shares(t) == {"Tea": 0.6, "Coffee": 0.4}          # "Net" is a roll-up, left out
    assert crosstab.table_shares(t, "Segment: Right") == {"Tea": 0.4, "Coffee": 0.6}
    assert t["weighted_n"]["Segment: Left"] == 50.0


def test_crosstab_grid_items_and_verbatims():
    rows = [["G"], ["How much trust?"], GROUP, ["G: NHS", *LABELS[1:]], ["A lot", "0.7", "0.7", "0.7", "0.9", "0.5"], ["Not much", "0.3", "0.3", "0.3", "0.1", "0.5"],
            ["Weighted N", "100", "50", "50", "50", "50"], GROUP, ["G: Banks", *LABELS[1:]], ["A lot", "0.2", "0.2", "0.2", "0.1", "0.3"],
            ["Not much", "0.8", "0.8", "0.8", "0.9", "0.7"], ["Weighted N", "100", "50", "50", "50", "50"]]
    s = crosstab.parse_sheet("G", rows)
    assert [t["item"] for t in s["tables"]] == ["NHS", "Banks"]
    other = crosstab.parse_sheet("(specify) why..", [["x"], ["Other (please specify)"], GROUP, LABELS, ["Too costly", "0.1", "0", "0.2", "0.2", "0"]])
    assert other["tables"] == [] and other["verbatims"][0]["text"] == "Too costly"
    assert other["verbatims"][0]["columns"] == ["Gender: Female", "Segment: Left"]


def test_shipped_benchmark_matches_the_workbook():
    b = benchmark.load("mic_11london_june2023")
    assert b and len(b["questions"]) == 23
    q1 = next(q for q in b["questions"] if q["key"] == "q1_priorities")
    shares = crosstab.table_shares(q1["tables"][0])
    assert round(shares["Increasing the availability of GP appointments"] * 100, 1) == 51.6
    assert round(shares["Improving emergency services (e.g., A&E)"] * 100, 1) == 49.2
    form = benchmark.load_form("mic_11london_june2023")
    assert validate(form) == []
    q12 = next(q for q in normalise(form["questions"]) if q["key"] == "q12_why_skipped")
    assert q12["show_if"] == {"key": "q11_skipped_meds", "equals": ["Yes"]} and len(q12["options"]) == 14


def test_forms_cap_exclusive_and_routing():
    form = {"questions": [
        {"key": "a", "type": "single", "text": "Ever?", "options": ["Yes", "No"]},
        {"key": "b", "type": "multi", "text": "Why?", "options": ["x", "y", "None of the above"], "exclusive": ["None of the above"],
         "show_if": {"key": "a", "equals": "Yes"}},
        {"key": "c", "type": "multi", "text": "Pick", "options": ["p", "q", "r", "s"], "max_choices": 2},
    ]}
    schema = schema_for(form)
    assert schema["properties"]["c"]["maxItems"] == 2
    text = question_for(form)
    assert schema["properties"]["c"]["uniqueItems"] is True
    assert "choose up to 2 different options" in text and "ONLY if you answered \"Yes\" to question 1" in text and "None of the above: only on its own" in text
    rows = [{"answer": {"a": "Yes", "b": ["x", "x"], "c": ["p"]}, "agent": {}, "agent_id": "1"},
            {"answer": {"a": "No", "b": [], "c": ["q"]}, "agent": {}, "agent_id": "2"},
            {"answer": {"a": "Yes", "b": ["y"], "c": ["p", "q"]}, "agent": {}, "agent_id": "3"}]
    out = aggregate(rows, form)
    b = next(q for q in out["questions"] if q["key"] == "b")
    assert b["n"] == 2                                   # only the two routed to it
    assert {d["value"]: d["count"] for d in b["distribution"]}["x"] == 1     # ["x", "x"] counts once
    assert b["mean_selected"] == 1.0


KIT = {
    "id": "t", "title": "Test kit", "population": "GB adults",
    "share_presets": {"a": {"label": "A", "shares": {"s1": 75, "s2": 25}}}, "default_preset": "a",
    "frame_defaults": {"region": {"North": 50, "South": 50}},
    "frame": [{"key": "region", "label": "Region", "attribute": "region", "categories": [{"label": "North", "share_pct": 50}, {"label": "South", "share_pct": 50}]}],
    "segments": [
        {"id": "s1", "name": "One", "summary": "First", "humanity_hint": "balanced",
         "distributions": {"age_band": {"18-34": 40, "35-54": 60}, "gender": {"female": 50, "male": 50}},
         "beliefs": [{"agree": "I trust the NHS", "disagree": "I do not trust the NHS", "agree_pct": 70},
                     {"agree": "Most people can be trusted", "disagree": "You can't be too careful", "agree_pct": 20}],
         "character": {"information_diet": "BBC"}},
        {"id": "s2", "name": "Two", "summary": "Second", "distributions": {"age_band": {"55-74": 100}, "gender": {"female": 100}}, "beliefs": []},
    ],
}


def test_quota_matches_the_mix_exactly():
    labels = registry.quota({"a": 33, "b": 33, "c": 34}, 10)
    assert len(labels) == 10 and sorted(set(labels)) == ["a", "b", "c"]
    assert registry.quota({"x": 40, "y": 60}, 20).count("y") == 12


def test_cards_are_seeded_and_hit_the_published_belief_shares():
    seg = KIT["segments"][0]
    a = registry.draw_cards(KIT, seg, 20, seed=1)
    assert a == registry.draw_cards(KIT, seg, 20, seed=1)
    assert sum(1 for c in a if "I trust the NHS" in c["beliefs"]) == 14
    assert sum(1 for c in a if "Most people can be trusted" in c["beliefs"]) == 4
    assert sum(1 for c in a if c["age_band"] == "35-54") == 12 and all(35 <= c["age"] <= 54 for c in a if c["age_band"] == "35-54")
    assert sum(1 for c in a if c["region"] == "North") == 10   # frame default when the segment has no region mix


def test_plan_from_kit(monkeypatch):
    monkeypatch.setattr(registry, "load_kit", lambda k: KIT if k == "t" else None)
    plan = registry.plan_from_kit(KIT, 8)
    assert [s["count"] for s in plan["segments"]] == [6, 2]
    assert all(len(s["kit_cards"]) == s["count"] for s in plan["segments"])
    assert plan["kit"]["preset"] == "a"
    frame = registry.frame_from_kit(KIT)
    assert frame["targets"]["region"]["status"] == "uploaded"
    plan["segments"][0]["count"] = 3
    registry.ensure_cards(plan, plan["segments"])
    assert len(plan["segments"][0]["kit_cards"]) == 3


def test_enforce_card_overrides_the_written_persona():
    seg = KIT["segments"][0]
    card = {"slot": 1, "age": 44, "gender": "female", "region": "North West England", "education": "No degree", "ge2019": "Labour",
            "beliefs": ["I trust the NHS"], "typicality": 0.8}
    d = cast.enforce(seg, card, {"name": "X", "age": 30, "gender": "male", "town": "Bolton", "humanity": 99, "region": "London"})
    assert d["age"] == 44 and d["gender"] == "female" and d["region"] == "Bolton, North West England"
    assert d["education"] == "secondary"
    assert d["frame"] == {"region": "North West England", "age": "Gen X (41-55)", "gender": "Female", "ge2019": "Labour", "education": "No degree"}
    assert d["character"]["beliefs"] == ["I trust the NHS"] and d["character"]["information_diet"] == "BBC"
    assert d["humanity"] <= 80


def _bench():
    cols = [{"key": k, "group": k.split(":")[0] if ":" in k else "All", "label": k.split(": ")[-1]} for k in ("All", "Segment: Left", "Segment: Right")]
    t = {"label": "Q", "item": None, "rows": [{"label": "Tea", "derived": False, "values": {"All": 0.6, "Segment: Left": 0.8, "Segment: Right": 0.4}},
                                             {"label": "Coffee", "derived": False, "values": {"All": 0.4, "Segment: Left": 0.2, "Segment: Right": 0.6}}],
         "weighted_n": {"All": 100, "Segment: Left": 50, "Segment: Right": 50}}
    return {"id": "b", "columns": cols, "questions": [{"key": "q", "type": "single", "text": "Q", "options": ["Tea", "Coffee"], "tables": [t]}]}


def test_score_rewards_getting_the_segments_right():
    resp = []
    for seg, tea in (("Left", 8), ("Right", 4)):
        for k in range(10):
            resp.append({"segment": seg, "age": 40, "demographics": {}, "weight": 1.0, "answer": {"q": "Tea" if k < tea else "Coffee"}})
    s = benchmark.score(_bench(), resp)
    assert s["headline"]["mae_pts"] == 0.0 and s["headline"]["top_choice_agreement"] == 1.0
    assert s["by_column"]["Segment: Left"]["mae_pts"] == 0.0
    assert s["by_column"]["Segment: Left"]["national_baseline_mae_pts"] == 20.0
    flat = [{**r, "answer": {"q": "Tea" if i % 10 < 6 else "Coffee"}} for i, r in enumerate(resp)]
    s2 = benchmark.score(_bench(), flat)
    assert s2["headline"]["mae_pts"] == 0.0                        # the total is right…
    assert s2["by_column"]["Segment: Left"]["mae_pts"] == 20.0     # …but the segments are not


def test_responses_from_the_csv_export():
    form = {"questions": [{"key": "m", "type": "multi"}, {"key": "g", "type": "grid"}, {"key": "s", "type": "single"}]}
    rows = [{"segment": "Left", "age": "33", "gender": "female", "region": "Wales", "ge2019": "Labour", "weight": "1.2",
             "m": json.dumps(["a", "b"]), "g": "{'nhs': 'A lot'}", "s": "Tea"}]
    r = benchmark.responses_from_csv(rows, form)[0]
    assert r["answer"] == {"m": ["a", "b"], "g": {"nhs": "A lot"}, "s": "Tea"} and r["weight"] == 1.2
    assert benchmark.cuts_for(r)["Region"] == "Region: Wales" and benchmark.cuts_for(r)["Age by generation"] == "Age by generation: Millennials (25-40)"


# ── the shipped kit, end to end without the model ─────────────────────────────

def test_shipped_kit_builds_a_plan_on_the_poll_mix():
    kit = registry.load_kit("britains_choice_2020")
    assert kit and len(kit["segments"]) == 7
    assert all(len(s["beliefs"]) >= 25 and all(b["source"] for b in s["beliefs"]) for s in kit["segments"])
    plan = registry.plan_from_kit(kit, 200)
    counts = {s["name"]: s["count"] for s in plan["segments"]}
    assert sum(counts.values()) == 200 and counts["Loyal Nationals"] == 45 and counts["Disengaged Battlers"] == 15
    regions = {c["region"] for s in plan["segments"] for c in s["kit_cards"]}
    poll_regions = {c["label"] for c in benchmark.load("mic_11london_june2023")["columns"] if c["group"] == "Region"}
    assert regions <= poll_regions                     # every card is cut by the poll's own region labels


def test_kit_segments_are_written_from_their_cards(monkeypatch):
    import asyncio
    import re
    from app.services.agents import agent_factory
    kit = registry.load_kit("britains_choice_2020")
    plan = registry.plan_from_kit(kit, 14)
    prompts = []

    async def fake_rag(*a, **k):
        return None

    async def fake_query(*a, **k):
        return "nothing"

    async def fake_create(client, *, session_id=None, label="", **kw):
        prompt = kw["messages"][0]["content"]
        prompts.append((label, prompt))
        n = int(re.search(r"Write (\d+) people", prompt).group(1))
        out = [{"slot": k + 1, "name": f"P{len(prompts)}-{k}", "town": "Leeds", "role": "Clerk", "occupation": "clerk", "age": 18, "gender": "x",
                "background": "b", "humanity": 100, "dials": {}, "personality": ["p"], "debate_style": "d", "geo_behavior": "g", "correlation": "c"} for k in range(n)]

        class R:
            content = [type("T", (), {"text": json.dumps(out)})()]
        return R()

    monkeypatch.setattr(agent_factory, "get_lightrag", fake_rag)
    monkeypatch.setattr(agent_factory, "query_rag", fake_query)
    monkeypatch.setattr(agent_factory, "tracked_messages_create", fake_create)
    profiles = asyncio.new_event_loop().run_until_complete(
        agent_factory.generate_agents_from_plan("s", "Health and charities", plan["segments"], {}, mode="fast"))
    assert len(profiles) == 14 and {lab for lab, _ in prompts} == {"spawn:kit"}
    assert any("Loyal Nationals" in p and "What this person believes" in p for _, p in prompts)
    ages = {s["name"]: sorted(c["age"] for c in s["kit_cards"]) for s in plan["segments"]}
    got: dict = {}
    for p in profiles:
        got.setdefault(p.segment, []).append(p.age)
    assert {k: sorted(v) for k, v in got.items()} == {k: v for k, v in ages.items() if v}   # the cards' ages, not the model's 18
    for p in profiles:
        assert p.character["beliefs"] and p.character["kit"]["segment"] == p.segment
        assert p.demographics["frame"]["region"] in p.demographics["region"]
        assert p.stance == "neutral" and p.humanity <= 80


def test_shattered_britain_kit_is_cited_and_builds():
    kit = registry.load_kit("shattered_britain_2025")
    assert kit and [s["share_pct"] for s in kit["segments"]] == [12, 21, 9, 10, 20, 8, 20]
    dd = next(s for s in kit["segments"] if s["name"] == "Dissenting Disruptors")
    beliefs = {b["id"]: b for b in dd["beliefs"]}
    assert beliefs["covid_exaggerated"]["agree_pct"] == 65 and "p75" in beliefs["covid_exaggerated"]["source"]
    plan = registry.plan_from_kit(kit, 100)
    assert sum(s["count"] for s in plan["segments"]) == 100
    assert all(c.get("region") for s in plan["segments"] for c in s["kit_cards"])   # national region mix fills the gap
    assert "What the research found" in cast.segment_block(dd)


def test_frame_report_counts_the_drawn_cards():
    from app.services.population import frame as F
    kit = registry.load_kit("britains_choice_2020")
    plan = registry.plan_from_kit(kit, 200)
    rep = F.build_report(registry.frame_from_kit(kit), plan["segments"], 200)
    assert F.summary_line(rep).startswith("Frame match good")      # not "poor — 89 pts off" from the segment summaries


# ── likelihood answers and staged routing (run 2) ─────────────────────────────

LIKELY_FORM = {"title": "T", "seed": 7, "questions": [
    {"key": "ever", "type": "single", "text": "Ever skipped?", "options": ["Yes", "No", "Don't know"], "likelihood": True},
    {"key": "why", "type": "multi", "text": "Why?", "options": ["forgot", "side effects", "None of the above"], "exclusive": ["None of the above"],
     "show_if": {"key": "ever", "equals": ["Yes"]}, "likelihood": True},
    {"key": "pick", "type": "multi", "text": "Top 2", "options": ["a", "b", "c", "d"], "max_choices": 2, "likelihood": True},
    {"key": "trust", "type": "grid", "text": "Trust", "rows": ["NHS"], "columns": ["Lots", "Little"], "likelihood": True},
]}


def test_likelihood_schema_and_stages():
    from app.services.measurement.instruments import survey as sv
    first, follow = sv.stages(LIKELY_FORM)
    assert [q["key"] for q in first[0]["questions"]] == ["ever", "pick", "trust"] and first[1] is None
    assert [q["key"] for q in follow[0]["questions"]] == ["why"] and follow[1]["key"] == "why"
    props = sv.schema_for(first[0])["properties"]
    assert set(props["ever"]["properties"]) == {"o1", "o2", "o3"} and set(props["trust"]["properties"]["nhs"]["properties"]) == {"o1", "o2"}
    assert "CHANCE" in sv.question_for(first[0]) and "ONLY if" not in sv.question_for(follow[0] | {"_followup_stage": True})


def test_realise_draws_from_the_likelihoods():
    import random as _r
    from app.services.measurement.instruments import survey as sv
    raw = {"reasoning": "r", "ever": {"o1": 25, "o2": 70, "o3": 5}, "pick": {"o1": 90, "o2": 80, "o3": 70, "o4": 0},
           "trust": {"nhs": {"o1": 100, "o2": 0}}}
    picks = [sv.realise(raw, LIKELY_FORM, _r.Random(k)) for k in range(2000)]
    yes = sum(1 for p in picks if p["ever"] == "Yes") / len(picks)
    assert 0.21 < yes < 0.29                                         # drawn near its 25% chance, not always the mode
    assert all(len(p["pick"]) <= 2 and len(set(p["pick"])) == len(p["pick"]) and "d" not in p["pick"] for p in picks)
    assert all(p["trust"] == {"nhs": "Lots"} for p in picks) and picks[0]["_dist"]["ever"]["o2"] == 70
    excl = sv.realise({"why": {"o1": 0, "o2": 0, "o3": 100}}, {"questions": [LIKELY_FORM["questions"][1]]}, _r.Random(1))
    assert excl["why"] == ["None of the above"]


def test_probe_asks_followups_only_when_routed(api_client, monkeypatch):
    import asyncio
    from tests.measurement_test import _agent
    client, Session = api_client
    calls = []

    async def fake_analyze(schema, system, user, **kw):
        props = schema["properties"]
        calls.append(sorted(k for k in props if k in ("ever", "why", "pick", "trust")))
        if "why" in props:
            assert "FOLLOW-UP" in user and 'you answered "Yes"' in user
            return {"reasoning": "f", "why": {"o1": 100, "o2": 0, "o3": 0}}
        yes = "Agent0" in system
        return {"reasoning": "r", "ever": {"o1": 100 if yes else 0, "o2": 0 if yes else 100, "o3": 0},
                "pick": {"o1": 100, "o2": 0, "o3": 0, "o4": 0}, "trust": {"nhs": {"o1": 60, "o2": 40}}}
    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_analyze)
    sid = client.post("/api/v1/sessions", json={"title": "T", "query": "q", "auto_research": False}).json()["id"]

    async def seed():
        async with Session() as db:
            for k in range(3):
                db.add(_agent(session_id=sid, name=f"Agent{k}"))
            await db.commit()
    asyncio.run(seed())
    r = client.post(f"/api/v1/sessions/{sid}/probes", json={"instrument": "survey", "spec": LIKELY_FORM})
    assert r.status_code == 200, r.text
    got = client.get(f"/api/v1/sessions/{sid}/probes/{r.json()['id']}").json()
    assert got["status"] == "complete"
    assert sum(1 for c in calls if c == ["why"]) == 1 and len(calls) == 4      # three first stages, one follow-up
    by = {a["answer"]["ever"]: a["answer"] for a in got["answers"]}
    assert by["Yes"]["why"] == ["forgot"] and "why" not in by["No"]
    q = {x["key"]: x for x in got["aggregates"]["questions"]}
    assert q["why"]["n"] == 1


def test_life_facts_drawn_by_age_and_sex():
    import random as _r
    assert registry._band_bounds("20 to 24") == (20, 24) and registry._band_bounds("90 and over")[0] == 90 and registry._band_bounds("75+")[0] == 75
    pf = {"yes": "Y", "no": "N", "by_age_sex": {"female": {"16-24": 0, "25-34": 100}}, "by_age": {"16-44": 50}, "overall": 50}
    assert registry._draw_fact(pf, {"age": 30, "gender": "female"}, _r.Random(1)) == "Y"
    assert registry._draw_fact(pf, {"age": 20, "gender": "female"}, _r.Random(1)) == "N"
    limited = {"yes": "Y", "no": None, "by_age": {"16-65": 100}, "overall": 100, "age_limited": True}
    assert registry._draw_fact(limited, {"age": 80}, _r.Random(1)) is None          # not drawn outside the published ages
    kit = registry.load_kit("britains_choice_2020")
    cards = [c for s in registry.plan_from_kit(kit, 60)["segments"] for c in s["kit_cards"]]
    assert all(c.get("facts") for c in cards)
    seg = kit["segments"][0]
    d = cast.enforce(seg, {**cards[0], "slot": 1}, {"name": "X"})
    assert d["character"]["life_facts"] == cards[0]["facts"] and "Facts of their life" in cast.card_line(cards[0])
