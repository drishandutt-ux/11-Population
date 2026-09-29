"""Headcounts — the gap in individuals, not percentages (brief L7-02).

A Journey result is shares: the share of the population that reached each step and, at every
drop-off, the share who get through. The brief wants the same thing in people — *individuals
with unmet need* is the currency a partnership negotiates in. This module multiplies the shares
through a denominator and never invents one:

  * the **denominator** is the in-scope slice the Population Studio read from the statistics
    on file (`frame.sizing.sam`, with its source and year; a share is multiplied through the
    place total `tam`), or a figure the analyst typed with a source (`spec.denominator`,
    labelled *client supplied*). With neither, headcounts are simply unavailable and the
    result says so — the shares stand on their own.
  * a **known headcount for a step** (`stages[].people`, with a source) is held fixed; the
    steps after it are scaled from it by the panel's shares, so a client's own channel figure
    anchors the steps it can see and the panel fills in the ones it cannot.
  * where the population carries **frame weights** (L2-02), the weighted share is used so the
    headcount follows the published distributions rather than the panel mix; the interval is
    the Wilson interval at the effective sample size.

Every headcount carries its basis (official statistic · client supplied · anchored on a client
figure) so a reader can tell a published denominator from a typed one.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.services.measurement import stats

BASIS_OFFICIAL = "official_statistic"
BASIS_CLIENT = "client_supplied"
BASIS_ANCHORED = "client_anchored"

_NUM = re.compile(r"(\d[\d,]*\.?\d*)\s*(%|per\s*cent|percent|million|mn|m\b|thousand|k\b|bn|billion)?", re.IGNORECASE)


def parse_figure(text: Any) -> Optional[dict]:
    """'141,000' → count 141000; '1.2 million' → count 1200000; '26%' → share 0.26. None when
    no number can be read."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return {"kind": "count", "value": float(text)} if text > 0 else None
    m = _NUM.search(str(text or ""))
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = (m.group(2) or "").lower().replace(" ", "")
    if unit in ("%", "percent", "percent", "percent") or unit.startswith("per"):
        return {"kind": "share", "value": v / 100.0} if 0 < v <= 100 else None
    mult = {"million": 1e6, "mn": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3, "bn": 1e9, "billion": 1e9}.get(unit, 1.0)
    v *= mult
    return {"kind": "count", "value": v} if v > 0 else None


def denominator_from_frame(frame: Optional[dict]) -> Optional[dict]:
    """The in-scope slice from the Studio's sizing trio: SAM as a count, or SAM as a share of
    TAM. None when the material gave neither."""
    sizing = (frame or {}).get("sizing") if isinstance(frame, dict) else None
    if not isinstance(sizing, dict):
        return None
    sam, tam = sizing.get("sam") or {}, sizing.get("tam") or {}
    ps = parse_figure(sam.get("value")) if sam else None
    if ps and ps["kind"] == "count":
        return {"people": int(round(ps["value"])), "basis": BASIS_OFFICIAL, "label": sam.get("label") or "in scope", "source": sam.get("source") or "",
                "year": sam.get("year") or "", "derived": "SAM"}
    pt = parse_figure(tam.get("value")) if tam else None
    if ps and ps["kind"] == "share" and pt and pt["kind"] == "count":
        return {"people": int(round(ps["value"] * pt["value"])), "basis": BASIS_OFFICIAL, "label": f"{sam.get('label') or 'in scope'} ({sam.get('value')} of {tam.get('label') or 'the place'})",
                "source": " / ".join(x for x in (sam.get("source"), tam.get("source")) if x), "year": sam.get("year") or tam.get("year") or "", "derived": "SAM share × TAM"}
    return None


def denominator_for(spec: dict, frame: Optional[dict]) -> Optional[dict]:
    """The analyst's own figure when typed (client supplied), else the frame's."""
    own = spec.get("denominator") if isinstance(spec.get("denominator"), dict) else None
    if own:
        p = parse_figure(own.get("people"))
        if p and p["kind"] == "count":
            return {"people": int(round(p["value"])), "basis": BASIS_CLIENT, "label": str(own.get("label") or "in scope (client supplied)")[:120],
                    "source": str(own.get("source") or "")[:160], "year": str(own.get("year") or "")[:12], "derived": "typed"}
    return denominator_from_frame(frame)


