"""The report structure, wired to the records underneath (brief L6-02).

The report keeps its seven parts — direct answer, question, source materials by role,
discussion with named dissent, metrics, outcome, conclusion-changing caveats — but each part
that *can* be computed now is, and the model only writes the prose around it:

  * **Direct answer** — the figure is the headline record (L6-01) and its confidence band is
    computed from that record's score (`confidence_band`), never asserted by the model. Any
    `Confidence: HIGH` line the model writes anyway is stripped (`strip_confidence_line`).
  * **Source materials by role** — the evidence the session actually holds, grouped by class
    (web, social, quant, personal, synthetic) with its trust mix and top items, plus the
    sampling frame's sourced dimensions (`evidence_summary`, `evidence_block`).
  * **Discussion with named dissent** — the population's positions come from the verdict
    probe: every twin's for / against / mixed with their one-line verdict. The majority is the
    most common position and the dissent is everyone else, listed for the model by handle
    (`positions_block`) and for the reader by id (`dissent_for`).
  * **Metrics** — the outcome records (L6-01).
  * **Outcome / caveats** — the deduplicated union of the cited records' computed caveats
    (`caveats_from_records`); the model still writes its own analytic ones in prose.

`build_structure` assembles all of that into one JSON object stored beside the answer, so a
reopened report renders the same wired parts without re-deriving them.

Generic by design: nothing here knows a domain. Pure functions except the two loaders.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from sqlalchemy import func, select

from app.core import database as dbm
from app.models.evidence import Evidence
from app.models.kg import KnowledgeGraph
from app.models.measurement import ProbeAnswer

#: The report's section spec — owned here so the structure has one owner (it used to live in
#: the frontend page). The model writes prose under these headings and nothing it can be
#: handed as data: no confidence label, no invented figures, no dissent it picked itself.
REPORT_PROMPT = """You are a senior analyst. Produce a structured executive briefing for this simulation session.

CRITICAL: Your VERY FIRST line must be "## DIRECT ANSWER" — no preamble, no intro. Use exactly these five sections in this order:

## DIRECT ANSWER
One precise sentence directly answering the user's question, leading with the headline record ([[R1]]). Do NOT write a confidence level — it is computed from the record and shown beside your sentence.

## QUESTION
Restate the question being investigated and why it matters.

## SOURCE MATERIALS
What grounds this population, by role: go through == EVIDENCE BY CLASS == in the order given, name the items that mattered and their direct relevance to the query, then state the population frame (including any model-estimated distribution). Be specific; do not list material that is not there.

