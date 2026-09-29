"""Outcome records (brief L6-01): the computed backbone of every report.

A report used to be prose the model wrote, with numbers pulled out of the prose afterwards.
Now every figure about the population is an OUTCOME RECORD — computed from a probe or an
experiment, never typed by the report model — and the narrative is written around the
records, citing each by id the way it cites twins.

  * `record_from_probe` / `record_from_experiment` shape one Lab result into a record: what
    was asked, who answered, the estimate with its interval, the population's own splits, the
    refusal share, the unanimity verdict, the provenance (model, seed, evidence mix, frame
    level) and a computed confidence with its drivers and caveats.
  * `ensure_headline` guarantees at least one record exists before a report is written: the
    population's answer to the session question, from the hidden `verdict` instrument. It is
    reused while the population is unchanged and re-run after a rebuild.
  * `records_block` numbers the records R1 … Rn for the report prompt; `resolve_handles` turns
    the model's `[[R2]]` into `[[record:<id>]]` for the reader.

Generic by design: nothing here knows what a condition or a journey stage is. A pharma tag
(`tags.condition`, `tags.journey_stage`) is carried when present and empty otherwise.
"""
from __future__ import annotations

import random
import re
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.agent import SpawnedAgent
from app.models.evidence import Evidence
from app.models.measurement import Experiment, Probe, ProbeAnswer
from app.services.population import equity as equity_mod

HANDLE_RE = re.compile(r"\[\[\s*(R\d+)\s*\]\]", re.IGNORECASE)
TOKEN_RE = re.compile(r"\[\[record:([0-9a-fA-F-]{36})\]\]")

FIGURE_RULES = (
    "FIGURES — where every number about this population comes from:\n"
    "- Every share, count, price, lift or interval about the population is an OUTCOME RECORD "
    "listed under == OUTCOME RECORDS ==, computed from the twins' answers. Cite the record right "
    "after the figure: \"75% would buy [[R1]]\".\n"
    "- Do NOT type a figure about the population that is not in a record. If no record covers "
    "it, say it in words (\"most\", \"a minority\", \"the older twins\") and cite the twins instead.\n"
    "- Figures from the source material (a statistic, a price in a document) are cited too — "
    "see SOURCE FIGURES: [[F3]] for a typed statistic, [[E5]] for the document it was read in.\n"
    "- The headline record (R1) is the population's answer to the question: lead with it.\n"
    "- Every record carries an equity line (most vs least deprived cell). State the gap only as the record gives it, "
    "say when it is not distinguishable at this size, and never read a gap into a record whose equity line is unavailable.\n"
    "- A record with 'barriers ranked' is the only source for what stands in the way: name barriers from that list, in that "
    "order, cite the record, and cite the twins who raised them. Never invent a barrier or reorder them."
)


# ── shaping ──────────────────────────────────────────────────────────────────

def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def confidence_for(*, n: int, low: Optional[float], high: Optional[float], fmt: str, unanimity: Optional[dict],
                   refusals: Optional[dict], frame_level: Optional[str], weighted: bool, model: str = "") -> dict:
    """A 5–95 score with the reasons it moved, from the record's own numbers. Deterministic."""
    score = 60
    drivers: list[str] = []
    if n >= 30:
        score += 15; drivers.append(f"{n} twins answered")
    elif n >= 10:
        score += 5; drivers.append(f"{n} twins answered")
    else:
        score -= 15; drivers.append(f"only {n} twins answered")
    if fmt == "share" and low is not None and high is not None:
        width = high - low
        if width <= 0.2:
            score += 10; drivers.append("tight interval")
        elif width > 0.4:
            score -= 10; drivers.append(f"wide interval (±{round(width * 50)} points)")
    if unanimity and unanimity.get("flagged"):
        score -= 20; drivers.append("agreement the population should not have produced")
    ref_share = _num((refusals or {}).get("share"))
    if ref_share > 0.3:
        score -= 10; drivers.append(f"{round(ref_share * 100)}% said it was not theirs to answer")
    if frame_level == "good":
        score += 10; drivers.append("population matched to published distributions")
    elif frame_level == "fair":
        score += 5; drivers.append("population roughly matched to published distributions")
    elif frame_level == "poor":
        score -= 10; drivers.append("population poorly matched to published distributions")
    elif frame_level in (None, "", "none"):
        score -= 5; drivers.append("no sampling frame")
    if weighted:
        score += 5; drivers.append("weighted to the frame")
    if "sonnet" in (model or "").lower() or "opus" in (model or "").lower():
        score += 5; drivers.append("Pro model")
    return {"score": max(5, min(95, score)), "drivers": drivers}


