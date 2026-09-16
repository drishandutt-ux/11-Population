"""Evidence gathering tests: engine parsers, the plausibility gate, the Reddit reader's filters,
the heuristic judges, graph ranking, and the whole research loop on SQLite with every network
and LLM call mocked.

Run:  cd backend && pytest tests/evidence_test.py -q
"""
import asyncio
import httpx
import os
import sys
import time
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["WEB_QUERY_GAP_MS"] = "0"
os.environ["SEARCH_CHAIN_RETRY_MS"] = "0"

from app.services.evidence.search import provider as prov  # noqa: E402
from app.services.evidence.search import engines  # noqa: E402
from app.services.evidence import reddit as rd  # noqa: E402
from app.services.evidence import judge_social, judge_web, frame as fr  # noqa: E402
from app.services.evidence.search.provider import SearchResult  # noqa: E402


# ── plausibility gate + chain ────────────────────────────────────────────────

def test_query_terms_and_plausibility():
    assert prov.query_terms("Crown Estate English Channel leasing 2026 site:gov.uk") == ["crown", "estate", "english", "channel", "leasing"]
    rs = [SearchResult("Crown Estate leasing round", "https://a", "a", "seabed", "x"), SearchResult("Ransomware tracker", "https://b", "b", "malware", "x")]
    kept = prov.plausible_results("Crown Estate leasing", rs)
    assert [r.url for r in kept] == ["https://a"]


def test_chain_moves_on_and_benches_rate_limited_engine():
    calls = []

    async def failing(q, o):
        calls.append("brave")
        raise RuntimeError("Brave HTTP 429")

    async def good(q, o):
        calls.append("ddg")
        return [SearchResult("Crown Estate leasing", "https://x", "x", "", "duckduckgo")]

    prov._cooling_until.clear()
    chain = prov.chain_of([prov.SearchProvider("brave", failing), prov.SearchProvider("duckduckgo", good)])
    out = asyncio.run(chain.search("Crown Estate leasing", {}))
    assert out[0].provider == "duckduckgo"
    assert prov._cooling_until.get("brave", 0) > time.time()      # benched
    # second query: brave fails fast on the bench, no call made
    asyncio.run(chain.search("Crown Estate leasing", {}))
    assert calls.count("brave") == 1
    prov._cooling_until.clear()


# ── engine parsers (synthetic markup in the shape each engine serves) ───────

def test_parse_ddg():
    html = ('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fpage&amp;rut=1">Example <b>title</b></a>'
            '<a class="result__snippet" href="#">A snippet &amp; more</a>')
    r = engines.parse_ddg_html(html, 5)
    assert r[0].url == "https://example.org/page" and r[0].title == "Example title" and r[0].snippet == "A snippet & more" and r[0].domain == "example.org"


def test_parse_bing_decodes_click_redirect_and_date():
    import base64
    target = base64.urlsafe_b64encode(b"https://news.example.com/story").decode().rstrip("=")
    html = f'<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u=a1{target}&amp;x=1">Story <i>title</i></a></h2><div class="b_caption"><p>30 Apr 2026 · The caption</p></div></li>'
    r = engines.parse_bing_html(html, 5)
    assert r[0].url == "https://news.example.com/story" and r[0].snippet == "The caption" and r[0].published_at.startswith("2026-04-30")


def test_parse_yahoo_decodes_redirect():
    html = '<h3 class="title"><a href="https://r.search.yahoo.com/_ylt=x/RU=https%3a%2f%2fsite.example%2fa/RK=2/RS=y">site.example › a<span>crumb</span>Real title</a><p class="fc-falcon">Snip</p>'
    r = engines.parse_yahoo_html(html, 5)
    assert r[0].url == "https://site.example/a" and "Real title" in r[0].title and r[0].snippet == "Snip"


def test_parse_brave_html():
    html = ('<div class="snippet fdb" data-type="web"><a href="https://brave.example/x">' '<div class="title search-snippet-title" title="Brave title"></div>'
            '<div class="generic-snippet"><div class="content">' '<span class="t-secondary">26 March 2026 - </span>Body text</div></div></a></div>')
    r = engines.parse_brave_html(html, 5)
    assert r[0].url == "https://brave.example/x" and r[0].title == "Brave title" and r[0].snippet == "Body text" and r[0].published_at.startswith("2026-03-26")


# ── Reddit reader ────────────────────────────────────────────────────────────

