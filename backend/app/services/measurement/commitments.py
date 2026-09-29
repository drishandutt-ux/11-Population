"""Commitment records (brief L7-08): freeze the modelled baseline when a client picks a candidate
outcome to pursue, so real-world performance can later be compared against what was forecast.

A candidate's numbers live inside a session that keeps changing — rebuild the population, add a
document, sign a rule, re-run the journey, and the figure the client saw is gone. A commitment
takes a **copy**, not a pointer:

  * **What is frozen** (`build_baseline`): the candidate as it stood (step, conversion with its
    interval, stuck, headcount and denominator, barriers, movability, equity, confidence), the
    journey run it came from (stages, funnel, headcount sentence, seed, model, prompt hash), every
    lever run, behaviour ranking and message test on that candidate (their records, the rule they
    ran under), the population build and the frame (level, matched / weighted / estimated
    dimensions, effective n, geography, sizing), the evidence on file (the ledger's items and typed
    facts with their provenance class — a list, not the corpus: L1-06 is not built), the scoping
    snapshot id, every calibration rule with its status, and the synthetic statement.
  * **Signed by name**, dated, and never edited. Committing the same candidate again supersedes the
    open one (`superseded_by`); a commitment can be closed with a note. Nothing else in the Lab is
    blocked by a commitment.
  * **The loop closes later** (`observe`, `compare`): an observed result is entered by hand with a
    source and a date; the record then shows forecast against observed and whether the observed
    figure fell inside the modelled interval and met the target. No model call anywhere.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select

STATUSES = ("open", "closed", "superseded")


# ── pure: the baseline, the comparison ───────────────────────────────────────

def _iso(v: Any) -> Optional[str]:
    return v.isoformat() if isinstance(v, datetime) else (str(v) if v else None)


def build_baseline(*, run: dict, candidate: dict, journey: dict, related: list[dict], ledger: dict, statement: str, weights: Optional[dict] = None) -> dict:
    """The frozen modelled baseline. Everything a later reader needs to say what was forecast and
    what it rested on; nothing that a later edit to the session can reach."""
    hc = journey.get("headcount") or {}
    return {
        "frozen_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "question": run.get("question") or "", "title": run.get("title") or "",
        "candidate": dict(candidate),
        "journey": {"probe_id": journey.get("probe_id"), "stages": journey.get("stages") or [], "funnel": journey.get("funnel") or [],
                    "headcount": {"available": bool(hc.get("available")), "sentence": hc.get("sentence") or "", "reason": hc.get("reason") or "",
                                  "denominator": hc.get("denominator"), "weighted": bool(hc.get("weighted"))},
                    "n": journey.get("n"), "seed": journey.get("seed"), "model": journey.get("model"), "prompt_hash": journey.get("prompt_hash"),
                    "created_at": journey.get("created_at")},
        "related": [{k: r.get(k) for k in ("id", "kind", "label", "estimate", "sentence", "caveats", "lever", "targeting", "messaging", "provenance")} for r in related],
        "population": {**(run.get("population") or {}), "weights": weights or {}},
        "frame": dict(run.get("frame") or {}),
        "evidence": {"counts": dict(run.get("evidence") or {}),
                     "items": [{k: it.get(k) for k in ("id", "title", "source_ref", "provenance_class", "trust_tier", "published_at", "on_topic")} for it in (ledger.get("items") or [])],
                     "facts": [{k: f.get(k) for k in ("id", "value", "statistic", "group", "geography", "year", "source", "provenance_class")} for f in (ledger.get("facts") or [])]},
        "scoping_snapshot": run.get("scoping_snapshot"),
        "calibration_rules": [{k: r.get(k) for k in ("id", "lever", "status", "reviewed_by", "reviewed_at", "basis_class", "deltas", "applies_to")} for r in (run.get("calibration_rules") or [])],
        "statement": statement,
    }


def clean_target(raw: Any) -> dict:
    """`{value (share 0–1), horizon, note}` — a value outside 0–1 or a percentage is normalised; empty when nothing was set."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    v = raw.get("value")
    if v is not None and str(v).strip() != "":
        try:
            x = float(v)
            out["value"] = round(x / 100.0 if x > 1 else x, 4)
        except (TypeError, ValueError):
            pass
    for k in ("horizon", "note"):
        if str(raw.get(k) or "").strip():
            out[k] = str(raw[k]).strip()[:300]
    return out