def anchors_of(stages: list[dict]) -> dict[str, dict]:
    """Known headcounts per step (`people` + `people_source`), keyed by step key."""
    out = {}
    for st in stages:
        p = parse_figure(st.get("people"))
        if p and p["kind"] == "count":
            out[st["key"]] = {"people": int(round(p["value"])), "source": str(st.get("people_source") or "")[:160]}
    return out


def weighted_reached(rows: list[dict], stages: list[dict], weights: dict[str, float]) -> tuple[list[dict], float]:
    """Per step: the weighted share who reached it, with a Wilson interval at the effective n."""
    idx = {st["key"]: k for k, st in enumerate(stages)}
    ws = [float(weights.get(r["agent_id"], 1.0)) for r in rows]
    total = sum(ws) or 1.0
    ess = round((sum(ws) ** 2) / (sum(w * w for w in ws) or 1.0), 1)
    out = []
    for k in range(len(stages)):
        share = sum(w for r, w in zip(rows, ws) if idx.get(r["answer"].get("reached"), -1) >= k) / total
        n_eff = max(1, int(round(ess)))
        wl = stats.wilson(int(round(share * n_eff)), n_eff)
        out.append({"share": round(share, 4), "low": wl["low"], "high": wl["high"]})
    return out, ess


def _people(n: float, share: float) -> int:
    return int(round(n * share))


def apply(agg: dict, *, denominator: Optional[dict], stages: list[dict], rows: Optional[list[dict]] = None,
          weights: Optional[dict[str, float]] = None) -> dict:
    """Write headcounts onto a journey aggregate in place: `headcount` (the denominator and its
    basis), `people` on every funnel step, `at_risk_people` / `through_people` / `stuck_people`
    with an interval on every transition and candidate. Quiet — `headcount.available: False`
    with a reason — when there is no denominator and no anchor."""
    funnel = agg.get("funnel") or []
    anchors = anchors_of(stages)
    if not funnel:
        agg["headcount"] = {"available": False, "reason": "No funnel to count."}
        return agg
    weighted = False
    ess = None
    shares = [{"share": f.get("share"), "low": f.get("low"), "high": f.get("high")} for f in funnel]
    if rows and weights and any(abs(float(w) - 1.0) > 1e-6 for w in weights.values()):
        shares, ess = weighted_reached(rows, stages, weights)
        weighted = True
    if not denominator and not anchors:
        agg["headcount"] = {"available": False, "reason": "No sizing figure on file for this population and none typed: the shares stand on their own. "
                                                          "Give the Journey tool the number of people in scope (with its source) to see headcounts.",
                            "weighted": weighted}
        for f in funnel:
            f.pop("people", None)
        return agg

    # People at every step: an anchored step is exact; a step after an anchor scales from the
    # nearest anchor before it by the panel's shares; otherwise the denominator × the share.
    people: list[dict] = []
    for k, st in enumerate(stages):
        sh = shares[k] if k < len(shares) else {"share": 0.0, "low": 0.0, "high": 0.0}
        if st["key"] in anchors:
            a = anchors[st["key"]]
            people.append({"people": a["people"], "low": a["people"], "high": a["people"], "basis": BASIS_CLIENT, "source": a["source"], "anchored": True})
            continue
        anchor_k = max((j for j in range(k) if stages[j]["key"] in anchors), default=None)
        if anchor_k is not None and (shares[anchor_k]["share"] or 0) > 0:
            base = anchors[stages[anchor_k]["key"]]["people"] / float(shares[anchor_k]["share"])
            people.append({"people": _people(base, sh["share"] or 0), "low": _people(base, sh["low"] or 0), "high": _people(base, sh["high"] or 0),
                           "basis": BASIS_ANCHORED, "source": anchors[stages[anchor_k]["key"]]["source"], "anchor": stages[anchor_k]["label"]})
            continue
        if denominator:
            n = float(denominator["people"])
            people.append({"people": _people(n, sh["share"] or 0), "low": _people(n, sh["low"] or 0), "high": _people(n, sh["high"] or 0),
                           "basis": denominator["basis"], "source": denominator.get("source", "")})
            continue
        people.append({"people": None, "low": None, "high": None, "basis": "", "source": ""})

    for f, p, sh in zip(funnel, people, shares):
        f.update({"people": p["people"], "people_low": p["low"], "people_high": p["high"], "basis": p["basis"], "anchor": p.get("anchor", ""), "fixed": bool(p.get("anchored"))})
        if weighted:
            f["share_weighted"] = sh["share"]
            f["low_weighted"], f["high_weighted"] = sh["low"], sh["high"]

    def _fill(t: dict) -> None:
        k = int(t.get("step") or 1) - 1
        at = people[k] if k < len(people) else None
        nxt = people[k + 1] if k + 1 < len(people) else None
        if not at or at["people"] is None:
            return
        conv = float(t.get("conversion") or 0.0)
        lo, hi = float(t.get("low") or 0.0), float(t.get("high") or 0.0)
        at_risk = at["people"]
        if nxt and nxt.get("anchored"):
            through = nxt["people"]
            stuck = max(0, at_risk - through)
            t.update({"at_risk_people": at_risk, "through_people": through, "stuck_people": stuck, "stuck_low": stuck, "stuck_high": stuck, "basis": BASIS_CLIENT})
        else:
            through = _people(at_risk, conv)
            t.update({"at_risk_people": at_risk, "through_people": through, "stuck_people": at_risk - through,
                      "stuck_low": at_risk - _people(at_risk, hi), "stuck_high": at_risk - _people(at_risk, lo), "basis": at["basis"]})

    for t in agg.get("transitions") or []:
        _fill(t)
    for c in agg.get("candidates") or []:
        _fill(c)
    agg["headcount"] = {
        "available": True, "denominator": denominator, "anchors": [{"step": st["label"], **anchors[st["key"]]} for st in stages if st["key"] in anchors],
        "weighted": weighted, "ess": ess, "unit": "people",
        "sentence": _sentence(denominator, anchors, stages, weighted),
    }
    return agg