def test_reddit_split_and_filters():
    assert rd.split_subreddit("subreddit:ukpolitics digital ID") == ("ukpolitics", "digital ID")
    assert rd.split_subreddit("plain words") == (None, "plain words")
    assert rd.junk_post({"title": "x", "author": "AutoModerator", "subreddit": "a"})
    assert rd.junk_post({"title": "x", "author": "bob", "subreddit": "u_bob"})
    assert not rd.junk_post({"title": "Real post", "author": "bob", "subreddit": "Dorset"})
    assert rd.junk_comment({"body": "lol", "author": "a", "score": 100})
    assert rd.junk_comment({"body": "short one liner here", "author": "a", "score": 3})
    assert not rd.junk_comment({"body": "This is a substantive comment with more than eight words in it.", "author": "a", "score": 0})
    p = rd.to_post({"id": "abc", "subreddit": "Dorset", "title": "Wind farm off Portland", "selftext": "Body", "author": "bob", "score": 12, "num_comments": 3, "created_utc": 1_750_000_000, "permalink": "/r/Dorset/comments/abc/x/", "url": "https://i.redd.it/x.png"})
    assert p.external_id == "abc" and p.author == "u/bob" and p.author_title == "r/Dorset" and p.url.startswith("https://www.reddit.com/r/Dorset") and p.image_url


# ── judges (heuristic paths) ─────────────────────────────────────────────────

def test_social_heuristic_judge_scores_and_stale():
    posts = [rd.ReadPost("1", "Crown Estate leasing round in the Channel is a mess", published_at="2026-08-01T00:00:00+00:00"),
             rd.ReadPost("2", "Recipe for banana bread", published_at="2026-08-01T00:00:00+00:00"),
             rd.ReadPost("3", "Crown Estate leasing round from years ago", published_at="2019-01-01T00:00:00+00:00")]
    v = judge_social.heuristic_judge("Crown Estate Channel leasing round", "Crown Estate leasing", posts, 1)
    assert v.verdicts[0].on_topic and not v.verdicts[1].on_topic and not v.verdicts[2].on_topic


def test_freshness_and_stale_before():
    frame = {"time_sensitivity": "recent", "window_start": "2026-06-01", "window_end": ""}
    assert fr.freshness_of("2026-08-01T00:00:00+00:00", frame) == 1.0
    assert fr.freshness_of("2024-01-01T00:00:00+00:00", frame) < 0.5
    assert fr.freshness_of(None, frame) == 0.5
    assert fr.stale_before(frame) == "2026-06-01"
    assert fr.stale_before({"time_sensitivity": "timeless"}) is None


# ── graph ranking ────────────────────────────────────────────────────────────

def test_rank_entities_prefers_focus_and_penalises_synthetic_only():
    from app.services.knowledge_graph.lightrag_service import rank_entities
    kg = {"entities": ["Enterprise SaaS", "Crown Estate", "Dorset Council", "Trading Card Game"],
          "chunks": ["[SOURCE synthetic | paper] Enterprise SaaS and Trading Card Game meta", "[SOURCE web | x] Crown Estate said Dorset Council objected", "[SOURCE web | y] Crown Estate leasing"]}
    ranked = rank_entities(kg, ["crown", "estate", "dorset"], 3)
    assert ranked[0] == "Crown Estate" and "Trading Card Game" not in ranked


# ── structured output helper: schemas are valid JSON Schema and tool_use blocks parse ─

def test_schemas_are_valid_and_analyze_parses_tool_use(monkeypatch):
    import json
    import jsonschema
    from app.services.evidence import llm, frame as frm, plan as pln, judge_web as jw, judge_social as js, brief as br, recommend as rc
    for schema in (frm.FRAME_SCHEMA, pln.PLAN_SCHEMA, jw.SCHEMA, js.SCHEMA, br.BRIEF_SCHEMA, rc.SCHEMA):
        jsonschema.Draft202012Validator.check_schema(schema)

    captured = {}

    async def fake_create(client, *, session_id=None, label="", **kw):
        captured.update(kw)
        block = types.SimpleNamespace(type="tool_use", name="record", input={"web_queries": ["a b c"], "web_region": "", "reddit_queries": ["x"], "rationale": "r"})
        return types.SimpleNamespace(content=[block], stop_reason="tool_use")

    monkeypatch.setattr(llm, "tracked_messages_create", fake_create)
    out = asyncio.run(llm.analyze(pln.PLAN_SCHEMA, "sys", "user", session_id="s", label="t"))
    assert out["web_queries"] == ["a b c"]
    assert captured["tool_choice"] == {"type": "tool", "name": "record"} and captured["tools"][0]["input_schema"] is pln.PLAN_SCHEMA
    assert captured["system"] == "sys" and captured["messages"][0]["content"] == "user"
    jsonschema.validate(out, pln.PLAN_SCHEMA)


