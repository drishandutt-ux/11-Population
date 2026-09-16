"""Tavily: keyed web search and page extraction behind one rate-limited client.

Why one module: every Tavily feature shares the account's request budget (100 requests per
minute on a development key, 1,000 on production), so search, extract and anything wired up
later all take a slot from the same limiter. The limiter is a rolling 60-second window sized
by TAVILY_RPM (default 95, i.e. below the 100/min development limit): the 96th call in any
minute waits until the oldest call leaves the window, then proceeds — requests are never
dropped, only paced. A 429 still honours Retry-After once before the engine is benched.

What Tavily does for the evidence practice (docs.tavily.com, read 2026-09-16):
  * /search — `include_domains` (+ `include_domains_mode: "filter"`) replaces the `site:`
    operator the statistics catalogue relies on and which Bing/Yahoo/Brave apply loosely;
    `search_depth: "advanced"` reranks for niche pages (2 credits vs 1); `chunks_per_source`
    returns up to three 500-character passages per hit — richer than a SERP snippet for
    triage; `country` boosts a nation's publishers; `include_published_date` dates hits.
  * /extract — cleaned markdown for up to 20 URLs per request; `extract_depth: "advanced"`
    keeps tables and embedded content (statistics releases are mostly tables). Used as the
    reader's second tier: after plain httpx fails (403, bot wall, thin page) and before the
    headless-Chromium retry.
  * /crawl, /map and the async /research endpoint exist but are not wired: the loop already
    decides page by page which URLs are worth reading, and the crawler is capped at
    100 requests/minute of its own.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from collections import deque
from typing import Awaitable, Callable, Optional

import httpx

from .search.provider import SearchResult, domain_of

BASE = "https://api.tavily.com"
TIMEOUT = httpx.Timeout(30.0)
RETRY_AFTER_MAX = float(os.environ.get("TAVILY_RETRY_AFTER_MAX_S", 70))


def api_key() -> str:
    return os.environ.get("TAVILY_API_KEY", "").strip()


def configured() -> bool:
    return bool(api_key())


class RateLimiter:
    """At most `rpm` acquisitions in any rolling `window` seconds; extra callers wait their turn
    in order. `clock` / `sleep` are injectable so tests run without real time."""

    def __init__(self, rpm: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self.rpm = max(1, rpm)
        self.window = window
        self._clock = clock
        self._sleep = sleep
        self._stamps: deque[float] = deque()
        self._lock: Optional[asyncio.Lock] = None
        self.waited_total = 0.0

    def _prune(self, now: float) -> None:
        while self._stamps and now - self._stamps[0] >= self.window:
            self._stamps.popleft()

    async def acquire(self) -> float:
        """Block until a slot is free; returns how long this caller waited."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:  # FIFO: whoever is waiting for the lock goes next
            waited = 0.0
            while True:
                now = self._clock()
                self._prune(now)
                if len(self._stamps) < self.rpm:
                    self._stamps.append(now)
                    self.waited_total += waited
                    return waited
                delay = self.window - (now - self._stamps[0]) + 0.05
                if waited == 0.0:
                    print(f"[tavily] {self.rpm}/min budget spent; next request waits {delay:.1f}s")
                await self._sleep(delay)
                waited += delay

    def in_window(self) -> int:
        self._prune(self._clock())
        return len(self._stamps)


limiter = RateLimiter(int(os.environ.get("TAVILY_RPM", 95)))


async def post(path: str, payload: dict, *, retried: bool = False) -> dict:
    key = api_key()
    if not key:
        raise RuntimeError("TAVILY_API_KEY is not set")
    await limiter.acquire()
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        res = await client.post(f"{BASE}{path}", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=payload)
    if res.status_code == 429:
        ra = res.headers.get("retry-after")
        wait = float(ra) if ra and re.match(r"^\d+(\.\d+)?$", ra) else 5.0
        if not retried and wait <= RETRY_AFTER_MAX:
            print(f"[tavily] 429 on {path}; honouring Retry-After {wait:.0f}s")
            await asyncio.sleep(wait)
            return await post(path, payload, retried=True)
        raise RuntimeError(f"Tavily HTTP 429 rate limit on {path}: {res.text[:120]}")
    if res.status_code != 200:
        raise RuntimeError(f"Tavily HTTP {res.status_code} on {path}: {res.text[:200]}")
    return res.json()


