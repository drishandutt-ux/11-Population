"""Population Studio: the parts that decide who ends up in the roster.

Run:  cd backend && pytest tests/population_test.py -q
No network. Covers share/count normalisation (the plan's arithmetic), the model→plan shape,
the dials as prompt text, the per-segment persona prompt, the quant fact chunk, and the HTTP
surface with the model stubbed (start → questions → answer → plan → reject/accept → approve).
"""
import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.population import builder, sources  # noqa: E402
from app.services.agents import agent_factory  # noqa: E402


def _seg(id, share, decision="proposed", **kw):
    d = {"id": id, "name": f"Segment {id}", "share_pct": share, "stance": "neutral", "decision": decision,
         "demographics": {"age_min": 20, "age_max": 60, "gender_female_pct": 50}, "sentiment": {"mood": "mixed", "temperature": 5, "top_emotions": []}}
    d.update(kw)
    return d


# ── normalisation ─────────────────────────────────────────────────────────────

def test_counts_sum_to_total_and_shares_to_100():
    out = builder.normalise_segments([_seg("a", 50), _seg("b", 30), _seg("c", 20)], 33)
    assert sum(s["count"] for s in out) == 33
    assert round(sum(s["share_pct"] for s in out)) == 100
    assert [s["count"] for s in out] == [17, 10, 6] or sum(s["count"] for s in out) == 33


def test_rejected_segment_gets_nothing_and_the_rest_absorb_its_share():
    out = builder.normalise_segments([_seg("a", 50), _seg("b", 30, decision="rejected"), _seg("c", 20)], 40)
    by = {s["id"]: s for s in out}
    assert by["b"]["count"] == 0 and by["b"]["share_pct"] == 30  # the rejected share is left as the model wrote it
    assert by["a"]["count"] + by["c"]["count"] == 40
    assert round(by["a"]["share_pct"] + by["c"]["share_pct"]) == 100
    assert by["a"]["share_pct"] > by["c"]["share_pct"]


def test_rejecting_keeps_the_slot_share_for_its_replacement():
    """Without this, the neighbours absorb the rejected share and the replacement's own share
    is then squeezed on top of a 100% plan (seen as 16.7% for a 20% slot)."""
    out = builder.normalise_segments([_seg("a", 50), _seg("b", 30, decision="rejected"), _seg("c", 20)], 40, rescale_shares=False)
    by = {s["id"]: s for s in out}
    assert (by["a"]["share_pct"], by["c"]["share_pct"]) == (50, 20)
    assert by["a"]["count"] + by["c"]["count"] == 40 and by["a"]["count"] > by["c"]["count"]
    replaced = builder.normalise_segments([by["a"], dict(_seg("b", 30)), by["c"]], 40)
    assert [s["share_pct"] for s in replaced] == [50, 30, 20]


def test_every_kept_segment_gets_at_least_one_agent_when_possible():
    out = builder.normalise_segments([_seg("a", 96), _seg("b", 2), _seg("c", 2)], 10)
    assert all(s["count"] >= 1 for s in out) and sum(s["count"] for s in out) == 10


def test_ages_are_clamped_to_the_population_dial():
    out = builder.normalise_segments([_seg("a", 100, demographics={"age_min": 12, "age_max": 90, "gender_female_pct": 140})], 5,
                                     constraints={"demographics": {"age_min": 25, "age_max": 45}})
    d = out[0]["demographics"]
    assert (d["age_min"], d["age_max"]) == (25, 45)
    assert d["gender_female_pct"] == 100


def test_zero_shares_fall_back_to_an_even_split():
    out = builder.normalise_segments([_seg("a", 0), _seg("b", 0)], 10)
    assert [s["count"] for s in out] == [5, 5]


# ── shapes & prompts ──────────────────────────────────────────────────────────

def test_segment_from_model_nests_demographics_and_sentiment():
    m = {"id": "s1", "name": "Renters", "share_pct": 40, "stance": "direct", "description": "d", "age_min": 22, "age_max": 39,
         "gender_female_pct": 55, "regions": ["Leeds", ""], "income_band": "low", "education": "degree", "occupations": ["nurse"],
         "mood": "against", "temperature": 12, "top_emotions": ["anger"], "arguments": ["too dear"], "evidence": ["42% rent (ONS)"],
         "rationale": "because", "humanity_hint": "defensive"}
    seg = builder.segment_from_model(m)
    assert seg["demographics"]["regions"] == ["Leeds"]
    assert seg["sentiment"]["temperature"] == 10  # clamped
    assert seg["decision"] == "proposed" and seg["stance"] == "direct"
    assert builder.segment_from_model({"stance": "bogus"})["stance"] == "neutral"


def test_constraints_summary_only_states_moved_dials():
    quiet = builder.constraints_summary({"sentiment": {"follow_evidence": True, "temperature": 5}, "stance": {"direct": 33, "indirect": 33, "neutral": 34, "follow_plan": True}})
    assert "Population dials" not in quiet and "follow the evidence" in quiet
    loud = builder.constraints_summary({"demographics": {"age_min": 30, "age_max": 50, "regions": ["Wales"], "income": "low"},
                                        "sentiment": {"follow_evidence": False, "mood": {"for": 20, "against": 70, "mixed": 10}, "price_sensitivity": 9}})
    assert "ages 30-50" in loud and "Wales" in loud and "income: low" in loud
    assert "70% against" in loud and "price sensitivity 9/10" in loud


