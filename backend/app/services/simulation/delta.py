"""The delta view (brief L6-06): what changed between two runs of the same question.

A report proper stores its computed structure and the ids of the records it was written from;
records live on probes, which never change once complete. So two reports can be compared long
after the fact: the headline then and now with whether the change is real (the two intervals do
not overlap), the position mix, the equity gap, the barriers that appeared, dropped or moved,
the dissenters who changed, how the evidence base grew, and the computed confidence.

`compare` is pure; `delta_for_session` loads the two reports and their records.
"""
from __future__ import annotations

from typing import Any, Optional


def _headline(records: list[dict]) -> Optional[dict]:
    return next((r for r in records if r.get("kind") == "headline"), None)


def _barriers(records: list[dict]) -> Optional[dict]:
    return next((r for r in records if r.get("barriers")), None)


def _real_change(a: Optional[dict], b: Optional[dict]) -> Optional[bool]:
    """True when the two intervals do not overlap."""
    if not a or not b:
        return None
    try:
        return bool(float(a["high"]) < float(b["low"]) or float(b["high"]) < float(a["low"]))
    except (KeyError, TypeError, ValueError):
        return None


def compare(a: dict, b: dict) -> dict:
    """`a` and `b`: `{report: {id, created_at, structure, answer}, records: [...]}` — the earlier
    and the later run."""
    sa, sb = (a.get("report") or {}).get("structure") or {}, (b.get("report") or {}).get("structure") or {}
    ha, hb = _headline(a.get("records") or []), _headline(b.get("records") or [])
    ea, eb = (ha or {}).get("estimate") or {}, (hb or {}).get("estimate") or {}
    out: dict[str, Any] = {
        "a": {"report_id": (a.get("report") or {}).get("id"), "created_at": (a.get("report") or {}).get("created_at"), "n": int(ea.get("n") or 0)},
        "b": {"report_id": (b.get("report") or {}).get("id"), "created_at": (b.get("report") or {}).get("created_at"), "n": int(eb.get("n") or 0)},
    }
    # headline
    if ea.get("value") is not None and eb.get("value") is not None:
        out["headline"] = {"label": eb.get("label") or ea.get("label"), "then": ea, "now": eb,
                           "change_points": round((float(eb["value"]) - float(ea["value"])) * 100, 1) if ea.get("format") == "share" else None,
                           "real": _real_change(ea, eb)}
    else:
        out["headline"] = None
    # positions
    pa = {p["value"]: p for p in ((sa.get("discussion") or {}).get("positions") or [])}
    pb = {p["value"]: p for p in ((sb.get("discussion") or {}).get("positions") or [])}
    out["positions"] = [{"value": k, "then": pa.get(k, {}).get("share"), "now": pb.get(k, {}).get("share"),
                         "change_points": round(((pb.get(k, {}).get("share") or 0) - (pa.get(k, {}).get("share") or 0)) * 100, 1)} for k in ("for", "mixed", "against")] if pa or pb else []
    # equity
    qa, qb = (ha or {}).get("equity") or {}, (hb or {}).get("equity") or {}
    out["equity"] = {"then": {"gap": qa.get("gap"), "significant": qa.get("significant")} if qa.get("available") else None,
                     "now": {"gap": qb.get("gap"), "significant": qb.get("significant")} if qb.get("available") else None}
    # dissent
    da = {d["agent_id"]: d for d in ((sa.get("discussion") or {}).get("dissent") or [])}
    db_ = {d["agent_id"]: d for d in ((sb.get("discussion") or {}).get("dissent") or [])}
    out["dissent"] = {"joined": [db_[k] for k in db_ if k not in da], "left": [da[k] for k in da if k not in db_], "stayed": [db_[k] for k in db_ if k in da],
                      "majority_then": (sa.get("discussion") or {}).get("majority"), "majority_now": (sb.get("discussion") or {}).get("majority")}
    # barriers
    ba, bb = _barriers(a.get("records") or []), _barriers(b.get("records") or [])
    if ba or bb:
        ra = {x["theme"]: (k + 1, x) for k, x in enumerate((ba or {}).get("barriers") or [])}
        rb = {x["theme"]: (k + 1, x) for k, x in enumerate((bb or {}).get("barriers") or [])}
        out["barriers"] = {
            "appeared": [{"theme": t, "rank": rb[t][0], "count": rb[t][1].get("count")} for t in rb if t not in ra],
            "dropped": [{"theme": t, "rank": ra[t][0], "count": ra[t][1].get("count")} for t in ra if t not in rb],
            "moved": [{"theme": t, "then": ra[t][0], "now": rb[t][0], "count_then": ra[t][1].get("count"), "count_now": rb[t][1].get("count")} for t in rb if t in ra and ra[t][0] != rb[t][0]],
            "same": [{"theme": t, "rank": rb[t][0], "count_then": ra[t][1].get("count"), "count_now": rb[t][1].get("count")} for t in rb if t in ra and ra[t][0] == rb[t][0]],
        }
    else:
        out["barriers"] = None
    # evidence base
    ev_a = {e["class"]: e["count"] for e in ((sa.get("source_materials") or {}).get("evidence") or [])}
    ev_b = {e["class"]: e["count"] for e in ((sb.get("source_materials") or {}).get("evidence") or [])}
    out["evidence"] = [{"class": k, "then": ev_a.get(k, 0), "now": ev_b.get(k, 0), "change": ev_b.get(k, 0) - ev_a.get(k, 0)} for k in sorted(set(ev_a) | set(ev_b))]
    out["evidence_total"] = {"then": sum(ev_a.values()), "now": sum(ev_b.values())}
    # confidence and figures
    ca, cb = (sa.get("direct_answer") or {}).get("confidence") or {}, (sb.get("direct_answer") or {}).get("confidence") or {}
    out["confidence"] = {"then": {"band": ca.get("band"), "score": ca.get("score")}, "now": {"band": cb.get("band"), "score": cb.get("score")}}
    out["unsourced"] = {"then": len(((sa.get("figures") or {}).get("unsourced") or [])), "now": len(((sb.get("figures") or {}).get("unsourced") or []))}
    out["records"] = {"then": len(a.get("records") or []), "now": len(b.get("records") or [])}
    out["summary"] = summary(out)
    return out