def clean_observed(raw: Any, *, entered_by: str = "") -> tuple[Optional[dict], Optional[str]]:
    """One observed result: a share (0–1, or a percentage), an optional range, a source and a date
    are required — an observation without a source is not evidence of anything."""
    if not isinstance(raw, dict):
        return None, "The observation must be an object."
    try:
        x = float(raw.get("value"))
    except (TypeError, ValueError):
        return None, "The observed value is required and must be a number (a share or a percentage)."
    value = round(x / 100.0 if x > 1 else x, 4)
    if not (0 <= value <= 1):
        return None, "The observed value must be a share between 0 and 1 (or a percentage)."
    source = str(raw.get("source") or "").strip()[:300]
    date = str(raw.get("date") or "").strip()[:40]
    if not source:
        return None, "Say where the observed figure comes from (the source is required)."
    if not date:
        return None, "Say when the observed figure was measured (the date is required)."
    out = {"value": value, "source": source, "date": date, "entered_by": str(raw.get("entered_by") or entered_by or "").strip()[:120],
           "entered_at": datetime.utcnow().isoformat(timespec="seconds") + "Z", "note": str(raw.get("note") or "").strip()[:600]}
    for k in ("low", "high"):
        v = raw.get(k)
        if v is not None and str(v).strip() != "":
            try:
                y = float(v)
                out[k] = round(y / 100.0 if y > 1 else y, 4)
            except (TypeError, ValueError):
                pass
    return out, None


def compare(baseline: dict, target: dict, observed: list[dict]) -> Optional[dict]:
    """Forecast against the latest observed result: the delta in points, whether the observed
    figure sits inside the modelled interval, and whether the target was met. None with no
    observation. Counted, never judged."""
    if not observed:
        return None
    c = baseline.get("candidate") or {}
    conv, low, high = c.get("conversion"), c.get("low"), c.get("high")
    latest = sorted(observed, key=lambda o: (o.get("date") or "", o.get("entered_at") or ""))[-1]
    obs = float(latest.get("value") or 0)
    out: dict = {"observed": obs, "observed_date": latest.get("date"), "observed_source": latest.get("source"), "observations": len(observed),
                 "forecast": conv, "forecast_low": low, "forecast_high": high}
    if conv is not None:
        out["delta"] = round(obs - float(conv), 4)
        out["direction"] = "above" if obs > float(conv) else "below" if obs < float(conv) else "at"
    if low is not None and high is not None:
        out["inside_interval"] = bool(float(low) <= obs <= float(high))
    tv = (target or {}).get("value")
    if tv is not None:
        out["target"] = tv
        out["target_met"] = bool(obs >= float(tv))
    return out


