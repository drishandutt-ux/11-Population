"""Today's date, for every prompt a twin, a planner or a brief writer reads.

The model that writes a twin has a training cut-off. Told nothing about the date, it answers
from wherever its memory ends, and a 2020 survey in its knowledge reads as this morning's
news: the PedalPass twins (2026-10-19) described London roads, docks and schemes as they
were years ago and called a six-year-old safety poll current. So every persona prompt carries
today's date and the rule that dated knowledge is that old, and every knowledge item a twin
is handed carries the year it was published.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional


def today() -> datetime:
    return datetime.now(timezone.utc)


def today_text() -> str:
    """'Monday 19 October 2026'."""
    d = today()
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B %Y')}"


def today_block() -> str:
    """The block every twin prompt ends with: the date, and how to treat what it has read."""
    return (
        f"\n\nTODAY IS {today_text().upper()}. You live in the present:\n"
        "- What you say about your area, your journey to work, prices, services, apps, schemes and what is on offer "
        "is as it stands today, not as it was a few years ago. Things change — a road gets a cycle lane, a service "
        "launches or folds, a price goes up — and what you pass every day, or anyone living where you live would know "
        "by now, is yours to know.\n"
        "- Anything you have read or been told carries a date, and you treat it that way: a survey from years ago "
        "describes then, a trial announced years ago is old news. Prefer the most recent thing you know, say when a "
        "figure is years old if it matters, and never describe the past as if it were today.\n"
        "- If you are not sure whether something has changed since you last heard, say so — do not fill the gap with "
        "how things used to be."
    )


def planner_line() -> str:
    """One sentence for the prompts that plan a population or write its personas."""
    return (
        f" Today is {today_text()}: general knowledge of the place and the market means as it stands today, not years "
        "ago, and where the evidence is dated, say how old it is."
    )


_DATE_LIKE = re.compile(
    r"(?:^\s*(?:19|20)\d{2}\s*$)|(?:\b(?:19|20)\d{2}-\d{2}-\d{2})|(?:\b\d{1,2}\s+[A-Z][a-z]{2,8}\.?,?\s+(?:19|20)\d{2}\b)|(?:\b[A-Z][a-z]{2,8}\.?\s+\d{1,2},?\s+(?:19|20)\d{2}\b)"
)
_YEAR = re.compile(r"(?:19|20)\d{2}")


def year_of(value: Optional[str]) -> Optional[str]:
    """The four-digit year of a date-like string ('2024-01-22', 'Mon, 22 Jan 2024', '2020');
    None for anything that is not a date, so a year inside a URL is never read as one."""
    if not value:
        return None
    text = str(value).strip()
    if not _DATE_LIKE.search(text):
        return None
    m = _YEAR.search(text)
    return m.group(0) if m else None


def age_note(value: Optional[str]) -> str:
    """'2020, 6 years ago' / '2025' for a dated item; '' when the value is not a date."""
    y = year_of(value)
    if not y:
        return ""
    gap = today().year - int(y)
    return f"{y}, {gap} years ago" if gap >= 2 else y
