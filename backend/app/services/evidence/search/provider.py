"""Web search providers behind one interface, walked as one chain: a query is answered by the
first engine that returns plausible results. Keyed APIs (Brave API, Tavily) when their key is
set, then Claude's server-side web search (keyed by ANTHROPIC_API_KEY, so production always has
it), then the keyless HTML engines (DuckDuckGo, Bing, Yahoo, Brave). When every engine fails the
whole chain retries once after a pause.

Decisions carried over from SuperMind (each cost an afternoon):
  * Bench, don't retry: after a 429/captcha an engine is benched (120 s scraped, 15 s keyed)
    so a locked-out engine fails fast and the chain moves on.
  * A chain never carries a member's name: cooldowns apply to members, never to the chain.
  * Plausibility gate: a result counts only if its title/snippet/domain shares a term with
    the query; scraped engines under bot pressure return unrelated pages.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse

ProviderName = str  # brave_api | tavily | anthropic | brave | duckduckgo | yahoo | bing


@dataclass
class SearchResult:
    title: str
    url: str
    domain: str
    snippet: str
    provider: str = ""
    published_at: Optional[str] = None


@dataclass
class SearchProvider:
    name: str
    search: Callable[[str, dict], Awaitable[list[SearchResult]]]
    composite: bool = False


#: Spend cap (2026-11-13): a session may run at most this many web searches in any rolling
#: SEARCH_CAP_WINDOW_MIN minutes — about one build's worth. A population build fans every query
#: out to each publisher and ran 330–700 paid searches (~$8–17) per build before the cap; past it
#: a search fails at once and the build carries on with what it found. 0 turns the cap off.
SEARCH_CAP_PER_BUILD = int(os.environ.get("SEARCH_CAP_PER_BUILD", 150))
SEARCH_CAP_WINDOW_MIN = int(os.environ.get("SEARCH_CAP_WINDOW_MIN", 60))
_searches_by_session: dict[str, list[float]] = {}


class SearchBudgetSpent(RuntimeError):
    """The session has used its web searches for this window."""


def _take_search() -> None:
    """Count one search against the current session, or raise SearchBudgetSpent."""
    if SEARCH_CAP_PER_BUILD <= 0:
        return
    try:
        from app.core.monitoring import current_session_id
        key = current_session_id.get() or "none"
    except Exception:  # noqa: BLE001
        key = "none"
    now = time.time()
    recent = [t for t in _searches_by_session.get(key, []) if now - t < SEARCH_CAP_WINDOW_MIN * 60]
    if len(recent) >= SEARCH_CAP_PER_BUILD:
        _searches_by_session[key] = recent
        raise SearchBudgetSpent(f"search limit reached ({SEARCH_CAP_PER_BUILD} web searches per {SEARCH_CAP_WINDOW_MIN} min for this session)")
    recent.append(now)
    _searches_by_session[key] = recent


def searches_used(session_id: Optional[str]) -> int:
    now = time.time()
    return len([t for t in _searches_by_session.get(session_id or "none", []) if now - t < SEARCH_CAP_WINDOW_MIN * 60])


COOLDOWN_MS = int(os.environ.get("SEARCH_COOLDOWN_MS", 120_000))
API_COOLDOWN_MS = int(os.environ.get("SEARCH_API_COOLDOWN_MS", 15_000))
CHAIN_RETRY_MS = int(os.environ.get("SEARCH_CHAIN_RETRY_MS", 10_000))
API_PROVIDERS = {"brave_api", "tavily", "anthropic"}
_cooling_until: dict[str, float] = {}

_RATE_LIMIT_RE = re.compile(r"429|rate.?limit|captcha|challenged", re.I)


def is_rate_limit(e: BaseException) -> bool:
    return bool(_RATE_LIMIT_RE.search(str(e)))


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).hostname or url
        return host[4:] if host.startswith("www.") else host
    except Exception:  # noqa: BLE001
        return url


STOPWORDS = {"the", "and", "for", "with", "from", "that", "this", "what", "which", "when", "where", "how", "why", "are", "was", "were", "has", "have", "does", "did", "will", "into", "over", "about", "after", "before", "latest", "news", "2024", "2025", "2026", "2027"}


def query_terms(query: str) -> list[str]:
    q = re.sub(r"\b(site|inurl|intitle|subreddit):\S+", " ", query.lower())
    q = re.sub(r"[^\w\s-]", " ", q, flags=re.U)
    out: list[str] = []
    for t in re.split(r"[\s-]+", q):
        if len(t) >= 4 and t not in STOPWORDS and t not in out:
            out.append(t)
    return out


def plausible_results(query: str, results: list[SearchResult]) -> list[SearchResult]:
    terms = query_terms(query)
    if not terms:
        return results
    keep = []
    for r in results:
        hay = f"{r.title} {r.snippet} {r.domain}".lower()
        if any(t in hay or (len(t) > 5 and t[:-1] in hay) for t in terms):
            keep.append(r)
    if len(keep) < len(results):
        prov = results[0].provider if results else ""
        print(f"[search] dropped {len(results) - len(keep)} of {len(results)} {prov} results as off-topic for {query!r}")
    return keep


async def _attempt(p: SearchProvider, query: str, opts: dict) -> list[SearchResult]:
    if p.composite:
        return await p.search(query, opts)
    until = _cooling_until.get(p.name, 0.0)
    now = time.time()
    if now < until:
        raise RuntimeError(f"{p.name} is cooling down after a rate limit ({int(until - now)}s left)")
    try:
        return await p.search(query, opts)
    except Exception as e:
        if is_rate_limit(e):
            _cooling_until[p.name] = time.time() + (API_COOLDOWN_MS if p.name in API_PROVIDERS else COOLDOWN_MS) / 1000
        raise


def chain_of(providers: list[SearchProvider]) -> SearchProvider:
    if not providers:
        raise RuntimeError("no search providers configured")

    async def search(query: str, opts: dict) -> list[SearchResult]:
        _take_search()   # before any engine: past the cap nothing is sent, paid or free
        reasons: list[str] = []
        for pass_no in (1, 2):
            for p in providers:
                try:
                    r = plausible_results(query, await _attempt(p, query, opts))
                    if r:
                        if p is not providers[0] or pass_no > 1:
                            print(f"[search] {query!r} answered by {p.name}{' on the second pass' if pass_no > 1 else ''} after: {' | '.join(reasons)}")
                        return r
                    reasons.append(f"{p.name}: no on-topic results")
                except Exception as e:  # noqa: BLE001
                    reasons.append(f"{p.name}: {e}")
            if pass_no == 1:
                print(f"[search] every engine failed for {query!r} ({' | '.join(reasons)}); retrying the chain in {CHAIN_RETRY_MS}ms")
                await asyncio.sleep(CHAIN_RETRY_MS / 1000)
        raise RuntimeError("all search engines failed: " + " | ".join(reasons))

    return SearchProvider(name=providers[0].name, search=search, composite=True)


def _anthropic_key() -> str:
    try:
        from app.core.config import get_settings
        return get_settings().anthropic_api_key or ""
    except Exception:  # noqa: BLE001
        return os.environ.get("ANTHROPIC_API_KEY", "")


def get_search_provider() -> SearchProvider:
    """Engine order: SEARCH_PROVIDER first when set, keyed APIs whose keys are present (Brave
    API, Tavily, then Claude web search whenever ANTHROPIC_API_KEY is set — measured 2026-09-16:
    every keyless engine is blocked or rate-limited from Railway's datacenter IP, so the keyed
    engine goes ahead of them), then the keyless engines. SEARCH_DISABLE=a,b drops engines."""
    from . import engines

    disabled = {x.strip() for x in os.environ.get("SEARCH_DISABLE", "").split(",") if x.strip()}
    order: list[str] = []

    def push(name: str):
        if name not in order and name not in disabled:
            order.append(name)

    pref = os.environ.get("SEARCH_PROVIDER", "").strip()
    if pref:
        push(pref)
    if os.environ.get("BRAVE_API_KEY"):
        push("brave_api")
    if os.environ.get("TAVILY_API_KEY"):
        push("tavily")
    if _anthropic_key():
        push("anthropic")
    # Measured 2026-09-09: DuckDuckGo, Bing and Yahoo answer in <1 s; Brave's HTML page spends
    # up to a minute in 429 back-off, so it goes last as the fallback of last resort.
    push("duckduckgo")
    push("bing")
    push("yahoo")
    push("brave")
    return chain_of([engines.build(n) for n in order])


def has_keyed_engine() -> bool:
    disabled = {x.strip() for x in os.environ.get("SEARCH_DISABLE", "").split(",") if x.strip()}
    return bool(os.environ.get("BRAVE_API_KEY") or os.environ.get("TAVILY_API_KEY") or (_anthropic_key() and "anthropic" not in disabled))