def test_plan_prompt_pins_the_segment_and_the_dials():
    seg = {"name": "Commuting parents", "description": "who", "stance": "direct", "share_pct": 40,
           "demographics": {"age_min": 28, "age_max": 45, "gender_female_pct": 60, "regions": ["Greater Manchester"], "income_band": "middle", "education": "mixed", "occupations": ["teacher"]},
           "sentiment": {"mood": "for", "temperature": 7, "top_emotions": ["hope", "anxiety"]}, "arguments": ["the bus never comes"], "evidence": ["61% aged 25-44 (ONS)"], "rationale": "r",
           "humanity_hint": "defensive"}
    cons = {"demographics": {"regions": ["Greater Manchester"], "age_min": 25, "age_max": 50}, "sentiment": {"price_sensitivity": 8}}
    p = agent_factory._plan_prompt("Will they use a new tram line?", seg, 10, cons, "KG", "EVIDENCE", [{"name": "A B", "role": "x", "age": 30}])
    assert "Commuting parents" in p and "Ages: 28 to 45" in p and "roughly 60% women" in p
    assert "Register: defensive" in p and "between 60 and 68" in p
    assert "Everyone lives in: Greater Manchester" in p and "price sensitivity: 8/10" in p
    assert '"stance": "direct"' in p and "ALREADY IN THIS POPULATION" in p and "A B" in p
    assert '"gender"' in p and '"region"' in p and "DIALS INSTRUCTIONS" in p


def test_segment_register_sets_the_humanity_band():
    """The segment's humanity_hint IS the humanity dial: an unknown or missing hint falls back
    to tempered, and every persona is clamped into its segment's band whatever the model wrote."""
    assert agent_factory.hint_band("reactive") == (72, 90)
    assert agent_factory.hint_band("Expert") == (0, 15)
    assert agent_factory.hint_band(None) == agent_factory.hint_band("nonsense") == (25, 45)
    lo, hi = agent_factory.HINT_HUMANITY_BANDS["balanced"]
    seg = {"name": "S", "stance": "direct", "humanity_hint": "balanced"}
    dicts = [{"humanity": 0}, {"humanity": 55}, {"humanity": 100}, {"humanity": "bad", "stance": "neutral"}]
    agent_factory.finalise_segment_dicts(seg, dicts)
    assert [d["humanity"] for d in dicts] == [lo, 55, hi, lo]
    assert all(d["stance"] == "direct" and d["_segment"] == "S" for d in dicts)


def test_profile_from_dict_keeps_demographics_and_segment():
    d = {"name": "Priya Nair", "age": 34, "gender": "female", "region": "Salford", "income_band": "middle", "education": "degree",
         "occupation": "nurse", "role": "NHS Nurse", "background": "b", "stance": "direct", "correlation": "c", "personality": ["warm"],
         "debate_style": "d", "humanity": 60, "dials": {"sentiment": {"hope": 8}}}
    p = agent_factory.profile_from_dict(d, "sess", "#fff", segment="Commuting parents")
    assert p.segment == "Commuting parents" and p.demographics["region"] == "Salford" and p.demographics["gender"] == "female"
    assert p.humanity == 60 and p.stance == "direct"
    assert agent_factory.profile_from_dict({"role": "no name"}, "s", "#fff") is None


def test_quant_chunk_and_prompt_carry_the_source():
    class E:
        session_id = "s"; source_ref = "https://ons.gov.uk/x"; author = "ons.gov.uk"; published_at = "2025-03-01"; title = "Cycling in England"
        full_text = None; text = "t"
        structured = {"source_label": "ONS", "facts": [{"statistic": "adults who cycle weekly", "value": "11%", "group": "adults 16+", "geography": "England", "year": "2024", "quote": "q"}], "demographic_signals": ["most are men"]}
    chunk = sources.quant_chunk(E())
    assert chunk.startswith("[SOURCE quant | ONS | https://ons.gov.uk/x | 2025-03-01]")
    assert "adults who cycle weekly: 11%" in chunk
    txt = sources.facts_for_prompt([E()])
    assert "QUANTITATIVE FACTS" in txt and "(ONS)" in txt and "most are men" in txt


def test_default_sources_follow_geography():
    uk = sources.default_sources("United Kingdom")
    assert {"ons", "nomis", "govuk", "fca", "ofcom", "moreincommon", "opinium"} <= set(uk)
    assert "statista" not in uk and "yougov" not in uk  # opt-in: teasers hide the number / headline without crossbreaks
    assert "scot_census" in sources.default_sources("Scotland") and "nisra" in sources.default_sources("Northern Ireland") and "london" in sources.default_sources("London, UK")
    assert "census" in sources.default_sources("United States")
    assert "statista" not in sources.default_sources("") and "oecd" in sources.default_sources("")
    # the question itself is a usable hint: UK regions and cities count as UK, whole words only
    assert "ons" in sources.default_sources("Would parents in the North West pay £12 a month for a kids' bike subscription?")
    assert "ons" in sources.default_sources("Manchester commuters and the tram")
    assert "ons" not in sources.default_sources("Milwaukee brewers in Bukhara")  # 'uk' inside words must not fire


def test_catalogue_entries_are_complete_and_unique():
    keys = [s["key"] for s in sources.QUANT_SOURCES]
    assert len(keys) == len(set(keys))
    for src in sources.QUANT_SOURCES:
        assert src["domain"] and src["label"] and src["description"]
        assert 1 <= int(src["fit"]) <= 5
        assert src["covers"] and set(src["covers"]) <= set(sources.DIMENSIONS)
        assert src["phrasing"]
        if src.get("site"):
            assert src["site"].startswith(src["domain"]), src["key"]  # results are filtered on the domain the site: prefix lives in


def test_route_sources_prefers_named_then_dimension_then_all_ordered_by_fit():
    ticked = ["yougov", "ons", "govuk", "brc"]
    # named publishers that are ticked, best readability first
    assert sources.route_sources(["govuk", "yougov", "pew"], ticked, "income") == ["govuk", "yougov"]
    # nothing named is ticked → every ticked publisher that covers the dimension
    assert sources.route_sources(["pew"], ticked, "income") == ["ons", "govuk"]
    # nobody covers it → all ticked, by fit
    assert sources.route_sources([], ticked, "transport") == ["govuk"]
    assert sources.route_sources([], ticked, "nonsense") == ["ons", "govuk", "yougov", "brc"]