def caveats_for(*, n: int, unanimity: Optional[dict], refusals: Optional[dict], frame_level: Optional[str],
                estimated_dims: Optional[list[str]] = None, thin_cells: Optional[list[str]] = None, equity: Optional[dict] = None) -> list[str]:
    out: list[str] = []
    if equity is not None and not equity.get("available"):
        out.append(str(equity.get("reason") or "No deprivation levels on this population."))
    elif equity and equity.get("thin"):
        out.append("Deprivation cells too thin to read on their own: " + ", ".join(equity["thin"][:4]) + ".")
    if n < 10:
        out.append(f"Small population ({n}): treat the interval, not the point, as the finding.")
    if unanimity and unanimity.get("flagged"):
        out.append("Flagged as more unanimous than this population should be: " + str(unanimity.get("reason") or "").split(". ")[0] + ".")
    ref = refusals or {}
    if ref.get("refused"):
        out.append(f"{ref['refused']} of {ref.get('n', 0)} twins said this was not theirs to answer; they are outside every denominator.")
    if frame_level in (None, "", "none"):
        out.append("No sampling frame: shares describe this panel, not a population.")
    elif frame_level == "poor":
        out.append("The panel matches published distributions poorly; weighted figures correct what they can.")
    if estimated_dims:
        out.append("Model-estimated distributions: " + ", ".join(estimated_dims) + ".")
    if thin_cells:
        out.append("Not safe to cut by: " + "; ".join(thin_cells[:4]) + ".")
    out.append("Synthetic population: these are simulated twins, not survey respondents.")
    return out


def _estimate_from_aggregates(instrument: str, agg: dict, spec: dict) -> dict:
    head = agg.get("headline") if isinstance(agg.get("headline"), dict) else None
    if head:
        return {
            "metric": str(head.get("metric") or ""), "label": str(head.get("label") or ""), "format": "share",
            "value": _num(head.get("share")), "low": _num(head.get("low")), "high": _num(head.get("high")),
            "n": int(head.get("n") or agg.get("n") or 0), "successes": int(head.get("successes") or 0),
        }
    # A survey has a per-question summary; its primary question's block is the headline.
    prim = agg.get("primary") if isinstance(agg.get("primary"), dict) else None
    if prim and isinstance(prim.get("share"), (int, float)):
        return {"metric": "primary", "label": str(prim.get("label") or "Primary question"), "format": "share",
                "value": _num(prim.get("share")), "low": _num(prim.get("low")), "high": _num(prim.get("high")),
                "n": int(prim.get("n") or agg.get("n") or 0), "successes": int(prim.get("successes") or 0)}
    return {"metric": "", "label": "Result", "format": "text", "value": None, "low": None, "high": None, "n": int(agg.get("n") or 0)}


def sources_used(rows: list) -> list[dict]:
    """The documents the answering twins cited (L6-05), rolled up: each unit with how many
    twins drew on it, most cited first. `rows` are ProbeAnswer rows or answer dicts."""
    seen: dict[str, dict] = {}
    for r in rows:
        ans = r if isinstance(r, dict) else (getattr(r, "answer", None) or {})
        for u in ans.get("used_units") or []:
            e = seen.setdefault(u["unit_id"], {"unit_id": u["unit_id"], "source_ref": u.get("source_ref", ""), "provenance_class": u.get("provenance_class", ""),
                                               "trust_tier": u.get("trust_tier", ""), "text": u.get("text", ""), "twins": 0})
            e["twins"] += 1
    return sorted(seen.values(), key=lambda e: (-e["twins"], e["provenance_class"]))[:10]


