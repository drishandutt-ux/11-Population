"""The six engines. Keyless ones parse HTML with regexes against markup that has been stable;
each raises on rate limits/captchas so the chain benches it and moves on."""
from __future__ import annotations

import asyncio
import base64
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote, unquote, urlencode

import httpx

from .provider import SearchProvider, SearchResult, domain_of

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
_TIMEOUT = httpx.Timeout(20.0)


def decode_entities(s: str) -> str:
    s = re.sub(r"<!--[\s\S]*?-->", "", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = (s.replace("&amp;", "&").replace("&quot;", '"').replace("&#x27;", "'").replace("&#39;", "'").replace("&apos;", "'")
         .replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ").replace("&#160;", " ").replace("&middot;", "·").replace("&#183;", "·").replace("&#32;", " "))
    s = re.sub(r"[​-‍﻿]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _iso(dt_text: Optional[str]) -> Optional[str]:
    if not dt_text:
        return None
    t = dt_text.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            d = datetime.strptime(t.replace("Z", "+0000"), fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d.isoformat()
        except ValueError:
            continue
    return None


def _country(region: Optional[str]) -> Optional[str]:
    if not region:
        return None
    m = re.match(r"^([a-z]{2})-", region.lower())
    if not m:
        return None
    return {"uk": "GB", "wt": "ALL"}.get(m.group(1), m.group(1).upper())


# ── Brave Search API (keyed; free plan = 1 request/s shared by every caller) ────────
_brave_lock = asyncio.Lock()
_brave_last = 0.0
BRAVE_MIN_GAP = float(os.environ.get("BRAVE_API_MIN_GAP_MS", 1100)) / 1000
BRAVE_RETRY_MAX = float(os.environ.get("BRAVE_API_RETRY_MAX_MS", 8000)) / 1000


async def _brave_slot():
    global _brave_last
    async with _brave_lock:
        wait = _brave_last + BRAVE_MIN_GAP - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
        _brave_last = time.time()


def _reset_ms(res: httpx.Response) -> Optional[float]:
    ra = res.headers.get("retry-after")
    if ra and ra.isdigit() and int(ra) > 0:
        return float(ra)
    rs = (res.headers.get("x-ratelimit-reset") or "").split(",")[0].strip()
    if rs.isdigit() and int(rs) > 0:
        return float(rs)
    return None


async def _brave_api(query: str, opts: dict, retried: bool = False) -> list[SearchResult]:
    key = os.environ.get("BRAVE_API_KEY", "")
    if not key:
        raise RuntimeError("BRAVE_API_KEY is not set")
    params = {"q": query, "count": str(min(opts.get("max_results", 8), 20)), "text_decorations": "0", "extra_snippets": "0"}
    c = _country(opts.get("region"))
    if c:
        params["country"] = c
    await _brave_slot()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        res = await client.get("https://api.search.brave.com/res/v1/web/search", params=params,
                               headers={"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": key})
    if res.status_code == 429 and not retried:
        wait = _reset_ms(res) or 1.5
        if wait <= BRAVE_RETRY_MAX:
            print(f"[search] brave_api 429 for {query!r}; retrying in {wait}s")
            await asyncio.sleep(wait)
            return await _brave_api(query, opts, True)
    if res.status_code != 200:
        raise RuntimeError(f"Brave API HTTP {res.status_code}: {res.text[:200]}")
    out = []
    for r in (res.json().get("web", {}) or {}).get("results", []) or []:
        age = r.get("page_age") or r.get("age")
        out.append(SearchResult(title=r.get("title", ""), url=r["url"], domain=domain_of(r["url"]), snippet=r.get("description", ""), provider="brave_api", published_at=_iso(age) if age else None))
    if not out and re.search(r'["“”]', query):
        return await _brave_api(re.sub(r'["“”]', "", query), opts, retried)
    return out


# ── Tavily (keyed) ──────────────────────────────────────────────────────────────
async def _tavily(query: str, opts: dict) -> list[SearchResult]:
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        raise RuntimeError("TAVILY_API_KEY is not set")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        res = await client.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {key}"},
                                json={"api_key": key, "query": query, "max_results": opts.get("max_results", 8), "search_depth": "basic", "include_answer": False})
    if res.status_code != 200:
        raise RuntimeError(f"Tavily HTTP {res.status_code}: {res.text[:200]}")
    return [SearchResult(title=r.get("title", ""), url=r["url"], domain=domain_of(r["url"]), snippet=r.get("content", ""), provider="tavily", published_at=_iso(r.get("published_date")))
            for r in res.json().get("results", [])]


# ── Brave HTML (keyless) ────────────────────────────────────────────────────────
def parse_brave_html(html: str, max_results: int) -> list[SearchResult]:
    out: list[SearchResult] = []
    seen: set[str] = set()
    blocks = re.split(r'<div class="snippet [^"]*"[^>]*data-type="web"', html)[1:]
    for block in blocks:
        m = re.search(r'<a href="(https?://[^"]+)"', block)
        if not m:
            continue
        href = m.group(1)
        if href in seen or re.search(r"search\.brave\.com|imgs\.search\.brave\.com", href):
            continue
        t = re.search(r'class="title search-snippet-title[^"]*"[^>]*title="([^"]*)"', block) or re.search(r'class="title search-snippet-title[^"]*"[^>]*>([\s\S]*?)</div>', block)
        title = t.group(1) if t else href
        c = re.search(r'class="generic-snippet[\s\S]*?class="content[^"]*">([\s\S]*?)</div>', block)
        content = c.group(1) if c else ""
        d = re.search(r'<span class="t-secondary">([^<]+?)\s*-\s*</span>', content)
        snippet = decode_entities(re.sub(r'<span class="t-secondary">[^<]*</span>', "", content))
        seen.add(href)
        out.append(SearchResult(title=decode_entities(title), url=href, domain=domain_of(href), snippet=snippet, provider="brave", published_at=_iso(d.group(1)) if d else None))
        if len(out) >= max_results:
            break
    return out


async def _brave_html(query: str, opts: dict) -> list[SearchResult]:
    params = {"q": query, "source": "web"}
    c = _country(opts.get("region"))
    if c and c != "ALL":
        params["country"] = c.lower()
    waits = [15, 40]
    attempt = 0
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        while True:
            attempt += 1
            res = await client.get("https://search.brave.com/search", params=params, headers={"User-Agent": UA, "Accept": "text/html", "Accept-Language": "en-GB,en;q=0.9"})
            if res.status_code == 429 and attempt <= len(waits):
                await asyncio.sleep(waits[attempt - 1])
                continue
            if res.status_code != 200:
                raise RuntimeError(f"Brave HTTP {res.status_code}")
            html = res.text
            if re.search(r"captcha|verify you are human|unusual traffic", html, re.I) and 'data-type="web"' not in html:
                raise RuntimeError("Brave challenged this request (captcha)")
            return parse_brave_html(html, opts.get("max_results", 8))


# ── DuckDuckGo HTML (keyless) ───────────────────────────────────────────────────
def _decode_uddg(href: str) -> str:
    m = re.search(r"[?&]uddg=([^&]+)", href)
    if m:
        return unquote(m.group(1))
    return "https:" + href if href.startswith("//") else href


def parse_ddg_html(html: str, max_results: int) -> list[SearchResult]:
    anchors = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', html)
    snippets = re.findall(r'<a[^>]*class="result__snippet"[^>]*>([\s\S]*?)</a>', html)
    out: list[SearchResult] = []
    seen: set[str] = set()
    for idx, (href, title_html) in enumerate(anchors):
        url = _decode_uddg(href)
        if not re.match(r"^https?://", url) or url in seen or re.search(r"duckduckgo\.com/y\.js|bing\.com/aclick", url):
            continue
        seen.add(url)
        out.append(SearchResult(title=decode_entities(title_html), url=url, domain=domain_of(url), snippet=decode_entities(snippets[idx]) if idx < len(snippets) else "", provider="duckduckgo"))
        if len(out) >= max_results:
            break
    return out


async def _ddg(query: str, opts: dict) -> list[SearchResult]:
    params = {"q": query}
    if opts.get("region"):
        params["kl"] = opts["region"]
    waits = [5, 12]
    attempt = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        while True:
            attempt += 1
            res = await client.get("https://html.duckduckgo.com/html/", params=params, headers={"User-Agent": UA, "Accept": "text/html", "Accept-Language": "en-GB,en;q=0.9"})
            if res.status_code != 200:
                raise RuntimeError(f"DuckDuckGo HTTP {res.status_code}")
            html = res.text
            if re.search(r"anomaly-modal|Unfortunately, bots use DuckDuckGo too", html, re.I):
                if attempt <= len(waits):
                    await asyncio.sleep(waits[attempt - 1])
                    continue
                raise RuntimeError("DuckDuckGo rate-limited this request; wait a moment and retry")
            return parse_ddg_html(html, opts.get("max_results", 8))


# ── Yahoo HTML (keyless) ────────────────────────────────────────────────────────
def _decode_yahoo(href: str) -> Optional[str]:
    raw = href.replace("&amp;", "&")
    m = re.search(r"/RU=([^/]+)/", raw)
    url = unquote(m.group(1)) if m else raw
    if re.match(r"^https?://", url) and not re.search(r"search\.yahoo\.com|\.yahoo\.com/?$", url):
        return url
    return None


def parse_yahoo_html(html: str, max_results: int) -> list[SearchResult]:
    out: list[SearchResult] = []
    seen: set[str] = set()
    for part in re.split(r'<h3[^>]*class="title"[^>]*>', html)[1:]:
        a = re.match(r'\s*<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', part)
        if not a:
            continue
        url = _decode_yahoo(a.group(1))
        if not url or url in seen:
            continue
        seen.add(url)
        title = decode_entities(re.sub(r"<span[^>]*>[\s\S]*?</span>", "", a.group(2)))
        snip = re.search(r'<p[^>]*class="[^"]*(?:fc-falcon|compText)[^"]*"[^>]*>([\s\S]*?)</p>', part) or re.search(r'<span[^>]*class="[^"]*fc-falcon[^"]*"[^>]*>([\s\S]*?)</span>', part)
        out.append(SearchResult(title=title or url, url=url, domain=domain_of(url), snippet=decode_entities(snip.group(1)) if snip else "", provider="yahoo"))
        if len(out) >= max_results:
            break
    return out


async def _yahoo(query: str, opts: dict) -> list[SearchResult]:
    max_results = opts.get("max_results", 8)
    m = re.match(r"^([a-z]{2})-", (opts.get("region") or "").lower())
    cc = m.group(1) if m else None
    host = f"{cc}.search.yahoo.com" if cc and cc not in ("wt", "us") else "search.yahoo.com"
    params = {"p": query, "n": str(min(max(max_results, 10), 30))}
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        res = await client.get(f"https://{host}/search", params=params, headers={"User-Agent": UA})  # UA only: Accept headers → 500
    if res.status_code in (429, 500):
        raise RuntimeError(f"Yahoo rate-limited this request (HTTP {res.status_code})")
    if res.status_code != 200:
        raise RuntimeError(f"Yahoo HTTP {res.status_code}")
    results = parse_yahoo_html(res.text, max_results)
    if not results and re.search(r"captcha|unusual traffic|robot", res.text, re.I):
        raise RuntimeError("Yahoo challenged this request (captcha)")
    return results


# ── Bing HTML (keyless) ─────────────────────────────────────────────────────────
def _decode_bing(href: str) -> Optional[str]:
    raw = href.replace("&amp;", "&")
    if not re.search(r"bing\.com/ck/", raw):
        return raw if re.match(r"^https?://", raw) else None
    m = re.search(r"[?&]u=a1([A-Za-z0-9_-]+)", raw)
    if not m:
        return None
    try:
        pad = "=" * (-len(m.group(1)) % 4)
        url = base64.urlsafe_b64decode(m.group(1) + pad).decode("utf-8", "ignore")
        return url if re.match(r"^https?://", url) else None
    except Exception:  # noqa: BLE001
        return None


def _split_caption(caption: str) -> tuple[Optional[str], str]:
    m = re.match(r"^(\d{1,2} [A-Z][a-z]{2} \d{4}|[A-Z][a-z]{2} \d{1,2}, \d{4}) ?· ?(.*)$", caption)
    if not m:
        return None, caption
    return _iso(m.group(1)), m.group(2)


def parse_bing_html(html: str, max_results: int) -> list[SearchResult]:
    out: list[SearchResult] = []
    seen: set[str] = set()
    for block in re.findall(r'<li class="b_algo"[\s\S]*?</li>', html):
        a = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', block)
        if not a:
            continue
        url = _decode_bing(a.group(1))
        if not url or url in seen:
            continue
        seen.add(url)
        cap = re.search(r'<div class="b_caption">[\s\S]*?<p[^>]*>([\s\S]*?)</p>', block) or re.search(r'<p class="b_lineclamp[^"]*"[^>]*>([\s\S]*?)</p>', block)
        published, text = _split_caption(decode_entities(cap.group(1)) if cap else "")
        out.append(SearchResult(title=decode_entities(a.group(2)) or url, url=url, domain=domain_of(url), snippet=text, provider="bing", published_at=published))
        if len(out) >= max_results:
            break
    return out


async def _bing(query: str, opts: dict) -> list[SearchResult]:
    max_results = opts.get("max_results", 8)
    params = {"q": query, "count": str(min(max(max_results, 10), 30))}
    m = re.match(r"^([a-z]{2})-([a-z]{2})$", (opts.get("region") or "").lower())
    if m and m.group(1) != "wt":
        cc = "GB" if m.group(1) == "uk" else m.group(1).upper()
        params["setlang"] = f"{m.group(2)}-{cc}"
        params["cc"] = cc
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        res = await client.get("https://www.bing.com/search", params=params, headers={"User-Agent": UA, "Accept": "text/html", "Accept-Language": "en-GB,en;q=0.9"})
    if res.status_code == 429:
        raise RuntimeError("Bing HTTP 429")
    if res.status_code != 200:
        raise RuntimeError(f"Bing HTTP {res.status_code}")
    results = parse_bing_html(res.text, max_results)
    if not results and re.search(r"captcha|verify|unusual traffic", res.text, re.I) and "b_algo" not in res.text:
        raise RuntimeError("Bing challenged this request (captcha)")
    return results


_ENGINES = {
    "brave_api": _brave_api,
    "tavily": _tavily,
    "brave": _brave_html,
    "duckduckgo": _ddg,
    "yahoo": _yahoo,
    "bing": _bing,
}


def build(name: str) -> SearchProvider:
    fn = _ENGINES.get(name)
    if not fn:
        raise RuntimeError(f"unknown search engine {name!r}")
    return SearchProvider(name=name, search=fn)