def _sentence(denominator: Optional[dict], anchors: dict, stages: list[dict], weighted: bool) -> str:
    parts = []
    if denominator:
        src = " · ".join(x for x in (denominator.get("source"), denominator.get("year")) if x)
        parts.append(f"{denominator['people']:,} people in scope ({denominator.get('label') or 'in scope'}{'; ' + src if src else ''}; "
                     f"{'client supplied' if denominator['basis'] == BASIS_CLIENT else 'official statistic'})")
    if anchors:
        parts.append("held fixed at " + ", ".join(f"{a['people']:,} at '{st['label']}'" for st in stages for a in [anchors.get(st['key'])] if a))
    if weighted:
        parts.append("shares weighted to the sampling frame")
    return "; ".join(parts) + "." if parts else ""


async def attach(probe_id: str) -> None:
    """After a journey run: read the latest build's frame (sizing + weights) and the analyst's
    own figures from the spec, and write the headcounts onto the stored aggregates."""
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified
    from app.core import database as dbm
    from app.models.agent import SpawnedAgent
    from app.models.measurement import Probe, ProbeAnswer
    from app.services.measurement.instruments.journey import candidates_of, stages_of

    frame = None
    try:
        from app.services.population.builder import latest_build
        bld = await latest_build_for(probe_id, latest_build)
        frame = bld.frame if bld and bld.frame else None
    except Exception:  # noqa: BLE001
        frame = None
    async with dbm.AsyncSessionLocal() as db:
        probe = await db.get(Probe, probe_id)
        if not probe or not isinstance(probe.aggregates, dict) or not probe.aggregates.get("funnel"):
            return
        spec = probe.spec or {}
        stages = stages_of(spec)
        answers = (await db.execute(select(ProbeAnswer).where(ProbeAnswer.probe_id == probe_id))).scalars().all()
        ids = [a.agent_id for a in answers]
        agents = {a.id: a for a in (await db.execute(select(SpawnedAgent).where(SpawnedAgent.id.in_(ids)))).scalars().all()} if ids else {}
        rows = [{"agent_id": a.agent_id, "answer": a.answer or {}} for a in answers if (a.answer or {}).get("reached")]
        weights = {aid: float(getattr(ag, "weight", None) or 1.0) for aid, ag in agents.items()}
        agg = dict(probe.aggregates)
        apply(agg, denominator=denominator_for(spec, frame), stages=stages, rows=rows, weights=weights)
        if agg.get("transitions"):
            agg["candidates"] = candidates_of(agg["transitions"])
        probe.aggregates = agg
        flag_modified(probe, "aggregates")
        await db.commit()


async def latest_build_for(probe_id: str, latest_build) -> Any:
    from app.core import database as dbm
    from app.models.measurement import Probe
    async with dbm.AsyncSessionLocal() as db:
        probe = await db.get(Probe, probe_id)
        if not probe:
            return None
        sid = probe.session_id
    return await latest_build(sid)