def sentence(c: dict) -> str:
    """The commitment in one line, from the frozen baseline and the observed results only."""
    b = c.get("baseline") or {}
    cand = b.get("candidate") or {}
    frm, to = (cand.get("from") or {}).get("label"), (cand.get("to") or {}).get("label")
    pop = b.get("population") or {}
    conv, lo, hi = cand.get("conversion"), cand.get("low"), cand.get("high")
    text = (f"Committed by {c.get('committed_by') or 'nobody'} on {str(c.get('committed_at') or '')[:10]}: the share of those at '{frm}' who reach '{to}', "
            f"modelled at {round(float(conv or 0) * 100)}% (95% CI {round(float(lo or 0) * 100)}–{round(float(hi or 0) * 100)}%, {cand.get('n')} twins at risk, "
            f"{cand.get('stuck')} stuck) on population build {pop.get('build_id') or 'unknown'} ({pop.get('n')} twins)")
    if cand.get("stuck_people") is not None:
        text += f"; ≈{int(cand['stuck_people']):,} people stuck"
    t = c.get("target") or {}
    if t.get("value") is not None:
        text += f"; target {round(float(t['value']) * 100)}%" + (f" by {t['horizon']}" if t.get("horizon") else "")
    cmp_ = c.get("comparison")
    if cmp_:
        text += (f". Observed {round(cmp_['observed'] * 100)}% on {cmp_.get('observed_date')} ({cmp_.get('observed_source')}): "
                 f"{round(float(cmp_.get('delta') or 0) * 100):+d} points against the forecast, "
                 + ("inside" if cmp_.get("inside_interval") else "outside") + " the modelled interval"
                 + (("; target " + ("met" if cmp_.get("target_met") else "not met")) if "target_met" in cmp_ else "") + ".")
    else:
        text += ". No observed result yet."
    if c.get("status") == "superseded":
        text += " Superseded by a later commitment."
    elif c.get("status") == "closed":
        text += f" Closed by {c.get('closed_by') or 'nobody'}" + (f": {c.get('close_note')}" if c.get("close_note") else "") + "."
    return text


def payload(m: Any) -> dict:
    """The API's view of a commitment: the row plus the counted comparison and the sentence."""
    out = {
        "id": m.id, "session_id": m.session_id, "journey_probe_id": m.journey_probe_id, "candidate_id": m.candidate_id,
        "label": m.label or "", "committed_by": m.committed_by or "", "committed_at": _iso(m.committed_at),
        "target": dict(m.target or {}), "status": m.status or "open", "superseded_by": m.superseded_by,
        "closed_by": m.closed_by or "", "closed_at": _iso(m.closed_at), "close_note": m.close_note or "",
        "baseline": dict(m.baseline or {}), "observed": list(m.observed or []),
        "created_at": _iso(m.created_at),
    }
    out["comparison"] = compare(out["baseline"], out["target"], out["observed"])
    out["sentence"] = sentence(out)
    return out


# ── the freeze ───────────────────────────────────────────────────────────────