def test_coerce_recovers_pseudo_xml_and_wrong_shapes():
    """Production stored a brief whose 'groups' was pseudo-XML text and 'key_facts' a string
    (max_tokens hit mid-structure). coerce() must turn that into the schema's shapes."""
    from app.services.evidence import llm, brief as br
    bad = {
        "summary": "s",
        "key_facts": "22% of catch (reddit)\n£2.1m fund (council)",
        "groups": '\n<item>\n<parameter name="name">Index purists &amp; overlap critics</parameter>\n<parameter name="stance">against</parameter>\n<parameter name="share_pct">40</parameter>\n<parameter name="arguments">overlap</parameter>\n</item>\n<item>\n<parameter name="name">Cash-drag sceptics</parameter>\n<parameter name="stance">mixed</parameter>',
        "overall_for_pct": "35%", "overall_against_pct": None, "gaps": None, "source_mix": 3,
    }
    out = llm.coerce(br.BRIEF_SCHEMA, bad)
    assert out["key_facts"] == ["22% of catch (reddit)", "£2.1m fund (council)"]
    assert [g["name"] for g in out["groups"]] == ["Index purists & overlap critics", "Cash-drag sceptics"]
    assert out["groups"][0]["stance"] == "against" and out["groups"][0]["share_pct"] == 40 and out["groups"][0]["arguments"] == ["overlap"]
    assert out["groups"][1]["stance"] == "mixed" and out["groups"][1]["quotes"] == []
    assert out["overall_for_pct"] == 35 and out["overall_against_pct"] == 0 and out["gaps"] == [] and out["source_mix"] == "3"
    # brief_for_prompt must not crash on the raw broken row either
    assert "Index purists" in br.brief_for_prompt(bad)


def test_analyze_raises_on_truncation(monkeypatch):
    from app.services.evidence import llm, plan as pln

    async def fake_create(client, *, session_id=None, label="", **kw):
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="tool_use", name="record", input={"web_queries": "a"})], stop_reason="max_tokens")
    monkeypatch.setattr(llm, "tracked_messages_create", fake_create)
    with pytest.raises(llm.LlmTruncated):
        asyncio.run(llm.analyze(pln.PLAN_SCHEMA, "s", "u"))


