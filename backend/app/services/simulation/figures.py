"""Source figures with a provenance class (brief L6-03): every number a report quotes from the
material is cited, carries its class, and is visibly different from a number counted from the
twins — and a number the model typed with no source is flagged, not shown as fact.

Three kinds of figure can appear in a report:

  * **Population figures** — counted from the twins' answers: the outcome records (L6-01),
    class `model_inference`. Cited `[[record:<id>]]`.
  * **Source figures** — read from the material. Two ledgers are handed to the model, numbered
    like the roster and the records: the typed statistics the Studio extracted (`F1 … Fn`:
    value, what it measures, who, where, year, source, class) and the evidence items on file
    (`E1 … En`: class, title, source, excerpt). A document figure must cite a fact
    (`[[fact:<evidence id>#<k>]]`) or the item it was read in (`[[evidence:<id>]]`).
  * **Unsourced figures** — a number-shaped token in the prose with no citation in its
    sentence. `mark_unsourced` wraps it as `[[unsourced:<token>]]` so the reader sees it as
    the model's own, greyed and flagged, never as a finding.

The provenance vocabulary is the brief's L1-05 list, already used by the scoping tagger
(`classify_chunk`); `class_for_evidence` applies the same host rules to an evidence row.

Pure functions except `load_ledger`.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from sqlalchemy import select

from app.core import database as dbm
from app.models.evidence import Evidence
from app.services.scoping.tagger import _OFFICIAL_HOSTS, _PEER_HOSTS

PROVENANCE_CLASSES = ("official_statistic", "peer_reviewed", "grey_literature", "commissioned_research",
                      "client_data", "social_signal", "model_inference")
CLASS_LABELS = {
    "official_statistic": "Official statistic", "peer_reviewed": "Peer-reviewed", "grey_literature": "Grey literature",
    "commissioned_research": "Commissioned research", "client_data": "Client data", "social_signal": "Social signal",
    "model_inference": "Model-inferred",
}

FACT_HANDLE_RE = re.compile(r"\[\[\s*(F\d+)\s*\]\]", re.IGNORECASE)
ITEM_HANDLE_RE = re.compile(r"\[\[\s*(E\d+)\s*\]\]", re.IGNORECASE)
FACT_TOKEN_RE = re.compile(r"\[\[fact:([A-Za-z0-9-]{1,64})#(\d+)\]\]")
ITEM_TOKEN_RE = re.compile(r"\[\[evidence:([A-Za-z0-9-]{1,64})\]\]")
UNSOURCED_TOKEN_RE = re.compile(r"\[\[unsourced:([^\]]+)\]\]")
_ANY_TOKEN_RE = re.compile(r"\[\[[^\]]*\]\]")

SOURCE_FIGURE_RULES = (
    "SOURCE FIGURES — numbers from the material, with their provenance:\n"
    "- A figure read from the material (a statistic, a price, a finding) is cited right after it: "
    "[[F3]] for a typed statistic under == SOURCE FIGURES ==, or [[E5]] for the document it was read "
    "in under == SOURCE DOCUMENTS ==. \"Obesity prevalence is 34% [[F3]]\"; \"the guideline caps BMI at 35 [[E2]]\".\n"
    "- Prefer a fact handle to a document handle: the fact carries the exact value, year and source.\n"
    "- A number with no record, fact or document behind it is flagged to the reader as unsourced. "
    "If you cannot cite it, say it in words instead.\n"
    "- Never invent a handle. Only the handles listed exist."
)


# ── classes ──────────────────────────────────────────────────────────────────

def class_for_evidence(e: Any) -> str:
    """The provenance class of an evidence row: the same rules the scoping tagger applies to a
    chunk header, so a page reads the same class everywhere."""
    cls = str(getattr(e, "source_class", "") or "web").lower()
    if cls == "quant":
        return "official_statistic"
    if cls == "social":
        return "social_signal"
    if cls == "personal":
        return "client_data"
    if cls == "synthetic":
        return "model_inference"
    ref = f"{getattr(e, 'source_ref', '') or ''} {getattr(e, 'author', '') or ''}".lower()
    if any(h in ref for h in _PEER_HOSTS):
        return "peer_reviewed"
    if any(h in ref for h in _OFFICIAL_HOSTS):
        return "official_statistic"
    return "grey_literature"


# ── the ledger ───────────────────────────────────────────────────────────────

def ledger_from_evidence(rows: Iterable[Any], *, max_facts: int = 60, max_items: int = 40) -> dict:
    """`{facts, items}` from evidence rows: typed statistics first (on-topic, most relevant
    first), then the items themselves in the same order, each with its class."""
    ordered = sorted(rows, key=lambda e: (-(1 if getattr(e, "on_topic", False) else 0), -float(getattr(e, "relevance", 0) or 0)))
    facts: list[dict] = []
    items: list[dict] = []
    for e in ordered:
        cls = class_for_evidence(e)
        eid = getattr(e, "id", "") or ""
        st = getattr(e, "structured", None) or {}
        source = str((st.get("source_label") if isinstance(st, dict) else None) or getattr(e, "author", "") or "")
        if isinstance(st, dict) and st.get("facts"):
            for k, f in enumerate(st.get("facts") or []):
                if not isinstance(f, dict) or not re.search(r"\d", str(f.get("value") or "")):
                    continue
                if len(facts) >= max_facts:
                    break
                facts.append({
                    "id": f"{eid}#{k}", "evidence_id": eid, "k": k,
                    "value": str(f.get("value") or "").strip()[:40], "statistic": str(f.get("statistic") or "").strip()[:160],
                    "group": str(f.get("group") or "").strip()[:80], "geography": str(f.get("geography") or "").strip()[:80],
                    "year": str(f.get("year") or "").strip()[:20], "quote": str(f.get("quote") or "").strip()[:300],
                    "source": source[:80], "source_ref": str(getattr(e, "source_ref", "") or "")[:300], "title": (getattr(e, "title", None) or "")[:120],
                    "provenance_class": cls, "trust_tier": str(getattr(e, "trust_tier", "") or "medium"),
                })
        if len(items) < max_items:
            items.append({
                "id": eid, "provenance_class": cls, "trust_tier": str(getattr(e, "trust_tier", "") or "medium"),
                "title": (getattr(e, "title", None) or str(getattr(e, "source_ref", "") or ""))[:140],
                "author": (getattr(e, "author", None) or "")[:60], "source_ref": str(getattr(e, "source_ref", "") or "")[:300],
                "published_at": (getattr(e, "published_at", None) or "")[:40], "on_topic": bool(getattr(e, "on_topic", False)),
                "excerpt": (getattr(e, "text", None) or "")[:400],
            })
    return {"facts": facts, "items": items}


def ledger_block(ledger: dict) -> tuple[str, str, dict[str, str]]:
    """(source figures text, source documents text, handle → token) for the prompt."""
    handles: dict[str, str] = {}
    flines: list[str] = []
    for k, f in enumerate(ledger.get("facts") or [], 1):
        h = f"F{k}"
        handles[h.lower()] = f"[[fact:{f['id']}]]"
        where = ", ".join(x for x in (f.get("group"), f.get("geography"), f.get("year")) if x)
        flines.append(f"[[{h}]] {f['value']} — {f['statistic']}" + (f" ({where})" if where else "")
                      + f" — {f.get('source') or f.get('title')} [{CLASS_LABELS.get(f['provenance_class'], f['provenance_class'])}]"
                      + (f" \"{f['quote']}\"" if f.get("quote") else ""))
    ilines: list[str] = []
    for k, it in enumerate(ledger.get("items") or [], 1):
        h = f"E{k}"
        handles[h.lower()] = f"[[evidence:{it['id']}]]"
        who = " — ".join(x for x in (it.get("author"), it.get("published_at")) if x)
        ilines.append(f"[[{h}]] [{CLASS_LABELS.get(it['provenance_class'], it['provenance_class'])}, trust {it['trust_tier']}] {it['title']}"
                      + (f" ({who})" if who else "") + (f": {it['excerpt'][:240]}" if it.get("excerpt") else ""))
    return (
        "\n".join(flines) if flines else "(no typed statistics on file — quote a document figure with [[E…]] or say it in words)",
        "\n".join(ilines) if ilines else "(no evidence items on file)",
        handles,
    )


def resolve_handles(text: str, handles: dict[str, str]) -> str:
    """`[[F2]]` / `[[E3]]` → stable tokens; a handle that names nothing is dropped."""
    def sub(m: re.Match) -> str:
        return handles.get(m.group(1).lower(), "")
    out = FACT_HANDLE_RE.sub(sub, text)
    out = ITEM_HANDLE_RE.sub(sub, out)
    return re.sub(r"[ \t]{2,}", " ", out)


def cited_ids(text: str) -> tuple[list[str], list[str]]:
    facts = [f"{m.group(1)}#{m.group(2)}" for m in FACT_TOKEN_RE.finditer(text)]
    items = [m.group(1) for m in ITEM_TOKEN_RE.finditer(text)]
    return list(dict.fromkeys(facts)), list(dict.fromkeys(items))


# ── the unsourced check ──────────────────────────────────────────────────────

#: What counts as a figure: a percentage, money, a magnitude ("3.1 million", "£31k"), points.
_FIGURE_RE = re.compile(
    r"(?<![\w#\-])(?:"
    r"[£$€]\s?\d[\d,]*(?:\.\d+)?\s?(?:k|m|bn|million|billion|thousand)?"      # money
    r"|\d[\d,]*(?:\.\d+)?\s?%"                                                # percent
    r"|\d[\d,]*(?:\.\d+)?\s?(?:million|billion|thousand|bn)\b"                # magnitude
    r"|\d[\d,]*(?:\.\d+)?\s?(?:points?|pts)\b"                                # points
    r")(?![\w%])",
    re.IGNORECASE,
)
_CI_RE = re.compile(r"95\s?%\s?CI", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n")


def mark_unsourced(text: str) -> tuple[str, list[str]]:
    """Wrap every figure with no citation in its sentence as `[[unsourced:<figure>]]`.
    Citation tokens are masked first so their ids are never read as figures; a `95% CI` is
    not a figure; a year is not a figure. Returns (text, the figures flagged)."""
    flagged: list[str] = []
    out_parts: list[str] = []
    pos = 0
    # Walk sentence by sentence so "sourced" means a citation in the same sentence.
    for m in _SENTENCE_SPLIT_RE.finditer(text + "\n"):
        sentence = text[pos:m.start()] if m.start() <= len(text) else text[pos:]
        sep = text[m.start():m.end()] if m.end() <= len(text) else ""
        pos = m.end()
        if not sentence:
            out_parts.append(sep)
            continue
        has_cite = bool(_ANY_TOKEN_RE.search(sentence))
        if has_cite:
            out_parts.append(sentence + sep)
            continue
        masked = _CI_RE.sub(lambda mm: "·" * len(mm.group(0)), sentence)
        rebuilt: list[str] = []
        last = 0
        for fm in _FIGURE_RE.finditer(masked):
            tok = sentence[fm.start():fm.end()]
            rebuilt.append(sentence[last:fm.start()])
            rebuilt.append(f"[[unsourced:{tok.strip()}]]")
            flagged.append(tok.strip())
            last = fm.end()
        rebuilt.append(sentence[last:])
        out_parts.append("".join(rebuilt) + sep)
    return "".join(out_parts).rstrip("\n") + ("\n" if text.endswith("\n") else ""), flagged


# ── loading ──────────────────────────────────────────────────────────────────

async def load_ledger(session_id: str) -> dict:
    async with dbm.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Evidence).where(Evidence.session_id == session_id, Evidence.excluded == False)  # noqa: E712
        )).scalars().all()
    return ledger_from_evidence(rows)