def test_catalogue_for_prompt_teaches_coverage_and_phrasing():
    txt = sources.catalogue_for_prompt(["govuk", "nope"])
    assert "govuk (gov.uk statistics" in txt and "Households below average income" in txt and "covers income" in txt
    assert "nope" not in txt


def test_heuristic_rank_puts_statistics_pages_before_press():
    class R:
        def __init__(self, url, title, snippet=""):
            self.url, self.title, self.snippet = url, title, snippet
    rs = [R("https://www.gov.uk/government/news/minister-hails-cycling", "Minister hails cycling boom"),
          R("https://www.gov.uk/government/statistics/national-travel-survey-2024", "National Travel Survey: 2024", "2% of trips were by bicycle"),
          R("https://www.gov.uk/guidance/cycle-to-work", "Cycle to work scheme guidance")]
    assert sources.heuristic_rank(rs)[0] == 1


# ── quant query decomposition ─────────────────────────────────────────────────

def test_keyword_squeeze_strips_question_scaffolding_prices_and_parentheticals():
    q = "Would London commuters switch to a £65/month e-bike subscription (theft cover and 24-hour swap included) instead of paying for TfL or driving?"
    out = builder.keyword_squeeze(q)
    assert "£" not in out and "(" not in out and "Would" not in out and "?" not in out
    assert "London" in out and "e-bike" in out and len(out.split()) <= 7


def test_looks_like_question_flags_questions_but_not_keyword_queries():
    assert builder.looks_like_question("Would London commuters switch to an e-bike subscription?")
    assert builder.looks_like_question("how many people cycle to work in the UK every single day")  # >7 words
    assert not builder.looks_like_question("London travel to work mode share")
    assert not builder.looks_like_question("")


def test_targets_context_reads_configuration_before_research():
    """The planner must see the analyst's dials, audience profile and upload before the detected
    gaps and the publishers — the order of the prompt is the order of precedence."""
    c = {"demographics": {"age_min": 25, "age_max": 44, "regions": ["North West"]}, "profile_query": "parents of under-5s, mostly renting",
         "doc_context": "respondent,age,town\n1,31,Bolton", "derived_from_research": {"gender": "Census"}}
    d = {"target_population": "parents in the North West", "geography": "United Kingdom", "population_kind": "consumers",
         "segments_hinted": ["renting parents"], "gaps": ["household income of these families"], "confidence": 55,
         "demographic_signals": [{"attribute": "region", "value": "North West", "source": "query"}]}
    txt = builder.targets_context("Would parents pay £12 a month?", ["ons", "govuk"], constraints=c, detected=d, facts_text="QUANTITATIVE FACTS: x", brief_text="EVIDENCE BRIEF: y")
    i_cfg, i_det, i_facts, i_pub = txt.index("ANALYST'S CONFIGURATION"), txt.index("DETECTED FROM THE INPUTS"), txt.index("QUANTITATIVE FACTS"), txt.index("PUBLISHERS TICKED")
    assert i_cfg < i_det < i_facts < i_pub
    assert "ages 25-44" in txt and "parents of under-5s" in txt and "1,31,Bolton" in txt
    assert "do not search for them again): gender" in txt
    assert "GAPS (priority 1): household income of these families" in txt
    assert "Households below average income" in txt  # the publisher's own phrasing reaches the planner


def test_fallback_targets_squeeze_the_question():
    t = builder.fallback_targets("Would London commuters switch to a £65/month e-bike subscription?", ["ons", "govuk"])
    assert len(t) == 1 and "£" not in t[0]["fact"] and t[0]["queries"][0]["sources"] == ["ons", "govuk"]


def test_adhoc_search_plans_targets_about_the_audience(monkeypatch):
    """The Sources-panel box is prefilled with the session question; verbatim it matches nothing
    on any publisher. It must become fact targets about the audience, planned against the
    latest build's configuration, and each target runs through the gathering loop."""
    seen = {}

    async def fake_plan(session_id, question, keys, *, constraints=None, detected=None, facts_text="", brief_text=""):
        seen["constraints"], seen["detected"] = constraints, detected
        return {"audience": "London commuters", "skipped": [],
                "targets": [{"dimension": "transport", "fact": "London travel to work mode share", "why": "w", "priority": 1,
                             "queries": [{"query": "travel to work mode share London", "sources": ["ons"]}]},
                            {"dimension": "consumer", "fact": "UK e-bike ownership", "why": "w", "priority": 2,
                             "queries": [{"query": "e-bike ownership UK", "sources": ["gallup"]}]}]}

    async def fake_gather(session_id, question, targets, keys, **kw):
        seen["targets"], seen["keys"] = targets, keys
        return []

    class B:
        id = "b1"; constraints = {"profile_query": "commuters"}; detected = {"geography": "United Kingdom"}

    async def fake_load(build_id):
        return B()

    async def fake_log(*a, **k):
        return None

    async def fake_facts(session_id, limit=40):
        return []

    monkeypatch.setattr(builder, "plan_quant_targets", fake_plan)
    monkeypatch.setattr(builder, "gather_targets", fake_gather)
    monkeypatch.setattr(builder, "latest_build", fake_load)
    monkeypatch.setattr(builder, "load_quant_facts", fake_facts)
    monkeypatch.setattr(builder, "log", fake_log)

    async def fake_emit(session_id, event):
        return None

    monkeypatch.setattr(builder, "_emit", fake_emit)
    asyncio.new_event_loop().run_until_complete(
        builder.run_quant_search("s1", "Would London commuters switch to a £65/month e-bike subscription?", ["ons", "statista"]))
    assert seen["constraints"] == {"profile_query": "commuters"} and seen["detected"] == {"geography": "United Kingdom"}
    assert [t["fact"] for t in seen["targets"]] == ["London travel to work mode share", "UK e-bike ownership"]
    assert seen["keys"] == ["ons", "statista"]