# ── the loop end to end (mocked network + LLM) on SQLite via the API ────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.core.database as dbm
    from app.core import auth as auth_mod
    import app.models.session, app.models.agent, app.models.post, app.models.report, app.models.preset, app.models.kg, app.models.profile, app.models.evidence  # noqa: F401

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setattr(dbm, "engine", eng)
    monkeypatch.setattr(dbm, "AsyncSessionLocal", async_sessionmaker(eng, expire_on_commit=False))
    monkeypatch.setattr(dbm, "_sqlite", True)
    monkeypatch.setattr(auth_mod.get_settings(), "app_supabase_url", "")

    async def _get_db():
        async with dbm.AsyncSessionLocal() as s:
            yield s

    from fastapi.testclient import TestClient
    from app.main import app
    app.dependency_overrides[dbm.get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _mock_pipeline(monkeypatch):
    from app.services.evidence import loop, frame as frame_mod, plan as plan_mod, brief as brief_mod, recommend as rec_mod
    from app.services.evidence import fetch_page as fp

    async def fake_frame(question, session_id=None, context=""):
        return {**fr.fallback_frame(question), "sub_questions": [{"id": "q1", "text": "status", "kind": "status"}, {"id": "q2", "text": "reaction", "kind": "reaction"}], "places": ["Dorset"], "organisations": ["Crown Estate"]}

    async def fake_plan(question, frame, session_id=None):
        return {"web_queries": ["crown estate channel leasing"], "web_region": "uk-en", "reddit_queries": ["subreddit:Dorset wind farm"], "rationale": "test"}

    async def fake_search(q, o):
        return [SearchResult("Crown Estate leasing page", "https://thecrownestate.example/leasing", "thecrownestate.example", "leasing round evidence", "brave_api", "2026-08-01T00:00:00+00:00"),
                SearchResult("Unrelated", "https://other.example/x", "other.example", "crown estate mention", "brave_api")]

    async def fake_fetch(url, query="", browser_fallback=True):
        if "other" in url:
            raise fp.FetchError("Thin page (12 chars)")
        return fp.FetchedPage(url=url, title="Future leasing: our evidence approach", markdown="The Crown Estate will require metocean and grid evidence. " * 20, chars=1000, truncated=False, status=200, kind="html", published_at="2026-08-01T00:00:00+00:00")

    async def fake_judge_web(question, today, tried, items, frame, session_id=None):
        return judge_web.WebVerdict(useful=[0], missing=[], satisfied=True, refined_queries=[], entities=["Crown Estate"], reason="Covered.", covered=["q1"])

    async def fake_reddit(q):
        return [rd.ReadPost("p1", "Wind farm off Portland: the fishing fleet is furious", author="u/a", author_title="r/Dorset", published_at="2026-08-05T00:00:00+00:00", url="https://www.reddit.com/r/Dorset/comments/p1/x/", likes=40, comment_count=12, payload={"title": "Wind farm off Portland", "body": "", "kind": "text"}),
                rd.ReadPost("p2", "Banana bread recipe", author="u/b", author_title="r/Dorset", published_at="2026-08-05T00:00:00+00:00", url="https://www.reddit.com/r/Dorset/comments/p2/y/", payload={"title": "Banana", "body": ""})], "Read 2"

    async def fake_comments(post, n):
        return [rd.SocialComment("u/c", "We lose 22% of our catch to that zone and nobody asked us.", 30, "2026-08-05T00:00:00+00:00")]

    async def fake_judge_posts(question, platform, query, tried, posts, min_on_topic, **kw):
        return judge_social.JudgeResult([judge_social.PostVerdict(0.9, True), judge_social.PostVerdict(0.0, False)], 1, True, None, "One on-topic.", "test")

    async def fake_insert(rag, chunks):
        return ["Portland fishing fleet"], [["Fishing fleet", "opposes", "wind farm"]]

    async def fake_analyze(schema, system, user, **kw):
        if "recommend which quantitative instruments" not in system:
            return {"summary": "Fishing communities oppose; the Crown Estate wants evidence.", "key_facts": ["22% of catch from the zone (reddit)"], "groups": [{"name": "Fishing cooperative", "stance": "against", "share_pct": 60, "arguments": ["22% of catch lost"], "quotes": ["nobody asked us (r/Dorset)"], "signals": ["Dorset"]}], "overall_for_pct": 20, "overall_against_pct": 60, "overall_mixed_pct": 20, "gaps": ["grid timetable"], "source_mix": ""}
        return {"recommendations": [{"tool": "debate", "confidence": 0.9, "reason": "controversy", "spec_summary": "run it", "variants": [], "price_anchors": [], "segments": ["Fishing cooperative"], "attributes": []},
                                    {"tool": "ab_experiment", "confidence": 0.7, "reason": "two approaches compared", "spec_summary": "A vs B", "variants": ["industry-led", "Crown Estate-led"], "price_anchors": [], "segments": [], "attributes": []}]}

    monkeypatch.setattr(loop, "build_frame", fake_frame)
    monkeypatch.setattr(loop, "plan_query", fake_plan)
    monkeypatch.setattr(loop, "get_search_provider", lambda: prov.SearchProvider("brave_api", fake_search, composite=True))
    monkeypatch.setattr(loop, "fetch_page", fake_fetch)
    monkeypatch.setattr(loop, "judge_web", fake_judge_web)
    monkeypatch.setattr(loop, "search_reddit", fake_reddit)
    monkeypatch.setattr(loop, "reddit_comments", fake_comments)
    monkeypatch.setattr(loop, "judge_posts", fake_judge_posts)
    monkeypatch.setattr("app.services.knowledge_graph.lightrag_service.insert_chunks", fake_insert)
    monkeypatch.setattr(brief_mod, "analyze", fake_analyze)
    monkeypatch.setattr(rec_mod, "analyze", fake_analyze)


def test_research_loop_end_to_end(client, monkeypatch):
    _mock_pipeline(monkeypatch)
    r = client.post("/api/v1/sessions", json={"title": "t", "query": "What evidence does the Crown Estate need for a Channel leasing round?", "auto_research": True})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    state = None
    for _ in range(100):
        state = client.get(f"/api/v1/sessions/{sid}/research").json()
        if state["run"] and state["run"]["status"] in ("complete", "stopped", "error"):
            break
        time.sleep(0.1)
    assert state["run"]["status"] == "complete", state["run"]
    run = state["run"]
    assert run["frame"]["sub_questions"][0]["id"] == "q1" and run["plan"]["web_queries"] == ["crown estate channel leasing"]
    assert run["covered"] == ["q1"]
    assert {q["source"] for q in state["queries"]} == {"web", "reddit"}
    assert all(q["status"] == "done" for q in state["queries"])
    assert state["counts"]["web"] == {"read": 2, "on_topic": 1}
    assert state["counts"]["social"] == {"read": 2, "on_topic": 1}
    assert run["budget"]["pages"] == 1 and run["budget"]["queries"] == 2
    # Evidence rows: the thin page kept as a snippet, off-topic kept but flagged, comments attached
    ev = client.get(f"/api/v1/sessions/{sid}/evidence").json()
    assert len(ev) == 4
    web_on = [e for e in ev if e["source_class"] == "web" and e["on_topic"]]
    assert web_on[0]["title"] == "Future leasing: our evidence approach" and web_on[0]["structured"]["fetched"] is True
    social_on = [e for e in ev if e["source_class"] == "social" and e["on_topic"]]
    assert social_on[0]["structured"]["public_comments"][0]["likes"] == 30
    # Brief + recommendations
    assert run["brief"]["groups"][0]["name"] == "Fishing cooperative"
    recs = client.get(f"/api/v1/sessions/{sid}/recommendations").json()["recommendations"]
    assert recs[0]["tool"] == "debate" and recs[1]["variants"] == ["industry-led", "Crown Estate-led"]
    assert client.get(f"/api/v1/sessions/{sid}/evidence/brief").json()["brief"]["overall_against_pct"] == 60
    # Exclude an item
    eid = ev[0]["id"]
    assert client.post(f"/api/v1/sessions/{sid}/evidence/{eid}/exclude", json={"excluded": True}).json()["excluded"] is True
    # Stop on a run that already finished is a no-op
    assert client.post(f"/api/v1/sessions/{sid}/research/stop").json()["stopped"] is False


def test_stop_mid_run_still_builds_brief(client, monkeypatch):
    """Stop while the Reddit attempt is fetching comments: the run ends 'stopped', keeps what it
    gathered, and still produces a brief + recommendations for persona formation."""
    _mock_pipeline(monkeypatch)
    from app.services.evidence import loop
    stopped_during_comments = {"n": 0}

    async def slow_comments(post, n):
        stopped_during_comments["n"] += 1
        await asyncio.sleep(0.3)
        return [rd.SocialComment("u/c", "We lose 22% of our catch to that zone and nobody asked us.", 30, "2026-08-05T00:00:00+00:00")]

    async def many_posts(q):
        return [rd.ReadPost(f"p{i}", f"Wind farm off Portland thread {i}", author="u/a", author_title="r/Dorset", published_at="2026-08-05T00:00:00+00:00", url=f"https://www.reddit.com/r/Dorset/comments/p{i}/x/", likes=40, comment_count=12, payload={"title": "Wind farm", "body": "", "kind": "text"}) for i in range(6)], "Read 6"

    async def all_on_topic(question, platform, query, tried, posts, min_on_topic, **kw):
        return judge_social.JudgeResult([judge_social.PostVerdict(0.9, True) for _ in posts], len(posts), False, "refined query", "ok", "test")

    monkeypatch.setattr(loop, "reddit_comments", slow_comments)
    monkeypatch.setattr(loop, "search_reddit", many_posts)
    monkeypatch.setattr(loop, "judge_posts", all_on_topic)
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "q", "auto_research": True}).json()["id"]
    time.sleep(0.5)                                   # first comment fetch is in flight
    r = client.post(f"/api/v1/sessions/{sid}/research/stop").json()
    assert r["stopped"] is True
    state = None
    for _ in range(100):
        state = client.get(f"/api/v1/sessions/{sid}/research").json()
        if state["run"]["status"] in ("stopped", "complete", "error"):
            break
        time.sleep(0.1)
    assert state["run"]["status"] == "stopped" and state["run"]["note"] == "stopped by user"
    assert stopped_during_comments["n"] < 6                       # comment fetching was cut short
    assert state["run"]["brief"]["groups"][0]["name"] == "Fishing cooperative"   # brief still built
    assert state["run"]["recommendations"][0]["tool"] == "debate"
    assert state["counts"]["social"]["on_topic"] == 6             # gathered posts kept


