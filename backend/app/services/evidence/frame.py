"""Research frame: decompose the question before any search runs, so every later stage works
from the same map — sub-questions, entities and aliases, places, hashtags, stakeholder angles,
and the look-alikes to keep out. The planner writes queries from it; the judges score against it."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from .llm import analyze, arr, enum, obj, s

FRAME_SCHEMA = obj({
    "subject": s("What the question is about, one line, naming the responsible body"),
    "sub_questions": arr(obj({
        "id": s("short id like q1"),
        "text": s(),
        "kind": enum(["status", "timeline", "reaction", "comparison", "forecast", "explanation"]),
    }), "The distinct things the question asks (1-7). A reaction question and a 'is X left behind' question are separate. For a how-to or advice question, also the fundamentals a seasoned practitioner would insist on", 7),
    "organisations": arr(s(), "Bodies, companies, trade groups, campaigns involved, with common abbreviations in parentheses", 10),
    "people": arr(s(), "Named people likely to be quoted: ministers, MPs, executives, campaigners", 8),
    "places": arr(s(), "Regions, counties, towns, ports, sea areas the question implies — expand a region into its counties and ports", 10),
    "programmes": arr(s(), "Named schemes, rounds, bills, projects, products", 8),
    "aliases": arr(s(), "Other names, nicknames, abbreviations and plain-language phrasings people use for the subject", 12),
    "hashtags": arr(s(), "Hashtags likely used on X and Instagram for this subject", 10),
    "angles": arr(s(), "Stakeholder groups whose reaction matters: officials, developers, local councils, fishing communities, environmental groups, unions, users…", 8),
    "lookalikes": arr(s(), "Similarly named things that are NOT the subject and must be excluded or labelled", 6),
    "recency": s("The time window that matters, in words, e.g. 'since March 2026' or 'last 12 months' or 'any'"),
    "time_sensitivity": enum(["live", "recent", "period", "timeless"], "live: changes week to week; recent: latest state, older material is background; period: a specific past period; timeless: age does not matter"),
    "window_start": s("YYYY-MM-DD from which material counts as current; empty when timeless"),
    "window_end": s("YYYY-MM-DD end of the period for 'period' questions; empty otherwise"),
    "time_why": s("One sentence: why outdated information would mislead this user, or why it would not"),
})

SYSTEM = """You prepare a research frame for a question before any searching. Decompose it into its sub-questions and list everything a thorough researcher would search for: the bodies and people involved, the places (expanding a region into the counties, towns, ports and sea areas people actually post about), the programmes and projects, the aliases and abbreviations used in public conversation, the hashtags, the stakeholder angles, and the look-alikes to exclude. Be concrete and specific to this question; do not pad with generic terms. Today's date is given.
Hard rules:
- Aliases, abbreviations, and hashtags must be ones you are confident are actually used in press, official material, or public posts. Never coin an abbreviation or hashtag; if unsure, leave it out. Plain-language phrasings ("the leasing round", "the new seabed auction") are safe aliases.
- People must be named individuals you are confident hold the role now; never write role placeholders like "CEO of X". Omit if unknown.
- Look-alikes must be real things that share a name or label with the subject.
- How-to and advice questions: the sub-questions must cover what a seasoned practitioner would insist on for this kind of question, not only what the question literally names.
- Time: decide honestly whether outdated information would mislead this user. "live" is reserved for questions whose answer moves week to week. A reaction to a specific announcement, decision, plan, or law is "recent", and window_start is the date of that announcement (or 12 months before today if you do not know it). A question about how something works or its history is "timeless" or "period"."""


def today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def build_frame(question: str, session_id: Optional[str] = None, context: str = "") -> Optional[dict]:
    try:
        extra = f"\n\nThe user also supplied source material; derive sub-questions from it too:\n{context[:4000]}" if context else ""
        f = await analyze(FRAME_SCHEMA, SYSTEM, f"Today: {today_iso()}\nQuestion: {question}{extra}", session_id=session_id, label="research_frame", max_tokens=4000)
        f["sub_questions"] = [q for q in f.get("sub_questions", []) if q.get("text")][:7]
        if not f["sub_questions"]:
            f["sub_questions"] = [{"id": "q1", "text": question, "kind": "status"}]
        return f
    except Exception as e:  # noqa: BLE001
        print(f"[research] frame failed: {type(e).__name__}: {e}")
        return None


def fallback_frame(question: str) -> dict:
    return {"subject": question, "sub_questions": [{"id": "q1", "text": question, "kind": "status"}], "organisations": [], "people": [], "places": [],
            "programmes": [], "aliases": [], "hashtags": [], "angles": [], "lookalikes": [], "recency": "any",
            "time_sensitivity": "recent", "window_start": "", "window_end": "", "time_why": "Heuristic frame (no LLM)."}


def _decay(age_ms: float, per_month: float) -> float:
    months = age_ms / (30 * 86_400_000)
    return round(max(0.05, per_month ** months), 2)


def freshness_of(published_at: Optional[str], frame: Optional[dict], now_ms: Optional[float] = None) -> float:
    """0..1: inside the window = 1; before it decays per month by sensitivity; unknown = 0.5; timeless = 1."""
    if not frame or frame.get("time_sensitivity") == "timeless":
        return 1.0
    if not published_at:
        return 0.5
    try:
        t = datetime.fromisoformat(published_at.replace("Z", "+00:00")).timestamp() * 1000
    except Exception:  # noqa: BLE001
        return 0.5
    now = now_ms or datetime.now(timezone.utc).timestamp() * 1000

    def parse(d: str) -> Optional[float]:
        try:
            return datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp() * 1000 if d else None
        except Exception:  # noqa: BLE001
            return None

    start, end = parse(frame.get("window_start", "")), parse(frame.get("window_end", ""))
    sens = frame.get("time_sensitivity", "recent")
    if sens == "period":
        if start and t < start:
            return _decay(start - t, 0.85)
        if end and t > end:
            return _decay(t - end, 0.85)
        return 1.0
    frm = start if start else now - (60 if sens == "live" else 365) * 86_400_000
    if t >= frm:
        return 1.0
    return _decay(frm - t, 0.6 if sens == "live" else 0.8)


def stale_before(frame: Optional[dict]) -> Optional[str]:
    if not frame or frame.get("time_sensitivity") in ("timeless", "period"):
        return None
    if frame.get("window_start"):
        return frame["window_start"]
    days = 60 if frame.get("time_sensitivity") == "live" else 365
    return datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - days * 86400, tz=timezone.utc).strftime("%Y-%m-%d")


def frame_for_prompt(f: dict) -> str:
    win = f"{f.get('window_start')}{' to ' + f['window_end'] if f.get('window_end') else ' onwards'}" if f.get("window_start") else "not date-bound"
    lines = [
        f"Subject: {f.get('subject', '')}",
        "Sub-questions: " + " | ".join(f"[{q.get('id')} {q.get('kind')}] {q.get('text')}" for q in f.get("sub_questions", [])),
    ]
    for key, label in (("organisations", "Organisations"), ("people", "People"), ("places", "Places"), ("programmes", "Programmes/projects"), ("aliases", "Aliases people use"), ("angles", "Stakeholder angles"), ("lookalikes", "Look-alikes to exclude")):
        if f.get(key):
            lines.append(f"{label}: {', '.join(f[key])}")
    if f.get("hashtags"):
        lines.append("Hashtags: " + " ".join(f["hashtags"]))
    lines.append(f"Recency: {f.get('recency', 'any')}")
    lines.append(f"Time sensitivity: {f.get('time_sensitivity')} ({win}). {f.get('time_why', '')} Items carry a freshness score 0-1 against this window: prefer high-freshness items for the current state; use low-freshness items only as background.")
    return "\n".join(lines)


def frame_terms(f: dict) -> list[str]:
    """Terms for cheap relevance ranking of graph entities: entities, places, aliases, sub-question words."""
    from .search.provider import query_terms
    out: list[str] = []
    for key in ("organisations", "people", "places", "programmes", "aliases"):
        for v in f.get(key, []) or []:
            out.extend(query_terms(v))
    for q in f.get("sub_questions", []) or []:
        out.extend(query_terms(q.get("text", "")))
    seen: set[str] = set()
    return [t for t in out if not (t in seen or seen.add(t))]