def test_adhoc_search_runs_a_keyword_query_verbatim(monkeypatch):
    """A terse analyst query is the analyst knowing what they want — one round, no planning."""
    seen = {}

    async def fake_gather(session_id, question, targets, keys, **kw):
        seen["targets"] = targets
        return []

    async def fake_load(build_id):
        return None

    async def fake_emit(session_id, event):
        return None

    async def fail_plan(*a, **k):  # pragma: no cover
        raise AssertionError("must not plan a keyword query")

    monkeypatch.setattr(builder, "plan_quant_targets", fail_plan)
    monkeypatch.setattr(builder, "gather_targets", fake_gather)
    monkeypatch.setattr(builder, "latest_build", fake_load)
    monkeypatch.setattr(builder, "_emit", fake_emit)
    asyncio.new_event_loop().run_until_complete(builder.run_quant_search("s1", "London cycling mode share", ["ons"]))
    assert len(seen["targets"]) == 1
    t = seen["targets"][0]
    assert t["queries"] == [{"query": "London cycling mode share", "sources": ["ons"]}] and t["rounds"] == 1


class _Result:
    def __init__(self, url, title, snippet="", domain=None):
        self.url, self.title, self.snippet = url, title, snippet
        self.domain = domain or url.split("/")[2].replace("www.", "")
        self.provider, self.published_at = "test", None


def _gather_harness(monkeypatch, *, results_by_query, facts_by_url, refine):
    """Stub the search chain, the page reader, the model and the database around gather_target."""
    searched, read, logged = [], [], []

    class Provider:
        async def search(self, q, opts):
            searched.append(q)
            return results_by_query.get(q.split(" site:")[0], [])

    monkeypatch.setattr(sources, "get_search_provider", lambda: Provider())

    class Page:
        def __init__(self, url):
            self.markdown, self.title, self.published_at = f"text of {url}", f"title of {url}", None

    async def fake_fetch(url, query="", browser_fallback=True):
        read.append(url)
        return Page(url)

    monkeypatch.setattr(sources, "fetch_page", fake_fetch)

    async def fake_analyze(schema, system, user, **kw):
        label = kw.get("label")
        if label == "population_triage":
            n = user.count("\n[")
            return {"picks": list(range(n)), "why": "all statistics"}
        if label == "population_facts":
            url = next(u for u in facts_by_url if u in user)
            return facts_by_url[url]
        if label == "population_refine":
            return refine
        raise AssertionError(label)

    monkeypatch.setattr(sources, "analyze", fake_analyze)

    async def fake_seen(session_id):
        return set()

    monkeypatch.setattr(sources, "_seen_urls", fake_seen)

    class FakeDB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add(self, e):
            pass

        async def commit(self):
            pass

        async def refresh(self, e):
            pass

    monkeypatch.setattr(sources.dbm, "AsyncSessionLocal", lambda: FakeDB())

    async def fake_publish(channel, event):
        return None

    monkeypatch.setattr(sources, "publish", fake_publish)
    monkeypatch.setattr(sources, "_ingest_to_graph", lambda e: asyncio.sleep(0))

    async def log(level, message, detail=None):
        logged.append((level, message, detail))

    return searched, read, logged, log


def test_gather_target_refires_with_another_route_when_the_first_round_misses(monkeypatch):
    """Round 1 finds a page with related facts but not the target; the refine step proposes a new
    query on another publisher; round 2 finds the figure and the loop stops."""
    ok = {"relevant": True, "answers_target": False, "relevance": 55, "facts": [{"statistic": "households renting", "value": "19%", "group": "households", "geography": "England", "year": "2023", "quote": "q"}], "demographic_signals": [], "summary": "related"}
    hit = {"relevant": True, "answers_target": True, "relevance": 90, "facts": [{"statistic": "median income NW families", "value": "£31,400", "group": "families", "geography": "North West", "year": "2024", "quote": "q"}], "demographic_signals": [], "summary": "answers"}
    searched, read, logged, log = _gather_harness(
        monkeypatch,
        results_by_query={"household income North West": [_Result("https://www.ons.gov.uk/a", "Housing tenure bulletin")],
                          "Households below average income North West": [_Result("https://www.gov.uk/government/statistics/hbai", "HBAI 2024")]},
        facts_by_url={"https://www.ons.gov.uk/a": ok, "https://www.gov.uk/government/statistics/hbai": hit},
        refine={"queries": [{"query": "Households below average income North West", "sources": ["govuk"]}], "verdict": "use the survey's proper name"},
    )
    target = {"dimension": "income", "fact": "median household income of families in the North West", "why": "income dial untouched", "priority": 1,
              "queries": [{"query": "household income North West", "sources": ["ons"]}]}
    rows = asyncio.new_event_loop().run_until_complete(
        sources.gather_target("s1", "Would parents pay £12?", target, ["ons", "govuk"], log=log, region="uk-en", max_pages=6))
    assert searched == ["household income North West site:ons.gov.uk", "Households below average income North West site:gov.uk/government/statistics"]
    assert read == ["https://www.ons.gov.uk/a", "https://www.gov.uk/government/statistics/hbai"]
    assert [r.on_topic for r in rows] == [True, True]
    assert [(r.structured or {}).get("answers_target") for r in rows] == [False, True]
    assert rows[1].structured["target"]["dimension"] == "income" and rows[1].relevance == 0.9
    assert any(m.startswith("Target found") for _, m, _ in logged)
    assert any("another route" in m for _, m, _ in logged)