def test_recommender_tolerates_malformed_model_output(monkeypatch):
    from app.services.evidence import recommend as rc

    async def fake(schema, system, user, **kw):
        return {"recommendations": ["debate", {"tool": "ab_experiment", "confidence": 0.8, "reason": "r", "spec_summary": "s", "variants": "A vs B", "price_anchors": None, "segments": [1, 2], "attributes": []}, {"tool": "nope"}]}
    monkeypatch.setattr(rc, "analyze", fake)
    recs = asyncio.run(rc.recommend_tools("s", "q", None, None))
    assert [r["tool"] for r in recs] == ["ab_experiment"] and recs[0]["variants"] == ["A vs B"] and recs[0]["segments"] == ["1", "2"]


def test_session_without_auto_research_starts_nothing(client, monkeypatch):
    _mock_pipeline(monkeypatch)
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "q", "auto_research": False}).json()["id"]
    assert client.get(f"/api/v1/sessions/{sid}/research").json()["run"] is None


def test_stop_finalises_an_orphan_run_whose_task_died(client, monkeypatch):
    """A restart kills the research task but leaves the row saying 'stopping'/'running'; Stop used
    to be a silent no-op forever (prod: 100 clicks, still 'stopping'). Now it lands the row."""
    _mock_pipeline(monkeypatch)
    from app.services.evidence import loop
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "q", "auto_research": False}).json()["id"]
    import app.core.database as dbm
    from app.models.evidence import ResearchRun

    async def seed():
        async with dbm.AsyncSessionLocal() as db:
            db.add(ResearchRun(id="orphan1", session_id=sid, status="stopping", question="q", sources=["web"]))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(seed())
    assert "orphan1" not in loop._tasks
    r = client.post(f"/api/v1/sessions/{sid}/research/stop").json()
    assert r == {"stopped": True, "run_id": "orphan1"}
    state = client.get(f"/api/v1/sessions/{sid}/research").json()
    assert state["run"]["status"] == "stopped" and "no longer running" in state["run"]["note"]
    # and a further stop is a clean no-op
    assert client.post(f"/api/v1/sessions/{sid}/research/stop").json()["stopped"] is False