def summary(d: dict) -> str:
    parts = []
    h = d.get("headline")
    if h and h.get("change_points") is not None:
        parts.append(f"{h.get('label') or 'Headline'} moved {h['change_points']:+g} points ({round(float(h['then']['value']) * 100)}% → {round(float(h['now']['value']) * 100)}%), "
                     + ("a real change: the intervals do not overlap" if h.get("real") else "not distinguishable: the intervals overlap"))
    ev = d.get("evidence_total") or {}
    if ev.get("then") is not None and ev.get("now") != ev.get("then"):
        parts.append(f"the evidence base went from {ev['then']} to {ev['now']} items")
    b = d.get("barriers") or {}
    if b.get("appeared"):
        parts.append("new barrier(s): " + ", ".join(x["theme"] for x in b["appeared"]))
    if b.get("dropped"):
        parts.append("barrier(s) gone: " + ", ".join(x["theme"] for x in b["dropped"]))
    ds = d.get("dissent") or {}
    if ds.get("joined") or ds.get("left"):
        parts.append(f"{len(ds.get('joined') or [])} twin(s) joined the dissent, {len(ds.get('left') or [])} left it")
    c = d.get("confidence") or {}
    if (c.get("then") or {}).get("band") and (c.get("now") or {}).get("band") and c["then"]["band"] != c["now"]["band"]:
        parts.append(f"computed confidence {c['then']['band']} → {c['now']['band']}")
    return ("; ".join(parts) + ".") if parts else "Nothing measurable changed between the two runs."


async def delta_for_session(session_id: str, a_id: Optional[str] = None, b_id: Optional[str] = None) -> Optional[dict]:
    """Compare two reports proper of the session: `b` (default the latest) against `a` (default
    the one before it). None when fewer than two exist."""
    from sqlalchemy import select
    from app.core import database as dbm
    from app.models.report import ReportQuery
    from app.services.simulation import records as records_mod

    async with dbm.AsyncSessionLocal() as db:
        rows = (await db.execute(select(ReportQuery).where(ReportQuery.session_id == session_id, ReportQuery.structure.isnot(None)).order_by(ReportQuery.created_at))).scalars().all()
    if len(rows) < 2 and not (a_id and b_id):
        return None
    by_id = {r.id: r for r in rows}
    rb = by_id.get(b_id) if b_id else rows[-1]
    ra = by_id.get(a_id) if a_id else (rows[-2] if rb is rows[-1] else rows[max(0, rows.index(rb) - 1)])
    if not ra or not rb:
        return None

    async def side(r: ReportQuery) -> dict:
        ids = ((r.structure or {}).get("records") or {}).get("all") or []
        recs = await records_mod.records_by_ids(session_id, ids)
        return {"report": {"id": r.id, "created_at": r.created_at.isoformat() if r.created_at else None, "structure": r.structure or {}, "answer": r.answer}, "records": recs}

    out = compare(await side(ra), await side(rb))
    out["available"] = [{"id": r.id, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
    return out