def test_gather_target_stops_after_one_round_when_told_to(monkeypatch):
    """A keyword target runs once; an irrelevant page is kept greyed and no refine call is made."""
    miss = {"relevant": True, "answers_target": False, "relevance": 10, "facts": [{"statistic": "x", "value": "3%", "group": "g", "geography": "US", "year": "", "quote": "q"}], "demographic_signals": [], "summary": "wrong country"}
    searched, read, logged, log = _gather_harness(
        monkeypatch,
        results_by_query={"London cycling mode share": [_Result("https://www.ons.gov.uk/b", "Cycling")]},
        facts_by_url={"https://www.ons.gov.uk/b": miss},
        refine={"queries": [{"query": "must not run", "sources": ["ons"]}], "verdict": "no"},
    )
    rows = asyncio.new_event_loop().run_until_complete(
        sources.gather_target("s1", "q", sources.keyword_target("London cycling mode share", ["ons"]), ["ons"], log=log, max_pages=4))
    assert searched == ["London cycling mode share site:ons.gov.uk"] and read == ["https://www.ons.gov.uk/b"]
    assert rows[0].on_topic is False and rows[0].relevance < 0.3  # low relevance to this population → greyed, not used by the plan
    assert any(m.startswith("Target not found") for _, m, _ in logged)


def test_gather_targets_shares_the_page_budget_by_priority(monkeypatch):
    order = []

    async def fake_gather_target(session_id, question, target, keys, **kw):
        order.append((target["fact"], kw["max_pages"]))
        return []

    monkeypatch.setattr(sources, "gather_target", fake_gather_target)
    targets = [{"fact": "b", "priority": 2, "queries": [{"query": "b"}]}, {"fact": "a", "priority": 1, "queries": [{"query": "a"}]}, {"fact": "none", "priority": 1, "queries": []}]
    asyncio.new_event_loop().run_until_complete(sources.gather_targets("s", "q", targets, ["ons"], max_pages=8))
    assert order == [("a", 4), ("b", 8)]  # priority first; unused pages roll over


# ── HTTP surface with the model stubbed ───────────────────────────────────────

@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.core.database as dbm
    from app.core.config import get_settings
    import app.models.report, app.models.preset, app.models.kg, app.models.population  # noqa: F401

    monkeypatch.setattr(get_settings(), "app_supabase_url", "")
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/studio.db")
    Session = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(dbm, "engine", eng)
    monkeypatch.setattr(dbm, "AsyncSessionLocal", Session)
    monkeypatch.setattr(dbm, "_sqlite", True)

    calls: list[str] = []

    async def fake_analyze(schema, system, user, **kw):
        label = kw.get("label", "")
        calls.append(label)
        props = schema.get("properties", {})
        if "target_population" in props:
            return {"topic": "tram line", "decision": "use it", "geography": "United Kingdom", "target_population": "Greater Manchester residents",
                    "population_kind": "citizens", "segments_hinted": ["commuters", "retirees"], "demographic_signals": [{"attribute": "region", "value": "GM", "source": "query"}],
                    "sentiment_signals": ["mostly for"], "gaps": ["fares"], "confidence": 70,
                    "dials": {"age_min": 22, "age_max": 64, "age_skew": "unknown", "female_pct": 52, "regions": ["Greater Manchester"], "urban_rural": "urban",
                              "income": "unknown", "education": "unknown", "for_pct": 55, "against_pct": 25, "temperature": 6, "trust_in_institutions": -1,
                              "price_sensitivity": -1, "tech_savviness": -1, "openness_to_change": -1, "basis": "Census and the consultation"}}
        if "questions" in props:
            return {"questions": [{"id": "q1", "text": "Which boroughs?", "why": "changes the regions", "suggested": ["all ten", "Salford only"], "default": "all ten"}], "note": "can proceed"}
        if "segments" in props:
            return {"segments": [
                {"id": "s1", "name": "Commuters", "share_pct": 60, "stance": "direct", "description": "d", "age_min": 22, "age_max": 55, "gender_female_pct": 50, "regions": ["Manchester"],
                 "income_band": "middle", "education": "mixed", "occupations": ["clerk"], "mood": "for", "temperature": 6, "top_emotions": ["hope"], "arguments": ["a"], "evidence": ["e"], "rationale": "r", "humanity_hint": "tempered"},
                {"id": "s2", "name": "Retirees", "share_pct": 40, "stance": "neutral", "description": "d", "age_min": 65, "age_max": 85, "gender_female_pct": 55, "regions": ["Stockport"],
                 "income_band": "low", "education": "secondary", "occupations": ["retired"], "mood": "mixed", "temperature": 3, "top_emotions": ["nostalgia"], "arguments": ["b"], "evidence": [], "rationale": "r2", "humanity_hint": "balanced"},
            ], "rationale": "two groups", "assumptions": ["fares unknown"], "evidence_coverage": "half evidence"}
        if "humanity_hint" in props:  # single replacement segment
            return {"id": "x", "name": "Students", "share_pct": 40, "stance": "indirect", "description": "d", "age_min": 18, "age_max": 24, "gender_female_pct": 52, "regions": ["Fallowfield"],
                    "income_band": "low", "education": "some college", "occupations": ["student"], "mood": "for", "temperature": 5, "top_emotions": ["curiosity"], "arguments": [], "evidence": [], "rationale": "replaced", "humanity_hint": "reactive"}
        return {}

    monkeypatch.setattr(builder, "analyze", fake_analyze)

    async def fake_generate(session_id, query, segments, constraints, *, mode="fast", evidence_text="", on_progress=None, should_stop=None, on_note=None):
        from app.services.agents.profiles import AgentProfile
        out = []
        for seg in segments:
            for k in range(int(seg["count"])):
                out.append(AgentProfile(id=f"{seg['id']}-{k}", session_id=session_id, name=f"{seg['name']} {k}", age=30 + k, role="r", background="b", stance=seg["stance"],
                                        correlation="c", personality=[], debate_style="d", dials={}, humanity=0, segment=seg["name"], demographics={"gender": "female", "region": "Manchester"}))
            if on_progress:
                await on_progress(seg["name"], int(seg["count"]), int(seg["count"]), len(out))
        return out

    monkeypatch.setattr("app.services.agents.agent_factory.generate_agents_from_plan", fake_generate)

    async def _get_db():
        async with Session() as s:
            yield s

    from fastapi.testclient import TestClient
    from app.main import app
    app.dependency_overrides[dbm.get_db] = _get_db
    with TestClient(app) as c:
        yield c, Session, calls
    app.dependency_overrides.clear()