async def freeze(session_id: str, *, journey_probe_id: str, candidate_id: str, committed_by: str, target: Any = None, label: str = "") -> dict:
    """Create the commitment. Returns the payload or `{error}`. An open commitment on the same
    candidate is marked superseded by the new one."""
    from app.core.database import AsyncSessionLocal
    from app.models.agent import SpawnedAgent
    from app.models.measurement import Commitment, Experiment, Probe
    from app.services.simulation import export as export_mod
    from app.services.simulation import figures as figures_mod
    from app.services.simulation import records as records_mod

    who = str(committed_by or "").strip()[:120]
    if not who:
        return {"error": "A commitment is signed by name: say who is committing."}
    async with AsyncSessionLocal() as db:
        base = await db.get(Probe, journey_probe_id)
        if not base or base.session_id != session_id or base.instrument != "journey" or base.status != "complete":
            return {"error": "The journey run was not found or is not complete."}
        agg = base.aggregates or {}
        raw = next((c for c in (agg.get("candidates") or []) if c.get("id") == candidate_id or f"{base.id}:{c.get('id')}" == candidate_id), None)
        if not raw:
            return {"error": "That candidate is not on this journey run."}
        cand_key = raw.get("id")
        exps = (await db.execute(select(Experiment).where(Experiment.session_id == session_id, Experiment.status == "complete"))).scalars().all()
        agents = (await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == session_id))).scalars().all()
    candidate = records_mod.candidate_summary(raw, base.id)
    # every run on this candidate, as records
    related = []
    for e in exps:
        spec = e.spec or {}
        info = spec.get("lever_run") or spec.get("targeting") or spec.get("messaging") or {}
        if info.get("journey_probe_id") == base.id and info.get("candidate_id") == cand_key:
            r = records_mod.record_from_experiment(e)
            if r:
                related.append(r)
    ws = [float(getattr(a, "weight", None) or 1.0) for a in agents]
    weighted = any(abs(w - 1.0) > 1e-6 for w in ws)
    weights = {"n": len(ws), "weighted": weighted, "ess": round((sum(ws) ** 2) / (sum(w * w for w in ws) or 1.0), 1) if ws else 0}
    run = await export_mod.run_record(session_id)
    ledger = await figures_mod.load_ledger(session_id)
    journey = {"probe_id": base.id, "stages": agg.get("stages") or [], "funnel": agg.get("funnel") or [], "headcount": agg.get("headcount") or {},
               "n": base.answer_count, "seed": base.seed, "model": base.model, "prompt_hash": base.prompt_hash, "created_at": _iso(base.created_at)}
    baseline = build_baseline(run=run, candidate=candidate, journey=journey, related=related, ledger=ledger, statement=export_mod.statement(run), weights=weights)
    lab = str(label or "").strip()[:300] or f"{(raw.get('from') or {}).get('label')} → {(raw.get('to') or {}).get('label')}"
    async with AsyncSessionLocal() as db:
        m = Commitment(id=str(uuid.uuid4()), session_id=session_id, journey_probe_id=base.id, candidate_id=str(cand_key), label=lab,
                       committed_by=who, committed_at=datetime.utcnow(), target=clean_target(target), status="open", baseline=baseline, observed=[])
        db.add(m)
        olds = (await db.execute(select(Commitment).where(Commitment.session_id == session_id, Commitment.journey_probe_id == base.id,
                                                          Commitment.candidate_id == str(cand_key), Commitment.status == "open",
                                                          Commitment.id != m.id))).scalars().all()
        for o in olds:
            o.status = "superseded"
            o.superseded_by = m.id
        await db.commit()
        await db.refresh(m)
        return payload(m)


async def observe(session_id: str, commitment_id: str, raw: Any, *, entered_by: str = "") -> dict:
    from sqlalchemy.orm.attributes import flag_modified
    from app.core.database import AsyncSessionLocal
    from app.models.measurement import Commitment
    entry, err = clean_observed(raw, entered_by=entered_by)
    if err:
        return {"error": err}
    async with AsyncSessionLocal() as db:
        m = await db.get(Commitment, commitment_id)
        if not m or m.session_id != session_id:
            return {"error": "Commitment not found."}
        m.observed = list(m.observed or []) + [entry]
        flag_modified(m, "observed")
        await db.commit()
        await db.refresh(m)
        return payload(m)


async def close(session_id: str, commitment_id: str, *, closed_by: str, note: str = "") -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.measurement import Commitment
    who = str(closed_by or "").strip()[:120]
    if not who:
        return {"error": "Closing a commitment is signed by name: say who is closing it."}
    async with AsyncSessionLocal() as db:
        m = await db.get(Commitment, commitment_id)
        if not m or m.session_id != session_id:
            return {"error": "Commitment not found."}
        if m.status == "closed":
            return payload(m)
        m.status = "closed"
        m.closed_by = who
        m.closed_at = datetime.utcnow()
        m.close_note = str(note or "").strip()[:600]
        await db.commit()
        await db.refresh(m)
        return payload(m)


async def list_for_session(session_id: str) -> list[dict]:
    from app.core.database import AsyncSessionLocal
    from app.models.measurement import Commitment
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Commitment).where(Commitment.session_id == session_id).order_by(Commitment.committed_at.desc()))).scalars().all()
        return [payload(m) for m in rows]


async def get(session_id: str, commitment_id: str) -> Optional[dict]:
    from app.core.database import AsyncSessionLocal
    from app.models.measurement import Commitment
    async with AsyncSessionLocal() as db:
        m = await db.get(Commitment, commitment_id)
        return payload(m) if m and m.session_id == session_id else None