def test_second_stop_press_force_cancels_a_stuck_step(client, monkeypatch):
    """The polite flag is only read between steps; if a step hangs, the second Stop press must
    cancel the task outright and land the run as 'stopped'."""
    _mock_pipeline(monkeypatch)
    from app.services.evidence import loop

    async def hanging_comments(post, n):
        await asyncio.sleep(30)   # a step that ignores the stop flag
        return []

    async def many_posts(q):
        return [rd.ReadPost("p1", "Wind farm off Portland", author="u/a", author_title="r/Dorset", published_at="2026-08-05T00:00:00+00:00", url="https://www.reddit.com/r/Dorset/comments/p1/x/", likes=40, comment_count=12, payload={"title": "Wind farm", "body": "", "kind": "text"})], "Read 1"

    async def on_topic(question, platform, query, tried, posts, min_on_topic, **kw):
        return judge_social.JudgeResult([judge_social.PostVerdict(0.9, True) for _ in posts], len(posts), False, None, "ok", "test")

    monkeypatch.setattr(loop, "reddit_comments", hanging_comments)
    monkeypatch.setattr(loop, "search_reddit", many_posts)
    monkeypatch.setattr(loop, "judge_posts", on_topic)
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "q", "auto_research": True}).json()["id"]
    time.sleep(0.6)                                     # the comment fetch is now hanging
    assert client.post(f"/api/v1/sessions/{sid}/research/stop").json()["stopped"] is True   # polite
    assert client.post(f"/api/v1/sessions/{sid}/research/stop").json()["stopped"] is True   # force
    state = None
    for _ in range(50):
        state = client.get(f"/api/v1/sessions/{sid}/research").json()
        if state["run"]["status"] in ("stopped", "error"):
            break
        time.sleep(0.1)
    assert state["run"]["status"] == "stopped" and state["run"]["note"] == "force-stopped by user"


# ── Anthropic web search engine + Bing "no results" guard (2026-09-16) ─────

def test_parse_anthropic_search_takes_hits_from_tool_result_and_snippets_from_text():
    class B:  # SDK-style object blocks
        def __init__(self, **kw): self.__dict__.update(kw)
    content = [
        B(type="server_tool_use", name="web_search", input={"query": "x"}),
        B(type="web_search_tool_result", content=[
            B(type="web_search_result", url="https://www.nomisweb.co.uk/reports/lmp/la/1946157257/report.aspx", title="Labour Market Profile - Nomis", page_age="2026-03-01", encrypted_content="…"),
            B(type="web_search_result", url="https://www.nomisweb.co.uk/reports/lmp/la/1946157257/report.aspx", title="dup", page_age=None, encrypted_content="…"),
            {"type": "web_search_result", "url": "https://www.ons.gov.uk/x", "title": "ONS page", "page_age": None},
        ]),
        B(type="text", text='Here you go:\n[{"url": "https://www.nomisweb.co.uk/reports/lmp/la/1946157257/report.aspx", "title": "LMP", "snippet": "Employment by occupation for London."}]'),
    ]
    r = engines.parse_anthropic_search(content, 5)
    assert [x.domain for x in r] == ["nomisweb.co.uk", "ons.gov.uk"]
    assert r[0].snippet == "Employment by occupation for London." and r[0].provider == "anthropic" and r[0].published_at.startswith("2026-03-01")
    assert r[1].snippet == "" and r[1].title == "ONS page"
    # the gate keeps them: domain/title share terms with a site: query
    assert len(prov.plausible_results("Labour Market Profile London site:nomisweb.co.uk", r)) == 1