def _wait(client, sid, until, timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        b = client.get(f"/api/v1/sessions/{sid}/population/builds/latest").json()["build"]
        if b and until(b):
            return b
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting; last status {b and b['status']}")


def test_http_studio_round_trip(api_client):
    client, Session, calls = api_client
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "Will Greater Manchester use a new tram line?", "auto_research": False}).json()["id"]

    # start → detect → clarify (waits for the analyst)
    r = client.post(f"/api/v1/sessions/{sid}/population/builds", json={"mode": "fast", "count": 20, "constraints": {"humanity": 50}, "sources": {"quant": False}})
    assert r.status_code == 200
    b = _wait(client, sid, lambda b: b["status"] == "clarifying")
    assert b["detected"]["geography"] == "United Kingdom"
    assert b["questions"][0]["text"] == "Which boroughs?"
    assert any(e["level"] == "question" for e in b["log"])
    assert "population_detect" in calls and "population_questions" in calls

    # a segment decision before the plan exists is refused
    assert client.post(f"/api/v1/sessions/{sid}/population/builds/{b['id']}/segments/s1", json={"decision": "accept"}).status_code == 409

    # answer → plan → awaiting_review with counts summing to the target
    r = client.post(f"/api/v1/sessions/{sid}/population/builds/{b['id']}/answers", json={"answers": {"q1": "Salford only"}})
    assert r.status_code == 200
    b = _wait(client, sid, lambda b: b["status"] == "awaiting_review")
    segs = b["plan"]["segments"]
    assert [s["count"] for s in segs] == [12, 8]
    assert b["questions"][0]["answer"] == "Salford only"
    assert any("You answered" in e["message"] for e in b["log"])

    # reject one with a reason → a replacement arrives in its slot; accept the other
    r = client.post(f"/api/v1/sessions/{sid}/population/builds/{b['id']}/segments/s2", json={"decision": "reject", "reason": "no retirees near Salford"})
    assert r.status_code == 200
    b = _wait(client, sid, lambda b: any(s.get("replaced") for s in b["plan"]["segments"]))
    new = next(s for s in b["plan"]["segments"] if s["id"] == "s2")
    assert new["name"] == "Students" and new["replaced"] == "Retirees" and new["decision"] == "proposed"
    assert sum(s["count"] for s in b["plan"]["segments"]) == 20
    assert any("no retirees near Salford" in (e.get("detail") or "") for e in b["log"])
    r = client.post(f"/api/v1/sessions/{sid}/population/builds/{b['id']}/segments/s1", json={"decision": "edit", "edits": {"share_pct": 75, "demographics": {"age_max": 40}}})
    s1 = next(s for s in r.json()["plan"]["segments"] if s["id"] == "s1")
    assert s1["decision"] == "edited" and s1["demographics"]["age_max"] == 40 and s1["count"] == 15

    # approve → agents are written from the kept segments, carrying segment + demographics
    r = client.post(f"/api/v1/sessions/{sid}/population/builds/{b['id']}/approve", json={"count": 20})
    assert r.status_code == 200 and r.json()["status"] == "spawning"
    b = _wait(client, sid, lambda b: b["status"] == "complete")
    agents = client.get(f"/api/v1/sessions/{sid}/agents").json()
    assert len(agents) == 20
    assert {a["segment"] for a in agents} == {"Commuters", "Students"}
    assert agents[0]["demographics"]["region"] == "Manchester"
    assert sum(1 for a in agents if a["segment"] == "Commuters") == 15
    assert client.get(f"/api/v1/sessions/{sid}").json()["agent_count"] == 20
    assert any("Population built: 20 agents" in e["message"] for e in b["log"])


def test_http_quant_search_requires_a_query(api_client):
    client, _, _ = api_client
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "q", "auto_research": False}).json()["id"]
    assert client.post(f"/api/v1/sessions/{sid}/population/quant-search", json={"query": "  ", "sources": ["ons"]}).status_code == 400
    cat = client.get("/api/v1/population/sources?geography=United%20Kingdom").json()
    assert "ons" in cat["default"] and any(s["key"] == "statista" for s in cat["sources"])


def test_facts_without_a_number_are_dropped():
    """Seen on prod: Statista's paywalled teaser gave '<redacted>' as the value."""
    kept = sources.usable_facts([
        {"statistic": "e-bike access, men", "value": "<redacted>"},
        {"statistic": "e-bike access, women", "value": "not shown"},
        {"statistic": "car club members", "value": "752,560"},
        {"statistic": "unaware of subscriptions", "value": "78%"},
        {"statistic": "blank", "value": ""},
        "junk",
    ])
    assert [f["value"] for f in kept] == ["752,560", "78%"]