def _label_for(instrument: str, spec: dict, agg: dict) -> str:
    if instrument == "verdict":
        return "Population verdict on the question"
    if instrument == "purchase_intent":
        price = spec.get("price")
        cur = {"GBP": "£", "USD": "$", "EUR": "€"}.get(str(spec.get("currency") or ""), "")
        return f"Would buy at {cur}{_num(price):g}" if price else "Would buy"
    if instrument == "survey":
        return str(spec.get("title") or "Survey")
    if instrument == "barriers":
        o = str(spec.get("outcome") or "").strip()
        return f"What's in the way of: {o[:70]}" if o else "What's in the way"
    q = str(spec.get("question") or "").strip()
    return q[:80] if q else str(instrument).replace("_", " ").title()


def record_from_probe(p: Any, *, evidence_mix: Optional[dict] = None, frame: Optional[dict] = None) -> Optional[dict]:
    """One complete probe → one outcome record (None while it has no aggregates)."""
    agg = getattr(p, "aggregates", None) or {}
    if not isinstance(agg, dict) or not agg:
        return None
    spec = getattr(p, "spec", None) or {}
    instrument = str(getattr(p, "instrument", "") or "")
    rep = (frame or {}).get("report") if isinstance(frame, dict) else None
    frame_level = (rep or {}).get("level") if isinstance(rep, dict) else None
    est = _estimate_from_aggregates(instrument, agg, spec)
    weighted = agg.get("weighted") if isinstance(agg.get("weighted"), dict) else None
    unanimity = agg.get("unanimity") if isinstance(agg.get("unanimity"), dict) else None
    refusals = agg.get("dont_know") if isinstance(agg.get("dont_know"), dict) else None
    n = int(est.get("n") or agg.get("n") or 0)
    model = str(getattr(p, "model", "") or "")
    created = getattr(p, "created_at", None)
    splits = agg.get("segments") if isinstance(agg.get("segments"), dict) else {}
    equity = equity_mod.equity_block(splits.get(equity_mod.KEY), fmt=est.get("format", "share"))
    return {
        "id": p.id,
        "kind": "headline" if instrument == "verdict" else "probe",
        "instrument": instrument,
        "label": _label_for(instrument, spec, agg),
        "question": str(spec.get("question") or spec.get("stimulus") or spec.get("material") or "")[:300],
        "basis": "simulated",
        "estimate": est,
        "sentence": str(agg.get("sentence") or ""),
        "distribution": agg.get("position") or agg.get("would_buy") or agg.get("verdict") or [],
        "splits": splits,
        "equity": equity,
        # Barriers (brief L6-05): the ranked list this record carries, traceable to twins and evidence.
        "barriers": [{"theme": b.get("theme"), "count": b.get("count", 0), "share": b.get("share"), "low": b.get("low"), "high": b.get("high"),
                      "weight_mean": b.get("weight_mean"), "removals": b.get("removals") or [], "agent_ids": b.get("agent_ids") or [],
                      "evidence": b.get("evidence") or []} for b in (agg.get("barriers") or [])] if instrument == "barriers" else [],
        "outcome": str(agg.get("outcome") or "") if instrument == "barriers" else "",
        # The documents the twins drew on, by their own citation (L6-05); filled by the aggregator when it has the answers.
        "sources": list(agg.get("sources_used") or []),
        "refusals": refusals,
        "unanimity": unanimity,
        "weighted": weighted,
        "provenance": {
            "model": model, "seed": int(getattr(p, "seed", 0) or 0), "schema_id": str(getattr(p, "schema_id", "") or ""),
            "prompt_hash": str(getattr(p, "prompt_hash", "") or ""), "agents": int(getattr(p, "agent_count", 0) or 0),
            "answered": int(getattr(p, "answer_count", 0) or 0), "evidence_mix": evidence_mix or {},
            "frame_level": frame_level or "none", "created_at": created.isoformat() if isinstance(created, datetime) else None,
            "scoped": bool((agg.get("scoping") or {}).get("scoped")) if isinstance(agg.get("scoping"), dict) else None,
            "scoping_snapshot": (agg.get("scoping") or {}).get("snapshot_id") if isinstance(agg.get("scoping"), dict) else None,
        },
        "confidence": confidence_for(n=n, low=est.get("low"), high=est.get("high"), fmt=est.get("format", "share"),
                                     unanimity=unanimity, refusals=refusals, frame_level=frame_level, weighted=bool(weighted), model=model),
        "caveats": caveats_for(n=n, unanimity=unanimity, refusals=refusals, frame_level=frame_level,
                               estimated_dims=(rep or {}).get("estimated") if isinstance(rep, dict) else None,
                               thin_cells=(rep or {}).get("thin_cells") if isinstance(rep, dict) else None, equity=equity),
        "tags": {},
    }


