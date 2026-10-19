"""Plan stage: turn the frame into concrete gather actions — web queries and Reddit queries."""
from __future__ import annotations

from typing import Optional

from .frame import frame_for_prompt, today_iso
from .llm import analyze, arr, obj, s

PLAN_SCHEMA = obj({
    "web_queries": arr(s(), "1 to 3 focused web search queries that together cover the question: one for the official/latest status from the responsible body, one for news coverage, one for reaction", 3),
    "state_of_play_queries": arr(s(), "1 or 2 web queries that establish what exists TODAY for this audience: the current operators, services, competitors, prices, schemes and infrastructure the question presupposes, each carrying the current year", 2),
    "web_region": s("Search region code when the question is country-specific: 'uk-en' for the UK, 'us-en' for the US, 'de-de' for Germany, etc. Empty string when not country-specific."),
    "reddit_queries": arr(s(), "2 to 4 DIFFERENT Reddit searches: plain words people use in threads (no hashtags, no operators except an optional 'subreddit:name' prefix when one community obviously owns the topic, e.g. 'subreddit:ukpolitics digital ID')", 4),
    "rationale": s("One sentence on the gathering strategy"),
})


def _system(today: str) -> str:
    return f"""You plan evidence gathering for a research agent that can (1) search the web and read pages, and (2) search public Reddit threads and comments. Produce a compact plan. Prefer fewer, sharper queries.
Today is {today}. "Latest" means relative to today: never put an earlier year into a query unless the question is about that year. Add the current year or "latest" when recency matters, and name the responsible bodies (regulator, government department, company) so official pages rank first.
One or two queries must establish the state of play today — what this audience can already buy or use, who the operators and competitors are, what the infrastructure, prices and rules are now — each carrying the current year. Without them the agent describes a market or a city as it was years ago.
Searches are iterative: the agent re-queries with refinements if the first results miss the subject, so give the strongest first query, not a broad one. Reddit queries aim for coverage: every variant you list will be run, so make them genuinely different angles rather than rewordings.
Query syntax: plain keywords, 4 to 9 words. No quotes, no OR, no parentheses, no lists of outlet names. Do not use site: unless you are certain of the exact domain; naming the body in words (Crown Estate) is safer.
Search by substance, not by label: when the question uses a label that other things share (a round number, a project name, an acronym), at least one query must describe the subject by its responsible body, place, and process instead of the label.
Never rely on an abbreviation or acronym as the identifying term of a query, and never invent one; every query must carry a full proper name or a plain-language phrase people actually type."""


def _first_words(q: str, n_words: int) -> str:
    return " ".join(q.split()[:n_words])


def _dedupe(qs: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for q in qs:
        q = (q or "").strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out


def fallback_plan(question: str) -> dict:
    year = today_iso()[:4]
    state = [f"{_first_words(question, 6)} what is available now {year}"]
    return {"web_queries": [f"{question} {year}"] + state, "state_of_play_queries": state, "web_region": "", "reddit_queries": [_first_words(question, 5)], "rationale": "Heuristic plan (no LLM)."}


async def plan_query(question: str, frame: Optional[dict], session_id: Optional[str] = None) -> dict:
    try:
        p = await analyze(
            PLAN_SCHEMA, _system(today_iso()),
            f"Question: {question}\n" + (f"\nResearch frame (cover EVERY sub-question; use the aliases and places people actually use; keep look-alikes out):\n{frame_for_prompt(frame)}\n" if frame else ""),
            session_id=session_id, label="research_plan", max_tokens=1200,
        )
        web = _dedupe(p.get("web_queries", []))[:3] or fallback_plan(question)["web_queries"][:1]
        # The state-of-play queries run with the others (2026-10-19): the PedalPass run searched for
        # the subscription idea and never for what London commuters can already use today.
        state = _dedupe(p.get("state_of_play_queries", []))[:2] or fallback_plan(question)["state_of_play_queries"]
        web = _dedupe(web + state)[:5]
        reddit = _dedupe(p.get("reddit_queries", []))[:4] or fallback_plan(question)["reddit_queries"]
        return {"web_queries": web, "state_of_play_queries": state, "web_region": (p.get("web_region") or "").strip(), "reddit_queries": reddit, "rationale": p.get("rationale", "")}
    except Exception as e:  # noqa: BLE001
        print(f"[research] plan failed: {type(e).__name__}: {e}")
        return fallback_plan(question)