def test_plan_generation_runs_segments_concurrently_and_tags_them(monkeypatch):
    """Segments are independent slices, so they must not queue behind each other: on prod a
    50-agent, 8-segment build took ~1.5 min per segment when they ran one at a time."""
    import time as _t
    from app.core.config import get_settings

    async def fake_rag(session_id):
        return session_id

    async def fake_query(rag, query, mode="hybrid"):
        return "kg"

    monkeypatch.setattr(agent_factory, "get_lightrag", fake_rag)
    monkeypatch.setattr(agent_factory, "query_rag", fake_query)
    monkeypatch.setattr(get_settings(), "spawn_concurrency", 8)
    calls = []

    class _Resp:
        def __init__(self, text): self.content = [type("B", (), {"text": text})()]

    async def fake_create(client, **kw):
        user = kw["messages"][0]["content"]
        seg = "A" if "Name: Seg A" in user else "B"
        n = int(user.split("Create ")[1].split(" ")[0])
        calls.append((seg, _t.monotonic()))
        await asyncio.sleep(0.2)
        import json as _j
        return _Resp(_j.dumps([{"name": f"{seg} person {k} {len(calls)}", "age": 30 + k, "role": f"{seg} role {k} batch {len(calls)}", "background": "b", "stance": "neutral",
                               "correlation": "c", "personality": [], "debate_style": "d", "humanity": 0, "gender": "female", "region": "Bristol", "dials": {}} for k in range(n)]))

    monkeypatch.setattr(agent_factory, "tracked_messages_create", fake_create)
    progress = []

    async def on_progress(name, done_seg, seg_count, done_total):
        progress.append((name, done_seg, seg_count))

    segs = [{"id": "a", "name": "Seg A", "count": 12, "stance": "direct", "demographics": {}, "sentiment": {}},
            {"id": "b", "name": "Seg B", "count": 5, "stance": "neutral", "demographics": {}, "sentiment": {}}]
    t0 = _t.monotonic()
    profiles = asyncio.new_event_loop().run_until_complete(
        agent_factory.generate_agents_from_plan("s", "q", segs, {"humanity": 50, "humanity_coverage": 60}, on_progress=on_progress))
    elapsed = _t.monotonic() - t0
    assert len(profiles) == 17
    assert sum(1 for p in profiles if p.segment == "Seg A") == 12 and all(p.stance == "direct" for p in profiles if p.segment == "Seg A")
    assert profiles[0].demographics["region"] == "Bristol"
    # Two segments' first batches overlap in time: three calls total, two rounds, not three.
    assert elapsed < 0.55, elapsed
    assert ("Seg A", 12, 12) in progress and ("Seg B", 5, 5) in progress


# ── dials from research ───────────────────────────────────────────────────────

def test_detected_dials_fill_only_the_dials_left_on_default():
    analyst = {"demographics": {"age_min": 18, "age_max": 75, "regions": ["Bristol"], "income": "mixed"},
               "sentiment": {"follow_evidence": True, "temperature": 5, "price_sensitivity": 9}}
    detected = {"age_min": 25, "age_max": 54, "age_skew": "younger", "female_pct": 47, "regions": ["Bath"], "urban_rural": "urban",
                "income": "middle", "education": "unknown", "for_pct": 41, "against_pct": 30, "temperature": 6, "trust_in_institutions": -1,
                "price_sensitivity": 3, "tech_savviness": 7, "openness_to_change": -1, "basis": "Census 2021 and the YouGov tracker"}
    c, set_from = builder.apply_detected_dials(analyst, detected)
    d, se = c["demographics"], c["sentiment"]
    assert (d["age_min"], d["age_max"], d["age_skew"]) == (25, 54, "younger")
    assert d["gender"] == {"female": 47, "male": 51, "other": 2}
    assert d["regions"] == ["Bristol"]                       # the analyst named a place — theirs wins
    assert d["urban_rural"] == "urban" and d["income"] == "middle" and "education" not in d
    assert se["follow_evidence"] is False and se["mood"] == {"for": 41, "against": 30, "mixed": 29}
    assert se["temperature"] == 6 and se["tech_savviness"] == 7
    assert se["price_sensitivity"] == 9                       # moved by the analyst — untouched
    assert "trust_in_institutions" not in se and "openness_to_change" not in se
    assert set(set_from) == {"age_range", "age_skew", "gender", "urban_rural", "income", "mood", "temperature", "tech_savviness"}
    assert all(v == "Census 2021 and the YouGov tracker" for v in set_from.values())
    line = builder.dials_log_line(set_from, c)
    assert "ages 25-54" in line and "47% women" in line and "mood 41% for / 30% against" in line


def test_detected_dials_can_be_revised_on_a_later_detect_but_never_over_an_analyst_move():
    first, _ = builder.apply_detected_dials({}, {"age_min": 30, "age_max": 60, "female_pct": 60, "for_pct": -1, "against_pct": -1, "basis": "b"})
    assert first["demographics"]["age_min"] == 30 and "age_range" in first["derived_from_research"]
    second, _ = builder.apply_detected_dials(first, {"age_min": 20, "age_max": 40, "female_pct": -1, "for_pct": -1, "against_pct": -1, "basis": "b2"})
    assert second["demographics"]["age_min"] == 20                     # research-set dials may be revised by research
    assert second["demographics"]["gender"]["female"] == 60            # unknown this time → the earlier value stays
    assert builder.apply_detected_dials({"sentiment": {"temperature": 8}}, {"temperature": 2, "for_pct": -1, "against_pct": -1})[0]["sentiment"]["temperature"] == 8
    assert builder.apply_detected_dials({}, None) == ({}, {})


def test_generation_stops_between_batches_and_keeps_what_was_written(monkeypatch):
    from app.core.config import get_settings

    async def fake_rag(session_id):
        return session_id

    async def fake_query(rag, query, mode="hybrid"):
        return "kg"

    monkeypatch.setattr(agent_factory, "get_lightrag", fake_rag)
    monkeypatch.setattr(agent_factory, "query_rag", fake_query)
    monkeypatch.setattr(get_settings(), "spawn_concurrency", 1)
    flag = {"stop": False}
    calls = {"n": 0}

    class _Resp:
        def __init__(self, text): self.content = [type("B", (), {"text": text})()]

    async def fake_create(client, **kw):
        import json as _j
        calls["n"] += 1
        n = int(kw["messages"][0]["content"].split("Create ")[1].split(" ")[0])
        flag["stop"] = True  # the analyst presses Stop while the first batch is in flight
        return _Resp(_j.dumps([{"name": f"P {calls['n']} {k}", "age": 20 + k, "role": f"r {calls['n']} {k}", "background": "b", "stance": "neutral",
                               "correlation": "c", "personality": [], "debate_style": "d", "humanity": 0, "dials": {}} for k in range(n)]))

    monkeypatch.setattr(agent_factory, "tracked_messages_create", fake_create)
    segs = [{"id": "a", "name": "A", "count": 25, "stance": "neutral", "demographics": {}, "sentiment": {}}]
    profiles = asyncio.new_event_loop().run_until_complete(
        agent_factory.generate_agents_from_plan("s", "q", segs, {}, should_stop=lambda: flag["stop"]))
    assert 0 < len(profiles) <= 10 and calls["n"] == 1   # the first batch is kept, the other two never start