# ── search ──────────────────────────────────────────────────────────────────────
_SITE_RE = re.compile(r"\bsite:([A-Za-z0-9.-]+\.[A-Za-z]{2,})(/[^\s]*)?", re.I)

COUNTRIES = {
    "gb": "united kingdom", "uk": "united kingdom", "us": "united states", "ie": "ireland", "de": "germany", "fr": "france",
    "es": "spain", "it": "italy", "nl": "netherlands", "be": "belgium", "se": "sweden", "no": "norway", "dk": "denmark",
    "fi": "finland", "pl": "poland", "pt": "portugal", "ch": "switzerland", "at": "austria", "au": "australia",
    "nz": "new zealand", "ca": "canada", "in": "india", "sg": "singapore", "jp": "japan", "kr": "south korea",
    "br": "brazil", "mx": "mexico", "za": "south africa", "ae": "united arab emirates", "sa": "saudi arabia",
}


def split_site_operator(query: str) -> tuple[str, list[str], list[str]]:
    """`site:ons.gov.uk` → include_domains; `site:gov.uk/government/statistics` keeps the path as
    a hint word list so ranking still favours it. Returns (query, domains, path_hints)."""
    domains: list[str] = []
    hints: list[str] = []
    for m in _SITE_RE.finditer(query):
        d = m.group(1).lower()
        d = d[4:] if d.startswith("www.") else d
        if d not in domains:
            domains.append(d)
        if m.group(2):
            hints.extend(w for w in re.split(r"[/_-]+", m.group(2)) if len(w) >= 4)
    q = _SITE_RE.sub(" ", query)
    q = re.sub(r"\s+", " ", q).strip()
    return q, domains, hints


def country_for(region: Optional[str]) -> Optional[str]:
    m = re.match(r"^([a-z]{2})-", (region or "").lower())
    return COUNTRIES.get(m.group(1)) if m else None


def search_payload(query: str, opts: dict) -> dict:
    q, domains, hints = split_site_operator(query)
    depth = os.environ.get("TAVILY_SEARCH_DEPTH", "").strip() or ("advanced" if domains else "basic")
    payload: dict = {
        "query": (q + (" " + " ".join(hints) if hints else ""))[:1500],
        "search_depth": depth,
        "max_results": max(1, min(int(opts.get("max_results", 8)), 20)),
        "chunks_per_source": 3,
        "include_published_date": True,
        "include_answer": False,
        "include_raw_content": False,
    }
    if domains:
        payload["include_domains"] = domains
        payload["include_domains_mode"] = "filter"
    c = country_for(opts.get("region"))
    if c:
        payload["country"] = c
    if opts.get("time_range") in ("day", "week", "month", "year"):
        payload["time_range"] = opts["time_range"]
    if opts.get("topic") in ("news", "finance"):
        payload["topic"] = opts["topic"]
    return payload


def parse_search(data: dict, max_results: int) -> list[SearchResult]:
    out: list[SearchResult] = []
    seen: set[str] = set()
    for r in data.get("results", []) or []:
        url = r.get("url") or ""
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append(SearchResult(title=r.get("title") or url, url=url, domain=domain_of(url), snippet=(r.get("content") or "")[:1500],
                                provider="tavily", published_at=r.get("published_date") or None))
        if len(out) >= max_results:
            break
    return out


async def search(query: str, opts: dict) -> list[SearchResult]:
    data = await post("/search", search_payload(query, opts))
    return parse_search(data, opts.get("max_results", 8))


# ── extract ─────────────────────────────────────────────────────────────────────
async def extract(urls: list[str], *, query: str = "", depth: str = "advanced", fmt: str = "markdown") -> tuple[dict[str, str], dict[str, str]]:
    """Returns ({url: markdown}, {url: error}) for up to 20 URLs in ONE request (one slot of the
    minute budget). `query` reranks the returned chunks toward what the reader is hunting."""
    if not urls:
        return {}, {}
    payload: dict = {"urls": urls[:20], "extract_depth": depth, "format": fmt}
    if query:
        payload["query"] = query[:500]
        payload["chunks_per_source"] = 5
    data = await post("/extract", payload)
    ok = {r["url"]: (r.get("raw_content") or "") for r in data.get("results", []) or [] if r.get("url")}
    failed = {r["url"]: (r.get("error") or "extract failed") for r in data.get("failed_results", []) or [] if r.get("url")}
    return ok, failed
