"""Reddit through its JSON endpoints: search listings and comment trees come back with exact
scores, upvote ratios, timestamps, self-text, flair and depth. A "subreddit:name" prefix
restricts a search to one community (works logged out); site-wide search may be refused
without a session. Plain httpx first; if Reddit answers 403/429 or a block page and Playwright
is available, the same fetch is retried from inside a headless browser page on reddit.com."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
_JUNK_AUTHORS = re.compile(r"^(automoderator|\[deleted\]|\[removed\]|.*bot|.*_bot|bot_.*|.*-bot)$", re.I)
_JUNK_TEXT = re.compile(r"^\s*(\[deleted\]|\[removed\]|\[deleted by user\]|\.+|lol|this|same|\^+|f|first)\s*$", re.I)


@dataclass
class SocialComment:
    author: str
    text: str
    likes: int
    published_at: Optional[str]


@dataclass
class ReadPost:
    external_id: str
    text: str
    author: Optional[str] = None
    author_title: Optional[str] = None
    published_at: Optional[str] = None
    url: Optional[str] = None
    likes: int = 0
    comment_count: int = 0
    image_url: Optional[str] = None
    comments: list[SocialComment] = field(default_factory=list)
    relevance: float = 0.0
    on_topic: bool = False
    stale: bool = False
    query: str = ""
    attempt: int = 0
    payload: dict[str, Any] = field(default_factory=dict)


class RedditBlocked(RuntimeError):
    pass


async def _json_httpx(path: str) -> Any:
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=True) as client:
        res = await client.get(f"https://www.reddit.com{path}", headers={"User-Agent": UA, "Accept": "application/json"})
    if res.status_code == 429:
        raise RedditBlocked("Reddit rate limit (429)")
    if res.status_code == 403:
        raise RedditBlocked("Reddit refused the request (403)")
    if res.status_code != 200:
        raise RuntimeError(f"Reddit {path.split('?')[0]} → HTTP {res.status_code}")
    try:
        return res.json()
    except Exception:  # noqa: BLE001
        raise RedditBlocked("Reddit returned a non-JSON page (login or block page)")


class _RedditBrowser:
    """One headless Chromium per process, parked on reddit.com, reused for every JSON fetch.
    Launching a browser per call was slow (~2 s each) and drew 403s on comment fetches; one
    warm page behaves like a normal visitor. Fetches are serialised by a lock; any failure
    tears the browser down so the next call starts clean."""

    def __init__(self):
        self._pw = None
        self._browser = None
        self._page = None
        self._lock: Optional[asyncio.Lock] = None   # created lazily: a Lock built at import binds to no loop on older Pythons
        self.last_used = 0.0

    async def _ensure(self):
        if self._page is not None:
            return
        from playwright.async_api import async_playwright  # type: ignore
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = await self._browser.new_context(user_agent=UA, locale="en-GB")
        self._page = await ctx.new_page()
        await self._page.goto("https://www.reddit.com/", wait_until="domcontentloaded", timeout=25_000)
        await self._page.wait_for_timeout(1200)

    async def close(self):
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._pw = self._browser = self._page = None

    async def fetch(self, path: str) -> Any:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            try:
                await self._ensure()
                out = await self._page.evaluate(
                    """async (p) => { const r = await fetch(p, {headers: {accept: 'application/json'}, credentials: 'include'}); const t = await r.text(); return {status: r.status, text: t.slice(0, 3000000)}; }""",
                    path,
                )
            except Exception:
                await self.close()
                raise
            import time as _t
            self.last_used = _t.time()
        if out["status"] in (403, 429):
            raise RedditBlocked(f"Reddit blocked the browser fetch ({out['status']})")
        if out["status"] != 200:
            raise RuntimeError(f"Reddit {path.split('?')[0]} → HTTP {out['status']} (browser)")
        try:
            return json.loads(out["text"])
        except Exception:  # noqa: BLE001
            raise RedditBlocked("Reddit returned a non-JSON page (browser)")


_browser = _RedditBrowser()


async def _json_browser(path: str) -> Any:
    return await _browser.fetch(path)


async def close_browser():
    await _browser.close()


async def reddit_json(path: str) -> Any:
    try:
        return await _json_httpx(path)
    except RedditBlocked as e:
        try:
            import playwright  # type: ignore # noqa: F401
        except Exception:
            raise e
        try:
            return await _json_browser(path)
        except RedditBlocked:
            await asyncio.sleep(2.5)   # a burst of fetches trips Reddit briefly; one calm retry
            return await _json_browser(path)


def split_subreddit(query: str) -> tuple[Optional[str], str]:
    m = re.search(r"(?:^|\s)(?:subreddit|sub|r):/?r?/?([A-Za-z0-9_]+)", query)
    terms = re.sub(r"(?:^|\s)(?:subreddit|sub|r):/?r?/?[A-Za-z0-9_]+", " ", query)
    return (m.group(1) if m else None), re.sub(r"\s+", " ", terms).strip()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def to_post(d: dict) -> ReadPost:
    body = (d.get("selftext") or "").strip()
    title = d.get("title") or ""
    text = f"{title}\n\n{body[:6000]}" if body else title
    url = d.get("url") or ""
    thumb = d.get("thumbnail") or ""
    image = url if re.search(r"\.(jpe?g|png|webp)(\?|$)", url, re.I) else (thumb if thumb.startswith("http") else None)
    return ReadPost(
        external_id=d["id"], author=f"u/{d.get('author')}", author_title=f"r/{d.get('subreddit')}", text=text,
        published_at=_iso(d.get("created_utc", 0)), url=f"https://www.reddit.com{d.get('permalink', '')}",
        likes=int(d.get("score", 0) or 0), comment_count=int(d.get("num_comments", 0) or 0), image_url=image,
        payload={"platform": "reddit", "subreddit": d.get("subreddit"), "title": title, "body": body[:6000], "score": d.get("score", 0),
                 "upvote_ratio": d.get("upvote_ratio"), "comments": d.get("num_comments", 0), "flair": d.get("link_flair_text"),
                 "kind": "video" if d.get("is_video") else ("image" if d.get("post_hint") == "image" else ("text" if body else "link")), "link_url": url},
    )


def junk_post(d: dict) -> bool:
    if d.get("over_18") or d.get("stickied") or d.get("removed_by_category"):
        return True
    if _JUNK_AUTHORS.match(d.get("author") or "") or (d.get("subreddit") or "").startswith("u_"):
        return True
    return not (d.get("title") or "").strip()


def dedupe_by_text(posts: list[ReadPost]) -> list[ReadPost]:
    seen: set[str] = set()
    out = []
    for p in posts:
        key = re.sub(r"\s+", " ", p.text.lower())[:160]
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


async def _search_once(sub: Optional[str], terms: str, sort: str, t: str) -> list[dict]:
    q = quote(terms)
    path = (f"/r/{quote(sub)}/search.json?q={q}&restrict_sr=on&sort={sort}&t={t}&limit=50&include_over_18=off&raw_json=1" if sub
            else f"/search.json?q={q}&sort={sort}&t={t}&limit=50&include_over_18=off&raw_json=1")
    j = await reddit_json(path)
    if isinstance(j, dict) and j.get("error"):
        raise RuntimeError(f"Reddit search error {j.get('error')}: {j.get('message', '')}")
    return [c["data"] for c in ((j.get("data") or {}).get("children") or []) if c.get("kind") == "t3"]


async def search_reddit(query: str) -> tuple[list[ReadPost], str]:
    """Relevance over the last year plus newest first, merged; optionally one subreddit."""
    sub, terms = split_subreddit(query)
    if not terms:
        return [], "Empty Reddit query."
    try:
        rel = await _search_once(sub, terms, "relevance", "year")
        try:
            recent = await _search_once(sub, terms, "new", "month")
        except Exception:  # noqa: BLE001
            recent = []
    except RedditBlocked as e:
        return [], f"Reddit blocked the search: {e}"
    seen: set[str] = set()
    merged = []
    for d in rel + recent:
        if d["id"] in seen or junk_post(d):
            continue
        seen.add(d["id"])
        merged.append(to_post(d))
    posts = dedupe_by_text(merged)
    return posts, f"Read {len(posts)} Reddit posts ({'r/' + sub + ', ' if sub else ''}relevance/year {len(rel)} + new/month {len(recent)}) for {terms!r}."


def _flatten(listing: Any, depth: int = 0, out: Optional[list] = None) -> list[dict]:
    out = out if out is not None else []
    if not listing or isinstance(listing, str):
        return out
    for c in ((listing.get("data") or {}).get("children") or []):
        if c.get("kind") != "t1":
            continue
        d = dict(c["data"])
        d["depth"] = depth
        out.append(d)
        if depth < 1:
            _flatten(d.get("replies"), depth + 1, out)
    return out


def junk_comment(c: dict) -> bool:
    text = (c.get("body") or "").strip()
    if not text or _JUNK_TEXT.match(text):
        return True
    if _JUNK_AUTHORS.match(c.get("author") or "") or c.get("stickied") or c.get("distinguished") == "moderator":
        return True
    if len(text.split()) < 8 and int(c.get("score", 0) or 0) < 15:
        return True   # one-liners nobody upvoted
    return bool(re.match(r"^https?://\S+$", text))


async def reddit_comments(post: ReadPost, max_comments: int) -> list[SocialComment]:
    from urllib.parse import urlparse
    permalink = urlparse(post.url).path if post.url else f"/comments/{post.external_id}/"
    j = await reddit_json(f"{permalink.rstrip('/')}.json?sort=top&limit=150&depth=2&raw_json=1")
    if not isinstance(j, list) or len(j) < 2:
        return []
    link = (((j[0].get("data") or {}).get("children") or [{}])[0].get("data") or {})
    if link.get("selftext") and link["selftext"][:80] not in post.text:
        post.text = f"{link.get('title', '')}\n\n{link['selftext']}"[:6000]
        post.payload["body"] = link["selftext"][:6000]
    if link.get("num_comments") is not None:
        post.comment_count = int(link["num_comments"])
    kept = sorted((c for c in _flatten(j[1]) if not junk_comment(c)), key=lambda c: (-int(c.get("score", 0) or 0), c["depth"]))[:max_comments]
    return [SocialComment(author=f"u/{c.get('author')}", text=(c.get("body") or "").strip()[:1500], likes=int(c.get("score", 0) or 0), published_at=_iso(c.get("created_utc", 0))) for c in kept]