def test_http_stop_during_clarify_plans_with_what_we_have_and_can_be_approved(api_client):
    client, Session, calls = api_client
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "q", "auto_research": False}).json()["id"]
    b = client.post(f"/api/v1/sessions/{sid}/population/builds", json={"mode": "fast", "count": 10, "constraints": {}, "sources": {"quant": False}}).json()
    b = _wait(client, sid, lambda b: b["status"] == "clarifying")
    r = client.post(f"/api/v1/sessions/{sid}/population/builds/{b['id']}/stop")
    assert r.json()["stopped"] is True
    b = _wait(client, sid, lambda b: b["status"] == "awaiting_review")
    assert b["plan"] and sum(s["count"] for s in b["plan"]["segments"]) == 10
    assert any("planning now with what has been gathered" in e["message"] for e in b["log"])
    # the dials detect proposed are on the build, marked as research-set
    assert b["constraints"]["derived_from_research"]
    # a stopped-then-planned build approves like any other
    r = client.post(f"/api/v1/sessions/{sid}/population/builds/{b['id']}/approve", json={})
    assert r.status_code == 200
    b = _wait(client, sid, lambda b: b["status"] == "complete")
    assert len(client.get(f"/api/v1/sessions/{sid}/agents").json()) == 10


def test_startup_marks_interrupted_runs_and_builds(api_client):
    """A redeploy kills in-process tasks; their rows must not claim to be running afterwards
    (prod showed "Research is finishing" for an hour after the task had died)."""
    import asyncio as _a
    from app.models.evidence import ResearchRun
    from app.models.population import PopulationBuild
    from app.core.recovery import recover_interrupted
    client, Session, _ = api_client
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "q", "auto_research": False}).json()["id"]

    async def seed():
        async with Session() as db:
            db.add(ResearchRun(id="r1", session_id=sid, status="finalising", question="q", sources=["web"]))
            db.add(ResearchRun(id="r2", session_id=sid, status="complete", question="q", sources=["web"]))
            db.add(PopulationBuild(id="b1", session_id=sid, status="spawning", plan={"segments": []}, log=[]))
            db.add(PopulationBuild(id="b2", session_id=sid, status="awaiting_review", plan={"segments": []}, log=[]))
            await db.commit()
        return await recover_interrupted()

    counts = _a.new_event_loop().run_until_complete(seed())
    assert counts == {"research_runs": 1, "population_builds": 1}
    st = client.get(f"/api/v1/sessions/{sid}/research").json()
    assert st["run"]["status"] in ("interrupted", "complete")
    b1 = client.get(f"/api/v1/sessions/{sid}/population/builds/b1").json()
    assert b1["status"] == "stopped" and b1["log"][-1]["message"] == "Interrupted by a server restart" and "approved" in b1["log"][-1]["detail"]
    assert client.get(f"/api/v1/sessions/{sid}/population/builds/b2").json()["status"] == "awaiting_review"
    # a stopped build with a plan can still be approved
    assert client.post(f"/api/v1/sessions/{sid}/population/builds/b1/approve", json={}).status_code == 400  # empty plan → nothing to build, but not a 409


def test_segment_from_model_keeps_frame_values():
    seg = builder.segment_from_model({"id": "s1", "name": "X", "share_pct": 50, "stance": "direct", "frame_values": [{"dimension": "work_pattern", "value": "Hybrid"}, {"dimension": "", "value": "x"}, "junk"]})
    assert seg["frame_values"] == {"work_pattern": "Hybrid"}
    assert "frame: work_pattern=Hybrid" in builder.segment_for_prompt(seg)


def test_persona_dict_keeps_frame_and_inherits_segment_cells():
    d = {"name": "A", "age": 30, "gender": "female", "region": "Oxford", "frame": {"work_pattern": "Remote", "": "x"}}
    p = agent_factory.profile_from_dict(d, "s", "#fff", segment="Seg")
    assert p.demographics["frame"] == {"work_pattern": "Remote"}
    dicts = [{"name": "B", "humanity": 30}, {"name": "C", "humanity": 30, "frame": {"work_pattern": "Shift"}}]
    agent_factory.finalise_segment_dicts({"stance": "direct", "name": "Seg", "humanity_hint": "tempered", "frame_values": {"work_pattern": "Hybrid", "age": "30s"}}, dicts)
    assert dicts[0]["frame"] == {"work_pattern": "Hybrid", "age": "30s"}
    assert dicts[1]["frame"] == {"work_pattern": "Shift", "age": "30s"}


def test_voice_dial_instruction_and_summary():
    auto, v = builder.voice_setting({})
    assert (auto, v) == (True, 50)
    assert "auto" in builder.voice_instruction({}) and "voice_value" in builder.voice_instruction({})
    assert "as the real population" in builder.voice_instruction({"voice": {"auto": False, "value": 55}})
    lean_x = builder.voice_instruction({"voice": {"auto": False, "value": 10}})
    assert "leaning expert" in lean_x and "strength 0.8" in lean_x
    lean_r = builder.voice_instruction({"voice": {"auto": False, "value": 90}})
    assert "leaning reactive" in lean_r and "strength 0.8" in lean_r and "no expert segments" in lean_r
    assert builder.voice_setting({"voice": {"auto": False, "value": "999"}}) == (False, 100)
    assert "Expert ↔ Reactive: 20/100" in builder.constraints_summary({"voice": {"auto": False, "value": 20}})
    block = agent_factory._constraints_block({"voice_used": 85})
    assert "ordinary members of the public" in block
    assert "practitioners" in agent_factory._constraints_block({"voice_used": 15})
    assert agent_factory._constraints_block({"voice_used": 52}) == ""