def record_from_experiment(e: Any, *, evidence_mix: Optional[dict] = None, frame: Optional[dict] = None) -> Optional[dict]:
    """One complete experiment → one record: the best variant's lift on the primary metric."""
    res = getattr(e, "results", None) or {}
    comps = res.get("comparisons") if isinstance(res, dict) else None
    if not comps:
        return None
    best = max(comps, key=lambda c: next((_num(m.get("lift", {}).get("mean")) for m in c.get("metrics", []) if m.get("primary")), 0.0))
    prim = next((m for m in best.get("metrics", []) if m.get("primary")), (best.get("metrics") or [None])[0])
    lift = (prim or {}).get("lift") or {}
    rep = (frame or {}).get("report") if isinstance(frame, dict) else None
    frame_level = (rep or {}).get("level") if isinstance(rep, dict) else None
    n = int(lift.get("n") or best.get("n") or 0)
    created = getattr(e, "created_at", None)
    return {
        "id": e.id,
        "kind": "experiment",
        "instrument": str(res.get("instrument") or getattr(e, "instrument", "") or ""),
        "label": f"{best.get('label')} vs {best.get('control_label')}: lift in {(prim or {}).get('label') or 'the primary metric'}",
        "question": str(getattr(e, "name", "") or "")[:300],
        "basis": "simulated",
        "estimate": {"metric": str((prim or {}).get("key") or ""), "label": str((prim or {}).get("label") or ""), "format": "lift",
                     "value": _num(lift.get("mean")), "low": _num(lift.get("low")), "high": _num(lift.get("high")), "n": n,
                     "significant": bool(lift.get("significant")), "control": (prim or {}).get("control"), "variant": (prim or {}).get("variant")},
        "sentence": str(res.get("verdict") or best.get("sentence") or ""),
        "distribution": [],
        "splits": best.get("segments") if isinstance(best.get("segments"), dict) else {},
        "equity": equity_mod.equity_block(((best.get("segments") or {}) if isinstance(best.get("segments"), dict) else {}).get(equity_mod.KEY), fmt="lift"),
        "refusals": None,
        "unanimity": None,
        "weighted": None,
        "provenance": {"model": str(getattr(e, "model", "") or ""), "seed": int(getattr(e, "seed", 0) or 0), "design": str(res.get("design") or ""),
                       "arms": res.get("arms") or [], "evidence_mix": evidence_mix or {}, "frame_level": frame_level or "none",
                       "created_at": created.isoformat() if isinstance(created, datetime) else None},
        "confidence": confidence_for(n=n, low=None, high=None, fmt="lift", unanimity=None, refusals=None, frame_level=frame_level,
                                     weighted=False, model=str(getattr(e, "model", "") or "")),
        "caveats": (["The lift is not significant: the interval crosses zero."] if not lift.get("significant") else [])
                   + caveats_for(n=n, unanimity=None, refusals=None, frame_level=frame_level),
        "tags": {},
    }


# ── the prompt side ──────────────────────────────────────────────────────────

