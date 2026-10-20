"""Working a frame figure out from published parts (services/population/workout.py) and the
publisher registry (sources.registry_for_prompt). Run:  cd backend && pytest tests/workout_test.py -q
No network: the model, the gather loop and the build store are stubbed.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.population import builder, frame, sources, workout  # noqa: E402

INCOME = {"key": "income", "label": "Household income", "attribute": "income", "kind": "demographic", "why": "affordability", "matchable": True, "proxy_attribute": "other"}
STANCE = {"key": "stance", "label": "Trust in doctors", "attribute": "attitude", "kind": "attitudinal", "why": "w", "matchable": False, "proxy_attribute": "education"}
KEYS = [s["key"] for s in sources.QUANT_SOURCES]


class _Row:
    def __init__(self, url, facts, on_topic=True, label="ONS"):
        self.source_ref, self.on_topic, self.author = url, on_topic, "ons.gov.uk"
        self.structured = {"source_label": label, "facts": facts}
        self.text = ""


def _run(coro):
    return asyncio.run(coro)


# ── the registry ─────────────────────────────────────────────────────────────

def test_every_publisher_has_a_registry_entry_and_the_prompt_leads_with_the_dimensions_publishers():
    for src in sources.QUANT_SOURCES:
        assert src["holds"] and src["cannot"] and src["geographies"], src["key"]
        for h in src["holds"]:
            assert h["name"] and h["gives"] and h["geo"] and h["how"], (src["key"], h)
    text = sources.registry_for_prompt(KEYS, "health", full=False)
    first = text.splitlines()[0]
    assert first.startswith("- ") and "health" in first                      # a health publisher first
    assert "Health Survey for England" in text and "does not hold" in text    # holdings and the cannot line
    # Publishers that do not cover the dimension are one line each in compact mode.
    assert "• New car and van registrations" not in text and "smmt (SMMT" in text
    assert "• New car and van registrations" in sources.registry_for_prompt(KEYS)   # full mode lists everything


def test_the_planners_are_shown_the_registry():
    ctx = builder.targets_context("Will Blackpool adults use the drug?", KEYS, constraints={}, detected={"geography": "Blackpool"})
    assert "Labour Market Profile" in ctx and "does not hold" in ctx


# ── the hunt ─────────────────────────────────────────────────────────────────

def _stub(monkeypatch, *, plan, compute, rows):
    calls = {"labels": [], "gather": []}

    async def fake_analyze(schema, system, user, **kw):
        calls["labels"].append(kw.get("label"))
        calls.setdefault("users", []).append(user)
        if kw.get("label") == "population_workout_plan":
            return plan
        if kw.get("label") == "population_workout":
            return compute
        raise AssertionError(kw.get("label"))

    async def fake_gather(session_id, question, targets, keys, **kw):
        calls["gather"].append((targets, keys, kw))
        return rows

    monkeypatch.setattr(workout, "analyze", fake_analyze)
    monkeypatch.setattr(workout, "gather_targets", fake_gather)
    return calls


def test_search_route_gathers_the_components_then_computes_a_worked_out_target(monkeypatch):
    plan = {"route": "search", "method": "apply the regional income bands to the town's households",
            "components": [{"fact": "households in Blackpool", "dimension": "size", "role": "denominator", "queries": [{"query": "Labour Market Profile Blackpool", "sources": ["nomis"]}]},
                           {"fact": "household income bands North West", "dimension": "income", "role": "the pattern to apply", "queries": [{"query": "Households below average income North West", "sources": ["govuk", "ons"]}]}],
            "verdict": "two parts"}
    compute = {"ok": True, "categories": [{"label": "Under £25k", "share_pct": 45}, {"label": "£25k-£50k", "share_pct": 38}, {"label": "Over £50k", "share_pct": 17}],
               "working": "Nomis puts Blackpool at 64,000 households (2023). HBAI gives the North West bands as 45 / 38 / 17 (2023), applied to Blackpool.",
               "components": [{"statistic": "households", "value": "64,000", "source": "Nomis Labour Market Profile", "year": "2023", "url": "https://nomis/x"},
                              {"statistic": "income bands North West", "value": "45% / 38% / 17%", "source": "HBAI", "year": "2023", "url": "https://gov/y"}],
               "geography": "Blackpool (North West pattern applied)", "year": "2023", "confidence": 55, "caveat": "regional bands, not the town's own", "refusal": "",
               "assumptions": ["Blackpool's income bands follow the North West pattern"], "basis": "mostly_published"}
    rows = [_Row("https://nomis/x", [{"statistic": "households", "value": "64,000", "group": "households", "geography": "Blackpool", "year": "2023"}], label="Nomis")]
    calls = _stub(monkeypatch, plan=plan, compute=compute, rows=rows)
    logged = []

    async def log(level, message, detail=None):
        logged.append((level, message))

    tg = _run(workout.work_out_target("s", "Q?", INCOME, "Blackpool", KEYS, [], log=log))
    assert tg["status"] == "worked_out" and tg["provenance"] == "derived_statistic" and len(tg["categories"]) == 3
    assert tg["working"].startswith("Nomis puts") and tg["components"][1]["url"] == "https://gov/y" and tg["confidence"] == 55
    assert tg["source"] == "worked out from Nomis Labour Market Profile; HBAI" and tg["note"] == "regional bands, not the town's own"
    # Flagged as an educated assumption: the assumptions it rests on and how much of it is published travel with it.
    assert tg["assumptions"] == ["Blackpool's income bands follow the North West pattern"] and tg["basis"] == "mostly_published"
    assert any("educated assumption" in m for _, m in logged)
    # The components became fact targets routed to the named publishers plus those covering the dimension, capped.
    targets, keys, kw = calls["gather"][0]
    assert [t["fact"] for t in targets] == ["households in Blackpool", "household income bands North West"] and all(t["rounds"] == 1 for t in targets)
    assert keys[:2] == ["nomis", "govuk"] and len(keys) <= workout.WORKOUT_MAX_PUBLISHERS and kw["max_pages"] == workout.WORKOUT_MAX_PAGES
    # The compute call saw the figures found with their page, and the planner saw the registry.
    assert "64,000" in calls["users"][1] and "https://nomis/x" in calls["users"][1]
    assert "Labour Market Profile" in calls["users"][0] and "does not hold" in calls["users"][0]
    assert any(m.startswith("Worked out · Household income") for _, m in logged)


def test_on_file_route_skips_the_searches_and_none_leaves_the_gap_open(monkeypatch):
    compute = {"ok": True, "categories": [{"label": "Low", "share_pct": 60}, {"label": "High", "share_pct": 40}], "working": "w", "components": [{"statistic": "s", "value": "1", "source": "ONS", "year": "", "url": ""}],
               "geography": "Blackpool", "year": "", "confidence": 40, "caveat": "", "refusal": ""}
    calls = _stub(monkeypatch, plan={"route": "on_file", "method": "m", "components": [], "verdict": "v"}, compute=compute, rows=[])
    tg = _run(workout.work_out_target("s", "Q?", INCOME, "Blackpool", KEYS, []))
    assert tg["status"] == "worked_out" and calls["gather"] == [] and calls["labels"] == ["population_workout_plan", "population_workout"]

    calls = _stub(monkeypatch, plan={"route": "none", "method": "", "components": [], "verdict": "no publisher holds it"}, compute=compute, rows=[])
    tg = _run(workout.work_out_target("s", "Q?", INCOME, "Blackpool", KEYS, []))
    assert tg["status"] == "missing" and "no publisher holds it" in tg["note"] and calls["labels"] == ["population_workout_plan"]


def test_attitudes_are_never_worked_out_and_a_refusal_or_thin_answer_stays_missing(monkeypatch):
    calls = _stub(monkeypatch, plan={"route": "search"}, compute={}, rows=[])
    tg = _run(workout.work_out_target("s", "Q?", STANCE, "Blackpool", KEYS, []))
    assert tg["status"] == "missing" and calls["labels"] == []
    refused = workout.target_from_compute({"ok": False, "refusal": "the denominator was never found", "categories": []}, INCOME, "Blackpool", "m")
    assert refused["status"] == "missing" and "denominator" in refused["note"]
    thin = workout.target_from_compute({"ok": True, "categories": [{"label": "only one", "share_pct": 100}], "working": "w", "components": []}, INCOME, "Blackpool", "m")
    assert thin["status"] == "missing"
    # Leniency is in the prompt: partial parts are enough, refusal only when nothing bears on the dimension.
    assert "BE LENIENT" in workout.COMPUTE_SYSTEM and "ONLY when not one figure" in workout.COMPUTE_SYSTEM
    bare = workout.target_from_compute({"ok": True, "categories": [{"label": "A", "share_pct": 50}, {"label": "B", "share_pct": 50}], "working": "w", "components": []}, INCOME, "Blackpool", "m")
    assert bare["assumptions"] == [] and bare["basis"] == "published"


def test_a_worked_out_target_is_matched_weighted_and_named_in_the_report():
    worked = {"status": "worked_out", "categories": [{"label": "Low", "share_pct": 60}, {"label": "High", "share_pct": 40}], "source": "worked out from HBAI", "year": "2023",
              "geography": "Blackpool", "proxy_attribute": "other", "note": "", "provenance": "derived_statistic", "working": "w", "components": []}
    fr = {"dimensions": [INCOME], "targets": {"income": worked}, "geography": "Blackpool"}
    assert frame.active_targets(fr) == [(INCOME, worked)]
    rep = frame.build_report(fr, [{"id": "s1", "share_pct": 100, "income_band": "low", "frame_values": [{"dimension": "income", "value": "Low"}]}], 10)
    assert rep["worked_out"] == ["income"] and rep["matched_exactly"] == ["income"] and rep["level"] != "none"
    assert "worked out from published figures as educated assumptions: Household income" in frame.summary_line(rep)
    assert frame.proxy_target(fr, "income")["status"] == "proxy"


def test_the_pipeline_works_out_open_gaps_and_saves_what_lands(monkeypatch):
    """Two gaps and one attitude: the hunt runs for the two, saves the one that was worked out, leaves the other missing."""
    state = {"frame": {"dimensions": [INCOME, dict(INCOME, key="age", label="Age", attribute="age"), STANCE],
                       "targets": {"income": frame.skipped_target() | {"status": "missing"}, "age": {"status": "missing", "categories": []}, "stance": {"status": "missing", "categories": []}},
                       "geography": "Blackpool"}}
    bld = SimpleNamespace(id="b1", session_id="s", frame=state["frame"], sources={"quant_sources": ["ons", "nomis"]}, constraints={})

    async def fake_load(build_id):
        return bld

    async def fake_save(build_id, **fields):
        for k, v in fields.items():
            setattr(bld, k, v)
        return bld

    logged = []

    async def fake_log(build_id, stage, level, message, detail=None):
        logged.append((stage, level, message))

    asked = []

    async def fake_work_out(session_id, question, dim, geography, keys, facts_rows, **kw):
        asked.append((dim["key"], keys))
        if dim["key"] == "income":
            return {"status": "worked_out", "categories": [{"label": "Low", "share_pct": 60}, {"label": "High", "share_pct": 40}], "source": "worked out from HBAI", "year": "", "geography": "Blackpool",
                    "proxy_attribute": "other", "note": "", "provenance": "derived_statistic", "working": "w", "components": [], "confidence": 50}
        return workout.missing_target(dim, geography, "no route")

    monkeypatch.setattr(builder, "_load", fake_load)
    monkeypatch.setattr(builder, "_save", fake_save)
    monkeypatch.setattr(builder, "log", fake_log)
    monkeypatch.setattr(builder, "_stopped", lambda build_id: False)
    monkeypatch.setattr(builder.workout_mod, "work_out_target", fake_work_out)
    out = _run(builder._work_out_open_gaps("b1", "Q?", "Blackpool", [], None))
    assert [k for k, _ in asked] == ["income", "age"] and asked[0][1] == ["ons", "nomis"]       # the attitude is left for the ladder
    assert out.frame["targets"]["income"]["status"] == "worked_out" and out.frame["targets"]["age"]["status"] == "missing"
    assert [d["key"] for d in frame.gaps(out.frame)] == ["age", "stance"]
    assert any("working them out from published parts" in m for _, _, m in logged)


def test_concurrent_ladder_saves_keep_both_results_and_the_pipeline_runs_dimensions_in_parallel(monkeypatch):
    """Two actions that each snapshot the frame and save one key must not clobber each other (2026-10-20)."""
    bld = SimpleNamespace(id="b2", session_id="s", plan=None,
                          frame={"dimensions": [INCOME, dict(INCOME, key="age", label="Age", attribute="age")], "targets": {"income": {"status": "missing", "categories": []}, "age": {"status": "missing", "categories": []}}, "geography": "Blackpool"},
                          sources={"quant_sources": ["ons"]}, constraints={})

    async def fake_load(build_id):
        return SimpleNamespace(**{**bld.__dict__, "frame": {**bld.frame, "targets": dict(bld.frame["targets"])}})

    async def fake_save(build_id, **fields):
        await asyncio.sleep(0)            # yield, as the real commit does
        for k, v in fields.items():
            setattr(bld, k, v)
        return bld

    monkeypatch.setattr(builder, "_load", fake_load)
    monkeypatch.setattr(builder, "_save", fake_save)
    monkeypatch.setattr(builder, "_stopped", lambda build_id: False)

    async def fake_log(build_id, stage, level, message, detail=None):
        return None

    monkeypatch.setattr(builder, "log", fake_log)
    started = []

    async def fake_work_out(session_id, question, dim, geography, keys, facts_rows, **kw):
        started.append(dim["key"])
        await asyncio.sleep(0.01)
        return {"status": "worked_out", "categories": [{"label": "A", "share_pct": 50}, {"label": "B", "share_pct": 50}], "source": "w", "year": "", "geography": "Blackpool",
                "proxy_attribute": "other", "note": "", "provenance": "derived_statistic", "working": "w", "components": [], "confidence": 50}

    monkeypatch.setattr(builder.workout_mod, "work_out_target", fake_work_out)

    async def both():
        a = builder._set_frame_target("b2", "income", {"status": "found", "categories": [{"label": "x", "share_pct": 100}]})
        b = builder._set_frame_target("b2", "age", {"status": "found", "categories": [{"label": "y", "share_pct": 100}]})
        await asyncio.gather(a, b)
        return bld.frame["targets"]

    t = _run(both())
    assert t["income"]["status"] == "found" and t["age"]["status"] == "found"
    bld.frame["targets"] = {"income": {"status": "missing", "categories": []}, "age": {"status": "missing", "categories": []}}
    out = _run(builder._work_out_open_gaps("b2", "Q?", "Blackpool", [], None))
    assert sorted(started) == ["age", "income"] and all(v["status"] == "worked_out" for v in out.frame["targets"].values())
