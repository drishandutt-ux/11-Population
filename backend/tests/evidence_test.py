"""Evidence gathering tests: engine parsers, the plausibility gate, the Reddit reader's filters,
the heuristic judges, graph ranking, and the whole research loop on SQLite with every network
and LLM call mocked.

Run:  cd backend && pytest tests/evidence_test.py -q
"""
import asyncio
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


def test_session_without_auto_research_starts_nothing(client, monkeypatch):
    _mock_pipeline(monkeypatch)
    sid = client.post("/api/v1/sessions", json={"title": "t", "query": "q", "auto_research": False}).json()["id"]
    assert client.get(f"/api/v1/sessions/{sid}/research").json()["run"] is None
