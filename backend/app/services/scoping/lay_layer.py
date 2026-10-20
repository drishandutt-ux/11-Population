"""The lay layer (2026-10-20): street-level versions of the session's material, so a twin whose
scope hides the professional and technical items still knows real things in its own register —
instead of nothing, which the model then filled from memory (a chemist on Church Street).

After tagging, every unit above lay register is rewritten once by the fast model as what an
ordinary person in its place would plausibly have picked up — from local news, friends, the GP,
the chemist: a sentence or two, everyday words, the substance kept, figures rounded the way
people remember them. Units the public could not plausibly know at all (a methods appendix, an
internal audit figure, a commissioning memo) are skipped (`knowable: no`). The rewrites are
units of their own in the same snapshot: register lay, role patient + public, segment empty
(common knowledge, not a cohort's), geography, condition, stage and time copied from the
source, provenance and trust the source's, `facets.layer = "lay"` and `facets.derived_from =
<source unit id>`. Their route reads "from what people say round here".

Pure helpers (`candidates`, `rows_from`) do no I/O; `derive` is the model call.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from app.services.evidence.llm import analyze

from .registry import REGISTER_LEVELS

LAY_BATCH = 8
LAY_CONCURRENCY = 4
LAY_MAX = 60          # rewrites per tagging run — the professional / technical half of a 240-unit graph at most
LAY_ROUTE = "from what people say round here"

_SYSTEM = """You turn specialist material into what an ordinary member of the public living in the place named would
plausibly have picked up about it — from local news, friends and family, the GP, the chemist, work. For every unit:

- knowable: "yes" if some version of this could reach an ordinary person (a figure in the news, a waiting time people
  talk about, a service that opened or closed, a drug people have heard of, what the chemist or GP tells people);
  "no" if the public could not plausibly know it at all (trial methods, statistical detail, internal audits and
  commissioning papers, professional guidance, prescribing rules) — then leave `lay` empty.
- lay: one or two sentences, everyday words, in the voice of what people say ("round here you wait weeks for the GP",
  "about a third of adults are a lot overweight, the news said"). Keep the substance; round the figures the way people
  remember them; no jargon, no source names, no citations, nothing a person would not actually say. Never add a fact
  that is not in the unit. Do not name streets, surgeries or shops unless the unit does.

Answer for every index you are given, in order."""


def _schema():
    from app.services.evidence.llm import arr, enum, i, obj, s
    return obj({"units": arr(obj({"index": i("the unit's index in the list"), "knowable": enum(["yes", "no"]), "lay": s("the lay version, or empty when not knowable")}))})


def candidates(units: list[dict], limit: int = LAY_MAX) -> list[int]:
    """Indexes of the units worth a lay version: professional / technical register, real sources
    first (the debate's own posts are already in a lay voice), most recent last in the list so a
    cap keeps the newest."""
    idx = [k for k, u in enumerate(units) if (u.get("facets") or {}).get("register") in ("professional", "technical")
           and u.get("provenance_class") != "model_inference" and (u.get("text") or "").strip()]
    return idx[-limit:]


def rows_from(units: list[dict], results: dict[int, tuple[str, str]], *, session_id: str, snapshot_id: str, now: Any) -> list[dict]:
    """Lay units for every knowable rewrite: {id, text, source_ref, provenance_class, trust_tier, facets}."""
    out = []
    for k, (knowable, lay) in results.items():
        if knowable != "yes" or not (lay or "").strip() or not (0 <= k < len(units)):
            continue
        src = units[k]
        f = dict(src.get("facets") or {})
        facets = {
            "geography": list(f.get("geography") or []), "role": ["patient", "public"], "channel": [],
            "condition": list(f.get("condition") or []), "stage": list(f.get("stage") or []), "segment": [],
            "register": "lay", "layer": "lay", "derived_from": src.get("id") or "", "project": session_id,
        }
        if f.get("time"):
            facets["time"] = f["time"]
        out.append({"id": str(uuid.uuid4()), "session_id": session_id, "snapshot_id": snapshot_id, "text": " ".join(lay.split())[:600],
                    "source_ref": src.get("source_ref") or "", "provenance_class": src.get("provenance_class") or "grey_literature",
                    "trust_tier": src.get("trust_tier") or "medium", "facets": facets, "created_at": now})
    return out


def _unit_line(k: int, u: dict) -> str:
    f = u.get("facets") or {}
    places = ", ".join(f.get("geography") or []) or "the area"
    return f"{k}. [place: {places}] {(u.get('text') or '')[:700]}"


async def derive_batch(units: list[dict], idx: list[int], *, session_id: str, model: Optional[str]) -> dict[int, tuple[str, str]]:
    user = "UNITS:\n" + "\n\n".join(_unit_line(k, units[k]) for k in idx)
    res = await analyze(_schema(), _SYSTEM, user, session_id=session_id, label="lay_layer", model=model, max_tokens=4000)
    out: dict[int, tuple[str, str]] = {}
    for r in res.get("units", []) or []:
        try:
            k = int(r.get("index"))
        except (TypeError, ValueError):
            continue
        if k in idx:
            out[k] = (str(r.get("knowable") or "no"), str(r.get("lay") or ""))
    return out


async def derive(units: list[dict], *, session_id: str, snapshot_id: str, now: Any, model: Optional[str] = None) -> list[dict]:
    """The lay rows for a freshly tagged set of units (each with its id, text, facets, provenance,
    trust, source_ref). A failed batch simply yields no rows for its units."""
    idx = candidates(units)
    if not idx:
        return []
    batches = [idx[k:k + LAY_BATCH] for k in range(0, len(idx), LAY_BATCH)]
    sem = asyncio.Semaphore(LAY_CONCURRENCY)
    results: dict[int, tuple[str, str]] = {}

    async def one(b: list[int]) -> None:
        async with sem:
            try:
                results.update(await derive_batch(units, b, session_id=session_id, model=model))
            except Exception as e:  # noqa: BLE001
                print(f"[scoping.lay_layer] batch failed: {type(e).__name__}: {e}")

    await asyncio.gather(*[one(b) for b in batches])
    return rows_from(units, results, session_id=session_id, snapshot_id=snapshot_id, now=now)


__all__ = ["LAY_ROUTE", "LAY_MAX", "candidates", "rows_from", "derive", "derive_batch", "REGISTER_LEVELS"]
