"""Fetch a result page and reduce it to readable text for the evidence pool.
HTML: httpx + trafilatura (main content, boilerplate stripped). PDF: Claude skims it for the
query. Thin pages (teaser cards, cookie walls, 404s) are rejected so they never become
evidence. On 403 / bot walls / thin pages, one retry in headless Chromium when Playwright is
installed (it is in the production image; optional locally)."""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Optional

import httpx

from app.core.config import get_settings
from app.core.monitoring import tracked_messages_create

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
MAX_CHARS = 20_000
MIN_CHARS = 400
MAX_PDF_BYTES = 20 * 1024 * 1024


@dataclass
class FetchedPage:
    url: str
    title: str
    markdown: str
    chars: int
    truncated: bool
    status: int
    kind: str                      # html | pdf
    published_at: Optional[str] = None
    image_url: Optional[str] = None


class FetchError(RuntimeError):
    pass


def _meta(html: str, name: str) -> Optional[str]:
    m = re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']', html, re.I) \
        or re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(name)}["\']', html, re.I)
    return m.group(1) if m else None


def published_date(html: str) -> Optional[str]:
    v = _meta(html, "article:published_time") or _meta(html, "datePublished") or _meta(html, "date") or _meta(html, "dc.date")
    if not v:
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html) or re.search(r'<time[^>]+datetime=["\']([^"\']+)["\']', html, re.I)
        v = m.group(1) if m else None
    if not v:
        return None
    from .search.engines import _iso
    return _iso(v) or (v if re.match(r"^\d{4}-\d{2}-\d{2}", v) else None)


def page_image(html: str, base: str) -> Optional[str]:
    v = _meta(html, "og:image:secure_url") or _meta(html, "og:image") or _meta(html, "twitter:image") or _meta(html, "twitter:image:src")
    if not v:
        return None
    from urllib.parse import urljoin
    u = urljoin(base, v.replace("&amp;", "&"))
    return u if u.startswith(("http://", "https://")) else None


def html_to_text(html: str, url: str) -> tuple[str, str]:
    """(title, main text). trafilatura when available, else a crude tag strip."""
    title_m = re.search(r"<title[^>]*>([\s\S]*?)</title>", html, re.I)
    title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else url
    text = ""
    try:
        import trafilatura  # type: ignore
        text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True, favor_recall=True, output_format="markdown") or ""
    except Exception:  # noqa: BLE001
        text = ""
    if not text:
        body = re.sub(r"<(script|style|noscript|svg|iframe|form|nav|header|footer|aside)[^>]*>[\s\S]*?</\1>", " ", html, flags=re.I)
        body = re.sub(r"<!--[\s\S]*?-->", "", body)
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    # Drop leading cookie/consent boilerplate when real content follows it.
    m = re.search(r"cookies? on |we use (some )?(essential )?cookies|accept (all )?cookies", text[:600], re.I)
    if m:
        rest = text[m.start():]
        cut = re.search(r"\n#{1,3} ", rest)
        if cut and cut.start() > 0:
            text = rest[cut.start():].strip()
    return title, text


def _finish(url: str, title: str, text: str, status: int, kind: str, html: str = "") -> FetchedPage:
    if re.search(r"page not found|404|access denied|just a moment", title, re.I):
        raise FetchError(f"Unusable page: {title[:60]}")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < MIN_CHARS:
        raise FetchError(f"Thin page ({len(text)} chars)")
    truncated = len(text) > MAX_CHARS
    if truncated:
        text = text[:MAX_CHARS] + "\n\n[... truncated ...]"
    return FetchedPage(url=url, title=title[:200], markdown=text, chars=len(text), truncated=truncated, status=status, kind=kind,
                       published_at=published_date(html) if html else None, image_url=page_image(html, url) if html else None)


async def _skim_pdf(url: str, data: bytes, query: str, status: int) -> FetchedPage:
    settings = get_settings()
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    resp = await tracked_messages_create(
        client, label="research_pdf", model=settings.model_fast, max_tokens=1500,
        messages=[{"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(data).decode()}},
            {"type": "text", "text": f"Skim this document for what bears on: {query}\n\nStart with a line '## Document' followed by its title, then the key facts, figures, dates and positions as markdown bullets. Quote numbers exactly. 300-600 words."},
        ]}],
    )
    md = resp.content[0].text.strip()
    tm = re.search(r"## Document\s*\n([^\n]+)", md)
    title = tm.group(1).strip() if tm else url.rsplit("/", 1)[-1]
    return FetchedPage(url=url, title=title[:200], markdown=md, chars=len(md), truncated=False, status=status, kind="pdf")


async def fetch_plain(url: str, query: str = "") -> FetchedPage:
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=True) as client:
        res = await client.get(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8", "Accept-Language": "en-GB,en;q=0.9"})
    if res.status_code >= 400:
        raise FetchError(f"HTTP {res.status_code}")
    ctype = (res.headers.get("content-type") or "").lower()
    is_pdf = "application/pdf" in ctype or (re.search(r"\.pdf(\?|#|$)", url, re.I) and "text/html" not in ctype)
    if is_pdf:
        if len(res.content) > MAX_PDF_BYTES:
            raise FetchError(f"PDF too large to skim ({len(res.content) / 1048576:.1f} MB)")
        return await _skim_pdf(url, res.content, query or "What are the key facts in this document?", res.status_code)
    if "text/html" not in ctype:
        raise FetchError(f"Not HTML ({ctype or 'unknown'})")
    html = res.text
    title, text = html_to_text(html, url)
    return _finish(url, title, text, res.status_code, "html", html)


async def fetch_with_browser(url: str) -> FetchedPage:
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise FetchError(f"Playwright not installed ({type(e).__name__})")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        try:
            ctx = await browser.new_context(user_agent=UA, locale="en-GB")
            page = await ctx.new_page()
            res = await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            await page.wait_for_timeout(1500)
            status = res.status if res else 0
            if status >= 400:
                raise FetchError(f"HTTP {status} (browser)")
            title = (await page.title()).strip() or url
            text = await page.evaluate("() => { const m = document.querySelector('article') || document.querySelector('main') || document.body; return m ? (m.innerText || '') : ''; }")
            html = await page.content()
            return _finish(url, title, text, status, "html", html)
        finally:
            await browser.close()


async def fetch_page(url: str, query: str = "", browser_fallback: bool = True) -> FetchedPage:
    try:
        return await fetch_plain(url, query)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if browser_fallback and not re.search(r"\.pdf(\?|#|$)", url, re.I) and re.search(r"HTTP 40[13]|Thin page|Not HTML \(unknown\)", msg):
            try:
                return await fetch_with_browser(url)
            except Exception as e2:  # noqa: BLE001
                raise FetchError(f"{msg}; browser: {e2}")
        if isinstance(e, FetchError):
            raise
        raise FetchError(f"{type(e).__name__}: {msg}")