def _fmt_value(est: dict) -> str:
    fmt, v = est.get("format"), est.get("value")
    if v is None:
        return "n/a"
    if fmt == "share":
        return f"{round(_num(v) * 100)}% (95% CI {round(_num(est.get('low')) * 100)}–{round(_num(est.get('high')) * 100)}%, n={est.get('n', 0)})"
    if fmt == "lift":
        return f"{_num(v):+.3g} (95% CI {_num(est.get('low')):+.3g} to {_num(est.get('high')):+.3g}, n={est.get('n', 0)}{', significant' if est.get('significant') else ', not significant'})"
    return f"{v} (n={est.get('n', 0)})"


def records_block(records: list[dict]) -> tuple[str, dict[str, str]]:
    """The records as the report model sees them, numbered R1 … Rn, plus handle → id."""
    handles: dict[str, str] = {}
    lines: list[str] = []
    for k, r in enumerate(records, 1):
        h = f"R{k}"
        handles[h.lower()] = r["id"]
        est = r.get("estimate") or {}
        splits = r.get("splits") or {}
        notable = []
        for key in ("segment", "stance", "region", "age_band"):
            buckets = splits.get(key) or []
            if len(buckets) >= 2:
                hi = max(buckets, key=lambda b: _num(b.get("share")))
                lo = min(buckets, key=lambda b: _num(b.get("share")))
                notable.append(f"{key}: {hi.get('value')} {round(_num(hi.get('share')) * 100)}% vs {lo.get('value')} {round(_num(lo.get('share')) * 100)}%")
        eq_line = equity_mod.prompt_line(r.get("equity") or {})
        bars = r.get("barriers") or []
        bar_line = ("; barriers ranked: " + "; ".join(f"{k}. {b['theme']} ({b['count']} twins, weight {round(float(b.get('weight_mean') or 0))}/100)" for k, b in enumerate(bars[:7], 1))) if bars else ""
        flags = []
        if (r.get("unanimity") or {}).get("flagged"):
            flags.append("FLAGGED: more unanimous than the population should be")
        if (r.get("refusals") or {}).get("refused"):
            flags.append(f"{r['refusals']['refused']} refused to answer")
        lines.append(
            f"[[{h}]] {r.get('label')} — {est.get('label') or 'value'}: {_fmt_value(est)}"
            + (f"; question: {r['question']}" if r.get("question") else "")
            + (f"; splits: {'; '.join(notable)}" if notable else "")
            + f"; {eq_line}"
            + bar_line
            + (f"; {'; '.join(flags)}" if flags else "")
            + f"; confidence {r.get('confidence', {}).get('score', '?')}/100"
        )
    return ("\n".join(lines) if lines else "(none — no computed figures exist for this population; describe it in words)"), handles


def resolve_handles(text: str, handles: dict[str, str]) -> str:
    """`[[R2]]` → `[[record:<id>]]`; a handle that names no record is dropped."""
    def sub(m: re.Match) -> str:
        rid = handles.get(m.group(1).lower())
        return f"[[record:{rid}]]" if rid else ""
    return re.sub(r"[ \t]{2,}", " ", HANDLE_RE.sub(sub, text))


def cited_record_ids(text: str) -> list[str]:
    seen: list[str] = []
    for m in TOKEN_RE.finditer(text):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


# ── loading ──────────────────────────────────────────────────────────────────