## DISCUSSION
Which perspectives were represented, what the majority position concluded and why, then the NAMED DISSENT: the twins listed as dissenting under == POSITIONS == — one entry each, opened with the handle once ([[A7]]: "…"), quoting their verdict line, then what would have to be true for them to be right, referring back to them by pronoun and citing the statement it rests on after the claim ([[A7#P12]]). Then any contradictions or risks flagged during the debate.

## OUTCOME
Final recommendation and answer. State the 2–3 analytic caveats that could change the conclusion (the computed caveats from the records are shown separately — do not repeat them).

Every figure about the population comes from an OUTCOME RECORD and is cited right after it ([[R1]]). Every figure from the source material cites the typed statistic ([[F2]]) or the document it was read in ([[E3]]); a number you cannot cite is said in words. Use **bold** for key conclusions. Write densely — every sentence must carry insight, zero filler."""

STRUCTURE_RULES = (
    "STRUCTURE — what is computed and what you write:\n"
    "- Never state a confidence level (HIGH / MEDIUM / LOW or a number): it is computed from the "
    "headline record and rendered beside your direct answer.\n"
    "- The dissent you name under DISCUSSION is the twins listed as DISSENT under == POSITIONS ==, "
    "cited by handle. Do not promote a majority twin to dissenter or invent a minority.\n"
    "- Under SOURCE MATERIALS, describe only the classes and items listed under == EVIDENCE BY CLASS ==.\n"
    "- == WHAT WAS RUN == lists the tools that produced records and the tools that were not run. Where a "
    "tool that was not run bears on the recommendation (no lever simulated, no message tested, no journey "
    "mapped), say so in one plain clause under OUTCOME; never fill the gap with an estimate of what it would "
    "have shown. A record whose 'in words' line says nothing moved is reported as nothing moved, not as a "
    "shift of zero."
)

CLASS_LABELS = {
    "quant": "Statistics & datasets",
    "web": "Web pages & documents",
    "social": "Social & forum posts",
    "personal": "Client & personal material",
    "synthetic": "Model-written material",
}
CLASS_ORDER = ("quant", "web", "social", "personal", "synthetic")

_CONF_LINE_RE = re.compile(r"^\s*\**\s*confidence\s*:\s*\**\s*(high|medium|low)\b.*$", re.IGNORECASE | re.MULTILINE)
_CONF_INLINE_RE = re.compile(r"\s*\**\s*confidence\s*:\s*\**\s*(high|medium|low)\**[.,]?", re.IGNORECASE)


# ── direct answer ────────────────────────────────────────────────────────────

def confidence_band(score: Optional[float]) -> str:
    """The record's 5–95 score as the label the report always carried. Thresholds are fixed
    so the same score always reads the same: ≥70 HIGH, ≥45 MEDIUM, else LOW."""
    if score is None:
        return "LOW"
    s = float(score)
    return "HIGH" if s >= 70 else "MEDIUM" if s >= 45 else "LOW"


def strip_confidence_line(text: str) -> tuple[str, Optional[str]]:
    """Remove any confidence label the model wrote anyway. Returns (text, the band it claimed)
    so the claim can be kept for the audit trail without ever being shown."""
    claimed: Optional[str] = None
    m = _CONF_LINE_RE.search(text) or _CONF_INLINE_RE.search(text)
    if m:
        claimed = m.group(1).upper()
    out = _CONF_LINE_RE.sub("", text)
    out = _CONF_INLINE_RE.sub("", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip(), claimed


# ── discussion: positions and named dissent ──────────────────────────────────

def positions_from_answers(rows: Iterable[Any]) -> list[dict]:
    """The verdict probe's answers as `{agent_id, position, confidence, verdict}`; a twin who
    said it was not theirs to answer is left out (they are outside every denominator)."""
    out: list[dict] = []
    for r in rows:
        ans = getattr(r, "answer", None) if not isinstance(r, dict) else r.get("answer")
        ans = ans or {}
        if str(ans.get("can_answer") or "yes").lower() == "no":
            continue
        pos = str(ans.get("position") or "").strip().lower()
        if pos not in ("for", "against", "mixed"):
            continue
        agent_id = getattr(r, "agent_id", None) if not isinstance(r, dict) else r.get("agent_id")
        try:
            conf = int(ans.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0
        out.append({"agent_id": agent_id, "position": pos, "confidence": max(0, min(100, conf)),
                    "verdict": str(ans.get("verdict") or "").strip()[:300]})
    return out


def majority_of(positions: list[dict]) -> Optional[str]:
    if not positions:
        return None
    counts: dict[str, int] = {}
    for p in positions:
        counts[p["position"]] = counts.get(p["position"], 0) + 1
    # Ties break in a fixed order so the same answers always give the same majority.
    return max(("for", "against", "mixed"), key=lambda k: (counts.get(k, 0), -("for", "against", "mixed").index(k)))


def dissent_for(positions: list[dict], limit: int = 8) -> tuple[Optional[str], list[dict]]:
    """The majority position and the dissenters — every twin who did not hold it, the most
    confident first, so the named dissent is the population's own minority, not the model's pick."""
    maj = majority_of(positions)
    if maj is None:
        return None, []
    others = [p for p in positions if p["position"] != maj]
    # "mixed" is dissent from a clear majority; when the majority is itself "mixed" the two
    # committed sides are the dissent, strongest first.
    others.sort(key=lambda p: (-p["confidence"], p["position"], p["agent_id"] or ""))
    return maj, others[:limit]


def positions_block(positions: list[dict], handle_of_agent: dict[str, str], names: dict[str, str]) -> str:
    """The positions as the model sees them: the split, then the dissent by handle with the
    line each dissenter would be quoted on. The name is deliberately not shown beside the
    handle: given both, the model typed both, and the reader saw the name twice."""
    if not positions:
        return "(no verdict answers on file — describe the discussion from the transcript and name no dissent as computed)"
    maj, dissent = dissent_for(positions)
    n = len(positions)
    counts = {k: sum(1 for p in positions if p["position"] == k) for k in ("for", "against", "mixed")}
    lines = [f"Majority position: {maj} ({counts[maj]} of {n}); for {counts['for']}, against {counts['against']}, mixed {counts['mixed']}."]
    if dissent:
        lines.append("DISSENT (the twins who did not hold the majority position — name these, by handle):")
        for p in dissent:
            h = handle_of_agent.get(p["agent_id"] or "", "?")
            lines.append(f"- [[{h}]] — {p['position']} (confidence {p['confidence']}/100): \"{p['verdict']}\"")
    else:
        lines.append("DISSENT: none — every twin who answered held the majority position (say so; do not invent a minority).")
    return "\n".join(lines)


# ── source materials by role ─────────────────────────────────────────────────

def evidence_summary(rows: Iterable[Any], chunk_count: int = 0) -> list[dict]:
    """Evidence grouped by class in a fixed order: count, on-topic count, trust mix and the
    top items by relevance. Ingested text with no evidence row shows as its chunk count."""
    by_class: dict[str, list[Any]] = {}
    for e in rows:
        by_class.setdefault(str(getattr(e, "source_class", "") or "web"), []).append(e)
    out: list[dict] = []
    for cls in list(CLASS_ORDER) + [c for c in by_class if c not in CLASS_ORDER]:
        items = by_class.get(cls) or []
        if not items:
            continue
        items.sort(key=lambda e: (-(1 if getattr(e, "on_topic", False) else 0), -float(getattr(e, "relevance", 0) or 0)))
        trust: dict[str, int] = {}
        for e in items:
            t = str(getattr(e, "trust_tier", "") or "medium")
            trust[t] = trust.get(t, 0) + 1
        out.append({
            "class": cls,
            "label": CLASS_LABELS.get(cls, cls.title()),
            "count": len(items),
            "on_topic": sum(1 for e in items if getattr(e, "on_topic", False)),
            "trust": trust,
            "top": [{"id": getattr(e, "id", None), "title": (getattr(e, "title", None) or str(getattr(e, "source_ref", "") or ""))[:120],
                     "author": (getattr(e, "author", None) or "")[:60], "source_ref": str(getattr(e, "source_ref", "") or "")[:300],
                     "trust": str(getattr(e, "trust_tier", "") or "medium")} for e in items[:5]],
        })
    if chunk_count:
        out.append({"class": "ingested", "label": "Ingested text & documents", "count": int(chunk_count), "on_topic": int(chunk_count),
                    "trust": {}, "top": []})
    return out


def frame_summary(frame: Optional[dict], summary_line: str) -> dict:
    rep = (frame or {}).get("report") if isinstance(frame, dict) else None
    dims = []
    for d in ((frame or {}).get("dimensions") or []):
        tg = ((frame or {}).get("targets") or {}).get(d.get("key")) or {}
        dims.append({"key": d.get("key"), "label": d.get("label"), "status": tg.get("status", "missing"),
                     "source": tg.get("source"), "geography": tg.get("geography"), "year": tg.get("year")})
    return {"level": (rep or {}).get("level") or "none", "summary": summary_line, "dimensions": dims,
            "estimated": list((rep or {}).get("estimated") or []), "thin_cells": list((rep or {}).get("thin_cells") or [])}


def evidence_block(summary: list[dict]) -> str:
    """The evidence as the model sees it, class by class."""
    if not summary:
        return "(no evidence on file — say so under SOURCE MATERIALS; do not describe material that is not there)"
    lines = []
    for s in summary:
        head = f"{s['label']}: {s['count']} item(s)"
        if s.get("trust"):
            head += ", trust " + ", ".join(f"{k} {v}" for k, v in sorted(s["trust"].items()))
        lines.append(head)
        for t in s.get("top") or []:
            who = f" — {t['author']}" if t.get("author") else ""
            lines.append(f"  · {t['title']}{who}")
    return "\n".join(lines)


# ── outcome: the computed caveats ────────────────────────────────────────────

def caveats_from_records(records: list[dict], cited_ids: list[str]) -> list[dict]:
    """The union of the cited records' caveats (all records when none is cited), deduplicated
    in first-seen order with the synthetic-population statement kept last; each carries the
    record ids it came from so the reader can open them."""
    chosen = [r for r in records if r.get("id") in set(cited_ids)] or list(records)
    seen: dict[str, list[str]] = {}
    order: list[str] = []
    for r in chosen:
        for c in r.get("caveats") or []:
            key = c.strip()
            if not key:
                continue
            if key not in seen:
                seen[key] = []
                order.append(key)
            if r.get("id") and r["id"] not in seen[key]:
                seen[key].append(r["id"])
    synthetic = [c for c in order if c.lower().startswith("synthetic population")]
    rest = [c for c in order if c not in synthetic]
    return [{"text": c, "record_ids": seen[c]} for c in rest + synthetic]


def barriers_from_records(records: list[dict]) -> Optional[dict]:
    """The newest barriers record's ranked list (brief L6-05), for the report's *What's in the
    way* block: theme, count, share, weight, removals, the twin ids and the evidence behind each."""
    for r in records:
        if r.get("barriers"):
            return {"record_id": r.get("id"), "outcome": r.get("outcome") or r.get("question") or "", "n": int((r.get("estimate") or {}).get("n") or 0),
                    "items": [{"theme": b.get("theme"), "count": b.get("count", 0), "share": b.get("share"), "weight_mean": b.get("weight_mean"),
                               "removals": [x.get("value") for x in (b.get("removals") or [])][:3], "agent_ids": (b.get("agent_ids") or [])[:12],
                               "evidence": (b.get("evidence") or [])[:5]} for b in r["barriers"][:7]]}
    return None


def candidates_from_records(records: list[dict]) -> Optional[dict]:
    """The newest journey record's candidate outcomes (brief L7-01), for the report's *Where the
    population drops off* block: the funnel and, per candidate, the step, the conversion, who is
    stuck and the top barriers with their twins."""
    for r in records:
        if r.get("candidates") or r.get("funnel"):
            hc = r.get("headcount") or {}
            return {"record_id": r.get("id"), "n": int((r.get("estimate") or {}).get("n") or 0),
                    "headcount": {"available": bool(hc.get("available")), "sentence": hc.get("sentence") or "", "reason": hc.get("reason") or "",
                                  "basis": ((hc.get("denominator") or {}).get("basis") or ("client_supplied" if hc.get("anchors") else "")), "weighted": bool(hc.get("weighted"))},
                    "funnel": [{"label": f.get("label"), "share": f.get("share"), "reached": f.get("reached"), "people": f.get("people"), "people_low": f.get("people_low"), "people_high": f.get("people_high")}
                               for f in (r.get("funnel") or [])],
                    "items": [{"id": c.get("id"), "rank": c.get("rank"), "from": (c.get("from") or {}).get("label"), "to": (c.get("to") or {}).get("label"),
                               "label": c.get("label"), "n": c.get("n"), "stuck": c.get("stuck"), "conversion": c.get("conversion"), "low": c.get("low"), "high": c.get("high"),
                               "gap": c.get("gap"), "equity_gap": (c.get("equity") or {}).get("gap") if (c.get("equity") or {}).get("available") else None,
                               "stuck_people": c.get("stuck_people"), "stuck_low": c.get("stuck_low"), "stuck_high": c.get("stuck_high"), "at_risk_people": c.get("at_risk_people"), "basis": c.get("basis") or "",
                               "movability": {k: (c.get("movability") or {}).get(k) for k in ("scored", "movable_share", "movable_count", "system_share", "structural_share", "unscored_share", "movable_people", "movable_low", "movable_high", "levers")},
                               "barriers": [{"theme": b.get("theme"), "count": b.get("count", 0), "weight_mean": b.get("weight_mean"),
                                             "removals": [x.get("value") if isinstance(x, dict) else x for x in (b.get("removals") or [])][:2],
                                             "reach": b.get("reach") or "", "lever": b.get("lever") or "", "actor": b.get("actor") or "",
                                             "agent_ids": (b.get("agent_ids") or [])[:8]} for b in (c.get("barriers") or [])[:3]]}
                              for c in (r.get("candidates") or [])[:7]]}
    return None


def commitments_from_records(records: list[dict]) -> Optional[list[dict]]:
    """Every commitment record (brief L7-08), for the report's *Committed outcomes* block: the
    frozen forecast, what it rested on, the target and the observed result against it."""
    out = []
    for r in records:
        cm = r.get("commitment")
        if not cm:
            continue
        est = r.get("estimate") or {}
        out.append({"record_id": r.get("id"), "label": r.get("label"), "from": cm.get("from"), "to": cm.get("to"), "status": cm.get("status"),
                    "committed_by": cm.get("committed_by"), "committed_at": cm.get("committed_at"), "frozen_at": cm.get("frozen_at"),
                    "conversion": est.get("value"), "low": est.get("low"), "high": est.get("high"), "n": est.get("n"), "stuck": cm.get("stuck"),
                    "stuck_people": cm.get("stuck_people"), "stuck_low": cm.get("stuck_low"), "stuck_high": cm.get("stuck_high"), "basis": cm.get("basis"),
                    "build_id": cm.get("build_id"), "population_n": cm.get("population_n"), "frame_level": cm.get("frame_level"),
                    "evidence_items": cm.get("evidence_items"), "rules": cm.get("rules"), "related": cm.get("related") or [],
                    "target": cm.get("target") or {}, "comparison": cm.get("comparison"), "observations": len(cm.get("observed") or []),
                    "closed_by": cm.get("closed_by"), "close_note": cm.get("close_note")})
    return out or None


# ── what was run, and what was not ───────────────────────────────────────────
# The report used to look the same whatever had been done in the session: the same headers,
# the same reading order, tiles at zero where a tool had never run. Now the structure says which
# tools produced records and which did not, so the page (and the model) can say "not run"
# instead of showing nothing or a zero.

#: key → (reader label, what it would add, the Lab instrument that runs it, needs a journey first)
TOOLS: tuple[tuple[str, str, str, Optional[str], bool], ...] = (
    ("debate", "debate", "what the twins argued", None, False),
    ("verdict", "verdict poll", "the population's answer to the question", "verdict", False),
    ("journey", "journey", "where people drop off on the way to the outcome", "journey", False),
    ("barriers", "barriers ranking", "what stands in the way, ranked by the twins", "barriers", False),
    ("lever", "lever run", "what a stated intervention would shift", "journey", True),
    ("targeting", "behaviour ranking", "which behaviour the twins respond to most", "journey", True),
    ("messaging", "message test", "which framing lands with the twins at risk", "journey", True),
    ("commitment", "committed outcome", "a frozen forecast to check against results later", "journey", True),
    ("experiment", "A/B test", "one framing against another", "experiment", False),
    ("probe", "Lab result", "a survey, an ask or a purchase-intent read", None, False),
)


def _plural(n: int, one: str, many: Optional[str] = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def coverage(records: list[dict], *, posts: int = 0, evidence_items: int = 0) -> dict:
    """Which tools produced records (with a count and the plain phrase for the line under the
    direct answer) and which did not (with what each would add and the Lab instrument to run)."""
    by_kind: dict[str, list[dict]] = {}
    for r in records:
        kind = str(r.get("kind") or "")
        if kind == "headline":
            kind = "verdict"
        elif kind == "probe":
            kind = str(r.get("instrument") or "probe")
            if kind not in ("journey", "barriers"):
                kind = "probe"
        by_kind.setdefault(kind, []).append(r)
    ran: list[dict] = []
    if posts:
        ran.append({"key": "debate", "label": "debate", "count": posts, "phrase": f"a debate of {_plural(posts, 'post')}", "record_ids": []})
    if evidence_items:
        ran.append({"key": "evidence", "label": "evidence", "count": evidence_items, "phrase": _plural(evidence_items, "evidence item"), "record_ids": []})
    not_run: list[dict] = []
    has_journey = bool(by_kind.get("journey"))
    for key, label, adds, instrument, needs_journey in TOOLS:
        if key == "debate":
            continue
        recs = by_kind.get(key) or []
        if recs:
            k = len(recs)
            if key == "verdict":
                n = int(((recs[0].get("estimate") or {}).get("n")) or 0)
                phrase = f"a verdict poll of {_plural(n, 'twin')}"
            elif key == "journey":
                cands = len(recs[0].get("candidates") or [])
                phrase = f"a journey with {_plural(cands, 'candidate step')}" + (f" ({k} runs)" if k > 1 else "")
            elif key == "barriers":
                bars = len(recs[0].get("barriers") or [])
                phrase = f"a barriers ranking ({_plural(bars, 'barrier')})" + (f" ({k} runs)" if k > 1 else "")
            else:
                phrase = _plural(k, label)
            ran.append({"key": key, "label": label, "count": k, "phrase": phrase, "record_ids": [r.get("id") for r in recs]})
        elif key not in ("probe", "experiment"):
            not_run.append({"key": key, "label": label, "adds": adds, "instrument": instrument,
                            "needs": "a journey first" if needs_journey and not has_journey else None})
    return {"ran": ran, "not_run": not_run}


def coverage_line(cov: dict) -> tuple[str, str]:
    """The two halves of the sentence under the direct answer: 'Based on …' and 'Not run: …'."""
    based = ", ".join(x["phrase"] for x in cov.get("ran") or []) or "the session's material only"
    missing = ", ".join(x["label"] + (f" (needs {x['needs']})" if x.get("needs") else "") for x in cov.get("not_run") or [])
    return based, missing


def coverage_block(cov: dict) -> str:
    """== WHAT WAS RUN == as the model sees it."""
    based, missing = coverage_line(cov)
    return f"Ran: {based}.\nNot run: {missing or 'nothing — every tool has a record'}." + (
        "\nA tool that was not run has no record: say it was not simulated where it matters; do not estimate what it would have shown." if missing else "")


# ── follow-up questions, from the records ────────────────────────────────────

def follow_ups(records: list[dict], positions: list[dict], names: Optional[dict[str, str]] = None, limit: int = 5) -> list[str]:
    """Questions a reader would ask next, written from what the records actually found: the step
    where most stall, the top barrier, the strongest dissenter, the best lever, the widest equity
    gap, a message test that moved nobody. Never generic while there is a record to ask about."""
    out: list[str] = []
    names = names or {}
    journey = next((r for r in records if r.get("candidates")), None)
    if journey:
        worst = max(journey["candidates"], key=lambda c: int(c.get("stuck") or 0), default=None)
        if worst and int(worst.get("stuck") or 0) > 0:
            out.append(f"Why do {worst.get('stuck')} of {worst.get('n')} twins stall at '{(worst.get('from') or {}).get('label')} → {(worst.get('to') or {}).get('label')}'?")
    bars = next((r for r in records if r.get("barriers")), None)
    if bars and bars["barriers"]:
        top = bars["barriers"][0]
        out.append(f"What would it take to remove '{top.get('theme')}' for the {_plural(int(top.get('count') or 0), 'twin')} who raised it?")
    maj, dissent = dissent_for(positions)
    if dissent:
        nm = names.get(dissent[0].get("agent_id") or "")
        if nm:
            out.append(f"What would have to be true for {nm} to be right?")
    levers = [r for r in records if r.get("lever") and (r.get("estimate") or {}).get("significant") and (r.get("estimate") or {}).get("value") is not None]
    if levers:
        best = max(levers, key=lambda r: float(r["estimate"]["value"]))
        # The step is in the label ("Lever: x — shift at A → B"); the lever block carries no step labels.
        step = str(best.get("label") or "").split(" → ")[-1].strip() if " → " in str(best.get("label") or "") else ""
        out.append(f"Where does the gain from '{(best['lever'].get('rule') or {}).get('lever')}' go after '{step or 'that step'}'?")
    gaps = [r for r in records if (r.get("equity") or {}).get("available") and (r.get("equity") or {}).get("significant")]
    if gaps:
        g = max(gaps, key=lambda r: abs(float((r.get("equity") or {}).get("gap") or 0)))
        # A record label can carry the whole question ("What's in the way of: Will …"); ask about the part before it.
        short = str(g.get("label") or "").split(": ")[0].split(" — ")[0]
        out.append(f"Why do the most deprived twins differ so much from the least deprived on '{short}'?")
    flat = next((r for r in records if r.get("messaging") and not (r.get("messaging") or {}).get("any_significant") and (r.get("messaging") or {}).get("messages")), None)
    if flat:
        step = str(flat.get("label") or "").replace("Messages tested at ", "") or "that step"
        out.append(f"Why did none of the {_plural(len(flat['messaging']['messages']), 'message')} tested at '{step}' move anyone?")
    if len(out) < 3:
        out += ["What is the single strongest objection in the debate, and who holds it?",
                "Which twins changed their mind during the debate, and why?",
                "What would the least convinced twins need to see before they moved?"]
    seen: list[str] = []
    for q in out:
        if q not in seen:
            seen.append(q)
    return seen[:limit]


# ── assembly ─────────────────────────────────────────────────────────────────

def build_structure(*, session_query: str, records: list[dict], headline: Optional[dict], positions: list[dict],
                    evidence: list[dict], frame: dict, cited_record_ids: list[str], claimed_band: Optional[str],
                    figures: Optional[dict] = None, activity: Optional[dict] = None, names: Optional[dict[str, str]] = None) -> dict:
    """Everything the rendered report reads from data rather than prose. `activity` carries the
    counts no record holds (posts in the debate, evidence items) for the coverage line."""
    maj, dissent = dissent_for(positions)
    counts = {k: sum(1 for p in positions if p["position"] == k) for k in ("for", "against", "mixed")}
    n = len(positions)
    conf = (headline or {}).get("confidence") or {}
    score = conf.get("score")
    act = activity or {}
    cov = coverage(records, posts=int(act.get("posts") or 0), evidence_items=int(act.get("evidence_items") or 0))
    return {
        "version": 2,
        "direct_answer": {
            "record_id": (headline or {}).get("id"),
            "confidence": {"band": confidence_band(score) if headline else None, "score": score, "drivers": list(conf.get("drivers") or [])},
            "claimed_band": claimed_band,
        },
        "question": {
            "session_query": session_query,
            "instrument": (headline or {}).get("instrument"),
            # None, not 0, when no verdict poll ran: nobody was asked.
            "asked": int(((headline or {}).get("provenance") or {}).get("agents") or 0) if headline else None,
            "answered": int(((headline or {}).get("estimate") or {}).get("n") or 0) if headline else None,
        },
        "coverage": cov,
        "follow_ups": follow_ups(records, positions, names),
        "source_materials": {"evidence": evidence, "frame": frame},
        "discussion": {
            "record_id": (headline or {}).get("id"),
            "positions": [{"value": k, "count": counts[k], "share": round(counts[k] / n, 4) if n else 0.0} for k in ("for", "against", "mixed")],
            "n": n,
            "majority": maj,
            "dissent": dissent,
        },
        "records": {"all": [r.get("id") for r in records], "cited": list(cited_record_ids)},
        "outcome": {"caveats": caveats_from_records(records, cited_record_ids), "barriers": barriers_from_records(records),
                    "candidates": candidates_from_records(records),
                    # L7-08: the frozen forecasts a client has committed to, and the observed results against them.
                    "commitments": commitments_from_records(records)},
        # L6-03: which source figures the prose cites, and every number it typed with no source.
        "figures": figures or {"facts_cited": [], "items_cited": [], "unsourced": []},
    }


# ── loaders ──────────────────────────────────────────────────────────────────

async def load_positions(probe_id: Optional[str]) -> list[dict]:
    if not probe_id:
        return []
    async with dbm.AsyncSessionLocal() as db:
        rows = (await db.execute(select(ProbeAnswer).where(ProbeAnswer.probe_id == probe_id))).scalars().all()
    return positions_from_answers(rows)


async def load_evidence(session_id: str) -> list[dict]:
    async with dbm.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Evidence).where(Evidence.session_id == session_id, Evidence.excluded == False)  # noqa: E712
        )).scalars().all()
        chunks = (await db.execute(select(KnowledgeGraph.chunks).where(KnowledgeGraph.session_id == session_id))).scalar_one_or_none()
    return evidence_summary(rows, chunk_count=len(chunks or []) if not rows else 0)