def test_parse_anthropic_search_raises_on_tool_error_so_the_chain_benches_it():
    content = [{"type": "web_search_tool_result", "content": {"type": "web_search_tool_result_error", "error_code": "too_many_requests"}}]
    with pytest.raises(RuntimeError) as e:
        engines.parse_anthropic_search(content, 5)
    assert prov.is_rate_limit(e.value)
    assert engines.parse_anthropic_search([{"type": "text", "text": "no search happened"}], 5) == []


def test_web_search_tool_type_by_model():
    assert engines.web_search_tool_type("claude-haiku-4-5-20251001") == "web_search_20250305"
    assert engines.web_search_tool_type("claude-sonnet-4-6") == "web_search_20260209"
    assert engines.web_search_tool_type("claude-opus-5") == "web_search_20260209"


def test_bing_no_results_block_is_not_an_answer():
    html = '<ol id="b_results"><li class="b_no"><h1>There are no results for <strong>x</strong></h1></li><li class="b_algo"><h2><a href="https://labour.org.uk/">The Labour Party</a></h2></li></ol>'
    assert engines.bing_says_no_results(html)
    assert not engines.bing_says_no_results('<li class="b_algo"><h2><a href="https://a">A</a></h2></li>')


def test_anthropic_engine_joins_the_chain_after_keyed_apis_and_before_keyless(monkeypatch):
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("SEARCH_DISABLE", "")
    built = []
    monkeypatch.setattr(engines, "build", lambda name: (built.append(name), prov.SearchProvider(name, None))[1])
    monkeypatch.setattr(prov, "_anthropic_key", lambda: "sk-test")
    prov.get_search_provider()
    assert built == ["anthropic", "duckduckgo", "bing", "yahoo", "brave"]
    assert prov.has_keyed_engine()
    monkeypatch.setenv("SEARCH_DISABLE", "anthropic")
    built.clear()
    prov.get_search_provider()
    assert built[0] == "duckduckgo" and not prov.has_keyed_engine()
    monkeypatch.setattr(prov, "_anthropic_key", lambda: "")
    monkeypatch.setenv("SEARCH_DISABLE", "")
    assert not prov.has_keyed_engine()