async def evidence_mix(session_id: str) -> dict:
    """How many evidence items of each class ground this session (web / social / quant / personal / synthetic)."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Evidence.source_class, func.count(Evidence.id)).where(Evidence.session_id == session_id, Evidence.excluded == False)  # noqa: E712
            .group_by(Evidence.source_class)
        )).all()
    return {str(k): int(v) for k, v in rows}


async def _frame(session_id: str) -> Optional[dict]:
    try:
        from app.services.population.builder import latest_build
        bld = await latest_build(session_id)
        return bld.frame if bld and bld.frame else None
    except Exception:  # noqa: BLE001
        return None


async def records_for_session(session_id: str) -> list[dict]:
    """Every outcome record on file: the latest verdict first, then Lab results newest first."""
    mix = await evidence_mix(session_id)
    frame = await _frame(session_id)
    async with AsyncSessionLocal() as db:
        probes = (await db.execute(
            select(Probe).where(Probe.session_id == session_id, Probe.status == "complete", Probe.experiment_id.is_(None))
            .order_by(Probe.created_at.desc())
        )).scalars().all()
        exps = (await db.execute(
            select(Experiment).where(Experiment.session_id == session_id, Experiment.status == "complete").order_by(Experiment.created_at.desc())
        )).scalars().all()
    out: list[dict] = []
    headline_seen = False
    for p in probes:
        if p.instrument == "verdict":
            if headline_seen:
                continue  # only the latest verdict is the headline; older ones are superseded
            headline_seen = True
        r = record_from_probe(p, evidence_mix=mix, frame=frame)
        if r:
            out.append(r)
    for e in exps:
        r = record_from_experiment(e, evidence_mix=mix, frame=frame)
        if r:
            out.append(r)
    out.sort(key=lambda r: (0 if r["kind"] == "headline" else 1, r.get("provenance", {}).get("created_at") or ""), reverse=False)
    heads = [r for r in out if r["kind"] == "headline"]
    rest = sorted([r for r in out if r["kind"] != "headline"], key=lambda r: r.get("provenance", {}).get("created_at") or "", reverse=True)
    return heads + rest


async def ensure_headline(session_id: str, query: str, *, mode: str = "fast") -> Optional[dict]:
    """The population's answer to the session question as a record. Reused while the roster is
    unchanged; otherwise the verdict probe is run now (synchronously — a report waits for it).
    None when the session has no agents."""
    from app.services.measurement import probe as probe_svc
    from app.services.measurement import instruments

    async with AsyncSessionLocal() as db:
        n_agents = (await db.execute(select(func.count(SpawnedAgent.id)).where(SpawnedAgent.session_id == session_id))).scalar_one()
        if not n_agents:
            return None
        newest_agent = (await db.execute(select(func.max(SpawnedAgent.created_at)).where(SpawnedAgent.session_id == session_id))).scalar_one()
        latest = (await db.execute(
            select(Probe).where(Probe.session_id == session_id, Probe.instrument == "verdict", Probe.status == "complete")
            .order_by(Probe.created_at.desc())
        )).scalars().first()
        fresh = bool(latest and latest.agent_count == n_agents and (not newest_agent or (latest.created_at and latest.created_at >= newest_agent)))
        if fresh:
            return record_from_probe(latest, evidence_mix=await evidence_mix(session_id), frame=await _frame(session_id))

        inst = instruments.get("verdict")
        if not inst:
            return None
        spec = {"question": query, "stimulus": query, "seed": random.randint(1, 2**31 - 1)}
        p = Probe(
            id=str(uuid.uuid4()), session_id=session_id, instrument="verdict", schema_id=inst.schema_id(), spec=spec,
            seed=int(spec["seed"]), model=get_settings().agent_model(mode), prompt_hash=probe_svc.prompt_hash(inst, spec), status="queued",
        )
        db.add(p)
        await db.commit()
        probe_id = p.id

    await probe_svc.run_probe(probe_id)
    await _copy_verdicts(probe_id)

    async with AsyncSessionLocal() as db:
        p = await db.get(Probe, probe_id)
    if not p or p.status not in ("complete", "stopped"):
        return None
    return record_from_probe(p, evidence_mix=await evidence_mix(session_id), frame=await _frame(session_id))


async def _copy_verdicts(probe_id: str) -> None:
    """The one-line verdicts feed the Agent Opinions sidebar, so the report and the sidebar agree."""
    try:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(ProbeAnswer).where(ProbeAnswer.probe_id == probe_id))).scalars().all()
            for row in rows:
                line = str((row.answer or {}).get("verdict") or "").strip()
                if not line:
                    continue
                agent = await db.get(SpawnedAgent, row.agent_id)
                if agent:
                    agent.verdict = line[:300]
            await db.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[records] could not copy verdicts to the roster: {type(e).__name__}: {e}")