def test_anthropic_engine_calls_claude_with_the_web_search_tool(monkeypatch):
    seen = {}

    async def fake_create(client, *, label="", **kw):
        seen.update(kw); seen["label"] = label
        class R: content = [{"type": "web_search_tool_result", "content": [{"type": "web_search_result", "url": "https://www.ons.gov.uk/a", "title": "ONS a", "page_age": None}]}, {"type": "text", "text": '[{"url":"https://www.ons.gov.uk/a","snippet":"Share of X."}]'}]
        return R()

    import app.core.monitoring as mon
    import app.core.config as cfg
    monkeypatch.setattr(mon, "tracked_messages_create", fake_create)
    monkeypatch.setattr(cfg, "get_settings", lambda: type("S", (), {"anthropic_api_key": "sk-test", "model_fast": "claude-haiku-4-5-20251001"})())
    r = asyncio.run(engines.build("anthropic").search("ONS a site:ons.gov.uk", {"max_results": 5, "region": "uk-en"}))
    assert r[0].url == "https://www.ons.gov.uk/a" and r[0].snippet == "Share of X."
    assert seen["label"] == "search" and seen["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1, "user_location": {"type": "approximate", "country": "GB"}}]
    assert seen["messages"] == [{"role": "user", "content": "ONS a site:ons.gov.uk"}]


# ── Tavily: rate-limited client, site: → include_domains, extract fallback (2026-09-16) ──
from app.services.evidence import tavily  # noqa: E402
from app.services.evidence import fetch_page as fp  # noqa: E402


def test_tavily_limiter_paces_the_101st_request_into_the_next_minute():
    t = {"now": 0.0}
    slept = []

    async def fake_sleep(d):
        slept.append(d); t["now"] += d

    lim = tavily.RateLimiter(100, clock=lambda: t["now"], sleep=fake_sleep)

    async def run():
        for _ in range(100):
            assert await lim.acquire() == 0.0
        assert lim.in_window() == 100
        w = await lim.acquire()              # 101st: must wait until the first slot is 60 s old
        assert w > 0 and t["now"] >= 60.0 and lim.in_window() <= 100
        t["now"] += 61
        assert await lim.acquire() == 0.0    # a minute later, free again
    asyncio.run(run())
    assert slept and all(d > 0 for d in slept)


def test_tavily_limiter_serialises_concurrent_callers():
    t = {"now": 0.0}

    async def fake_sleep(d):
        t["now"] += d
        await asyncio.sleep(0)

    lim = tavily.RateLimiter(3, clock=lambda: t["now"], sleep=fake_sleep)

    async def run():
        waits = await asyncio.gather(*(lim.acquire() for _ in range(5)))
        # FIFO under the lock: three free slots, the fourth waits a full window (the fake clock
        # jumps a minute, which frees the window again), the fifth is then free
        assert waits.count(0.0) == 4 and sum(1 for w in waits if w > 0) == 1 and lim.in_window() <= 3
    asyncio.run(run())


def test_tavily_search_payload_turns_site_operator_into_domain_filter(monkeypatch):
    monkeypatch.delenv("TAVILY_SEARCH_DEPTH", raising=False)
    p = tavily.search_payload("Labour Market Profile London site:nomisweb.co.uk", {"max_results": 5, "region": "uk-en"})
    assert p["query"] == "Labour Market Profile London" and p["include_domains"] == ["nomisweb.co.uk"] and p["include_domains_mode"] == "filter"
    assert p["search_depth"] == "advanced" and p["country"] == "united kingdom" and p["max_results"] == 5 and p["chunks_per_source"] == 3
    p2 = tavily.search_payload("Census 2021 working from home site:gov.uk/government/statistics", {"max_results": 30})
    assert p2["include_domains"] == ["gov.uk"] and "government statistics" in p2["query"] and p2["max_results"] == 20
    p3 = tavily.search_payload("Crown Estate leasing round 2026", {"region": "us-en"})
    assert "include_domains" not in p3 and p3["search_depth"] == "basic" and p3["country"] == "united states"
    monkeypatch.setenv("TAVILY_SEARCH_DEPTH", "basic")
    assert tavily.search_payload("x site:ons.gov.uk", {})["search_depth"] == "basic"


def test_tavily_parse_search_and_engine_wiring(monkeypatch):
    calls = []

    async def fake_post(path, payload, **kw):
        calls.append((path, payload))
        return {"results": [{"url": "https://www.ons.gov.uk/a", "title": "A", "content": "Share of X was 42%.", "published_date": "2026-03-01"},
                            {"url": "https://www.ons.gov.uk/a", "title": "dup", "content": ""}, {"url": "mailto:x", "title": "bad"}]}
    monkeypatch.setattr(tavily, "post", fake_post)
    r = asyncio.run(engines.build("tavily").search("share of X site:ons.gov.uk", {"max_results": 5}))
    assert len(r) == 1 and r[0].provider == "tavily" and r[0].snippet == "Share of X was 42%." and r[0].published_at == "2026-03-01"
    assert calls[0][0] == "/search" and calls[0][1]["include_domains"] == ["ons.gov.uk"]


def test_tavily_post_honours_retry_after_then_raises_rate_limit(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    responses = [httpx.Response(429, headers={"retry-after": "2"}, text="slow down"), httpx.Response(429, headers={"retry-after": "2"}, text="slow down")]
    slept = []

    async def fake_sleep(d):
        slept.append(d)

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return responses.pop(0)

    monkeypatch.setattr(tavily.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(tavily.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(tavily, "limiter", tavily.RateLimiter(100, clock=lambda: 0.0, sleep=fake_sleep))
    with pytest.raises(RuntimeError) as e:
        asyncio.run(tavily.post("/search", {"query": "x"}))
    assert prov.is_rate_limit(e.value) and slept == [2.0]


def test_fetch_page_falls_back_to_tavily_extract_before_the_browser(monkeypatch):
    async def plain_403(url, query=""):
        raise fp.FetchError("HTTP 403")

    async def fake_extract(urls, *, query="", depth="advanced", fmt="markdown"):
        assert urls == ["https://www.ons.gov.uk/x"] and depth == "advanced" and query
        return {urls[0]: "# Employment by occupation\n\n" + "London had 4.5 million jobs in 2025. " * 30}, {}

    async def no_browser(url):
        raise AssertionError("browser must not run when Tavily extracted the page")

    monkeypatch.setattr(fp, "fetch_plain", plain_403)
    monkeypatch.setattr(fp, "fetch_with_browser", no_browser)
    monkeypatch.setattr(tavily, "configured", lambda: True)
    monkeypatch.setattr(tavily, "extract", fake_extract)
    page = asyncio.run(fp.fetch_page("https://www.ons.gov.uk/x", "jobs by occupation London"))
    assert page.title == "Employment by occupation" and page.chars > 400 and page.kind == "html"

    # without a key the old path (straight to the browser) is unchanged
    monkeypatch.setattr(tavily, "configured", lambda: False)
    async def browser_ok(url):
        return fp.FetchedPage(url=url, title="B", markdown="x" * 500, chars=500, truncated=False, status=200, kind="html")
    monkeypatch.setattr(fp, "fetch_with_browser", browser_ok)
    assert asyncio.run(fp.fetch_page("https://www.ons.gov.uk/x")).title == "B"
