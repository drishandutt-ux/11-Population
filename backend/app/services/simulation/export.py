"""Export (brief L6-06) with the non-removable synthetic-population statement (brief L6-07).

Three ways the work leaves the app:

  * `bundle`        — the structured data as one zip: `run.json` (the run record — question,
                      population, models, seeds, evidence snapshot, frame, scoping), every
                      outcome record as JSON and as two flat CSVs (one row per record, one row
                      per record × cut × cell), the latest report with its computed structure,
                      the source-figure ledger, the roster with each twin's deprivation cell and
                      what it could see, and `STATEMENT.txt`.
  * `client_markdown` — the report as a client-facing document: statement, direct answer with
                      its computed confidence, records with intervals and equity, what's in the
                      way, the narrative with citations resolved to names and figures, the caveats,
                      the statement again.
  * `statement`     — the synthetic-population statement, built server-side from the run so it
                      cannot be edited out of the interface: what the twins are, what they were
                      calibrated against, what the output must not be used for. Stamped into
                      every exported file.

Pure functions except `bundle` / `run_record`, which load.
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select

from app.core import database as dbm

TWIN_RE = re.compile(r"\[\[twin:([0-9a-fA-F-]{36})(?:\|post:[0-9a-fA-F-]{36})?\]\]")
RECORD_RE = re.compile(r"\[\[record:([A-Za-z0-9-]{1,64})\]\]")
FACT_RE = re.compile(r"\[\[fact:([A-Za-z0-9-]{1,64}#\d+)\]\]")
EVID_RE = re.compile(r"\[\[evidence:([A-Za-z0-9-]{1,64})\]\]")
UNSOURCED_RE = re.compile(r"\[\[unsourced:([^\]]+)\]\]")


# ── the statement (L6-07) ────────────────────────────────────────────────────

def statement(run: dict) -> str:
    """What the twins are, what they were calibrated against, what this must not be used for.
    Built from the run so it is specific and cannot be a blank template."""
    n = run.get("population", {}).get("n", 0)
    frame = run.get("frame") or {}
    level = frame.get("level") or "none"
    calibrated = ("matched to published distributions on " + ", ".join(frame.get("matched_exactly") or []) + (
        " and weighted on " + ", ".join(frame.get("weighted_only") or []) if frame.get("weighted_only") else "")) if level not in ("none", None) else "not matched to any published distribution"
    est = frame.get("estimated") or []
    ev = run.get("evidence") or {}
    ev_line = ", ".join(f"{v} {k}" for k, v in sorted(ev.items())) or "no evidence items"
    return (
        "SYNTHETIC POPULATION STATEMENT\n"
        f"Every figure in this output was produced by {n} synthetic twins: language-model personas written from the evidence on file, "
        f"not survey respondents, patients, clinicians or members of the public. The population was {calibrated}"
        + (f"; the distribution of {', '.join(est)} was model-estimated, not published" if est else "") + ". "
        f"Its knowledge was limited to the evidence gathered for this session ({ev_line}); each twin was given only what a person of its place, role and register could plausibly reach. "
        "Shares and intervals describe this synthetic panel, not a real population, and every number was counted from the twins' answers, never typed by a model. "
        "This output must not be used as evidence of what real people think or will do, as a substitute for research with real participants, "
        "for clinical, regulatory or safety decisions, or to describe any individual. It is a modelling aid for forming and testing hypotheses before real research. "
        f"Generated {run.get('generated_at', '')} for the question: \"{run.get('question', '')}\"."
    )


# ── the run record ───────────────────────────────────────────────────────────

async def run_record(session_id: str) -> dict:
    from app.models.agent import SpawnedAgent
    from app.models.evidence import Evidence
    from app.models.measurement import Experiment, Probe
    from app.models.report import ReportQuery
    from app.models.session import AnalysisSession
    from app.services.population.builder import latest_build
    from app.services.scoping import service as scoping

    async with dbm.AsyncSessionLocal() as db:
        sess = await db.get(AnalysisSession, session_id)
        n = (await db.execute(select(func.count(SpawnedAgent.id)).where(SpawnedAgent.session_id == session_id))).scalar_one()
        ev_rows = (await db.execute(select(Evidence.source_class, func.count(Evidence.id)).where(Evidence.session_id == session_id, Evidence.excluded == False)  # noqa: E712
                                    .group_by(Evidence.source_class))).all()
        probes = (await db.execute(select(Probe).where(Probe.session_id == session_id, Probe.status == "complete").order_by(Probe.created_at))).scalars().all()
        exps = (await db.execute(select(Experiment).where(Experiment.session_id == session_id, Experiment.status == "complete").order_by(Experiment.created_at))).scalars().all()
        reports = (await db.execute(select(ReportQuery).where(ReportQuery.session_id == session_id, ReportQuery.structure.isnot(None)).order_by(ReportQuery.created_at))).scalars().all()
    bld = None
    try:
        bld = await latest_build(session_id)
    except Exception:  # noqa: BLE001
        pass
    rep = ((bld.frame or {}).get("report") if bld and bld.frame else None) or {}
    snapshot = None
    try:
        snapshot = await scoping.snapshot_of(session_id)
    except Exception:  # noqa: BLE001
        pass
    return {
        "session_id": session_id, "question": sess.query if sess else "", "title": sess.title if sess else "",
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "population": {"n": int(n), "build_id": bld.id if bld else None, "mode": getattr(bld, "mode", None) if bld else None},
        "frame": {"level": rep.get("level") or "none", "matched_exactly": rep.get("matched_exactly") or [], "weighted_only": rep.get("weighted_only") or [],
                  "estimated": rep.get("estimated") or [], "ess": rep.get("ess"), "thin_cells": rep.get("thin_cells") or [], "geography": (bld.frame or {}).get("geography") if bld and bld.frame else None},
        "evidence": {str(k): int(v) for k, v in ev_rows},
        "scoping_snapshot": snapshot,
        "runs": [{"kind": "probe", "id": p.id, "instrument": p.instrument, "schema_id": p.schema_id, "seed": p.seed, "model": p.model, "prompt_hash": p.prompt_hash,
                  "agents": p.agent_count, "answered": p.answer_count, "created_at": p.created_at.isoformat() if p.created_at else None,
                  "scoped": bool(((p.aggregates or {}).get("scoping") or {}).get("scoped")) if isinstance(p.aggregates, dict) else None} for p in probes]
                + [{"kind": "experiment", "id": e.id, "instrument": getattr(e, "instrument", ""), "seed": e.seed, "model": e.model, "created_at": e.created_at.isoformat() if e.created_at else None} for e in exps],
        "reports": [{"id": r.id, "created_at": r.created_at.isoformat() if r.created_at else None} for r in reports],
    }


# ── flat files ───────────────────────────────────────────────────────────────

def _csv(rows: list[dict], columns: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in columns})
    return buf.getvalue()


RECORD_COLUMNS = ["record_id", "kind", "instrument", "label", "question", "metric", "format", "value", "low", "high", "n", "weighted_value", "effective_n",
                  "refused", "unanimity_flagged", "confidence", "frame_level", "scoped", "model", "seed", "created_at", "equity_most", "equity_most_value", "equity_least",
                  "equity_least_value", "equity_gap", "equity_significant", "top_barrier", "top_candidate", "sources_cited", "caveats"]


def records_rows(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        est = r.get("estimate") or {}
        eq = r.get("equity") or {}
        prov = r.get("provenance") or {}
        w = r.get("weighted") or {}
        out.append({
            "record_id": r.get("id"), "kind": r.get("kind"), "instrument": r.get("instrument"), "label": r.get("label"), "question": r.get("question"),
            "metric": est.get("metric"), "format": est.get("format"), "value": est.get("value"), "low": est.get("low"), "high": est.get("high"), "n": est.get("n"),
            "weighted_value": w.get("weighted"), "effective_n": w.get("ess"),
            "refused": (r.get("refusals") or {}).get("refused"), "unanimity_flagged": (r.get("unanimity") or {}).get("flagged"),
            "confidence": (r.get("confidence") or {}).get("score"), "frame_level": prov.get("frame_level"), "scoped": prov.get("scoped"),
            "model": prov.get("model"), "seed": prov.get("seed"), "created_at": prov.get("created_at"),
            "equity_most": (eq.get("most") or {}).get("label") if eq.get("available") else "", "equity_most_value": (eq.get("most") or {}).get("share") if eq.get("available") else "",
            "equity_least": (eq.get("least") or {}).get("label") if eq.get("available") else "", "equity_least_value": (eq.get("least") or {}).get("share") if eq.get("available") else "",
            "equity_gap": eq.get("gap") if eq.get("available") else "", "equity_significant": eq.get("significant") if eq.get("available") else "",
            "top_barrier": (r.get("barriers") or [{}])[0].get("theme") if r.get("barriers") else "",
            "top_candidate": (r.get("candidates") or [{}])[0].get("label") if r.get("candidates") else "",
            "sources_cited": len(r.get("sources") or []), "caveats": " | ".join(r.get("caveats") or []),
        })
    return out


SPLIT_COLUMNS = ["record_id", "label", "split", "cell", "value", "low", "high", "n", "thin"]


def split_rows(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        for key, buckets in (r.get("splits") or {}).items():
            for b in buckets or []:
                out.append({"record_id": r.get("id"), "label": r.get("label"), "split": key, "cell": b.get("value"),
                            "value": b.get("share", b.get("mean")), "low": b.get("low"), "high": b.get("high"), "n": b.get("n"), "thin": b.get("thin")})
    return out


ROSTER_COLUMNS = ["agent_id", "name", "age", "role", "stance", "segment", "region", "gender", "income_band", "deprivation", "weight", "humanity",
                  "validation_score", "knowledge_visible", "knowledge_total", "written_from"]


def roster_rows(agents: list[Any]) -> list[dict]:
    out = []
    for a in agents:
        demo = getattr(a, "demographics", None) or {}
        fr = demo.get("frame") if isinstance(demo.get("frame"), dict) else {}
        k = getattr(a, "knowledge", None) or {}
        v = getattr(a, "validation", None) or {}
        out.append({"agent_id": a.id, "name": a.name, "age": a.age, "role": a.role, "stance": getattr(a.stance, "value", a.stance), "segment": getattr(a, "segment", None),
                    "region": demo.get("region"), "gender": demo.get("gender"), "income_band": demo.get("income_band"), "deprivation": fr.get("deprivation") or demo.get("deprivation"),
                    "weight": getattr(a, "weight", None), "humanity": getattr(a, "humanity", None), "validation_score": v.get("score") if isinstance(v, dict) else None,
                    "knowledge_visible": k.get("visible") if isinstance(k, dict) else None, "knowledge_total": k.get("total") if isinstance(k, dict) else None,
                    "written_from": k.get("written_from") if isinstance(k, dict) else None})
    return out


# ── the client document ──────────────────────────────────────────────────────

def _fmt(est: dict) -> str:
    v = est.get("value")
    if v is None:
        return "n/a"
    if est.get("format") == "share":
        return f"{round(float(v) * 100)}% (95% CI {round(float(est.get('low') or 0) * 100)}–{round(float(est.get('high') or 0) * 100)}%, n={est.get('n', 0)})"
    if est.get("format") == "lift":
        return f"{float(v) * 100:+.0f} points (95% CI {float(est.get('low') or 0) * 100:+.0f} to {float(est.get('high') or 0) * 100:+.0f}, n={est.get('n', 0)})"
    return f"{v} (n={est.get('n', 0)})"


def resolve_citations(text: str, *, agents: dict[str, str], records: dict[str, dict], facts: dict[str, dict], items: dict[str, dict]) -> str:
    """Citations as a reader outside the app needs them: names, figures with their source class,
    and unsourced numbers marked as such."""
    def rec(m):
        r = records.get(m.group(1))
        return f" [{_fmt(r.get('estimate') or {})} — {r.get('label')}, model-inferred]" if r else ""
    def fact(m):
        f = facts.get(m.group(1))
        return f" [{f.get('value')} — {f.get('statistic')}, {f.get('source') or f.get('title')} {f.get('year') or ''}, {str(f.get('provenance_class') or '').replace('_', ' ')}]".replace("  ", " ") if f else ""
    def item(m):
        it = items.get(m.group(1))
        return f" [{it.get('title')}, {str(it.get('provenance_class') or '').replace('_', ' ')}]" if it else ""
    out = TWIN_RE.sub(lambda m: agents.get(m.group(1), "a twin"), text)
    out = RECORD_RE.sub(rec, out)
    out = FACT_RE.sub(fact, out)
    out = EVID_RE.sub(item, out)
    out = UNSOURCED_RE.sub(lambda m: f"{m.group(1)} [unsourced — typed by the model, not counted]", out)
    return re.sub(r"[ \t]{2,}", " ", out)


def client_markdown(*, run: dict, report: Optional[dict], records: list[dict], agents: dict[str, str], ledger: dict) -> str:
    st = statement(run)
    facts = {f["id"]: f for f in (ledger.get("facts") or [])}
    items = {i["id"]: i for i in (ledger.get("items") or [])}
    by_id = {r["id"]: r for r in records}
    lines = [f"# {run.get('title') or 'Population report'}", "", f"**Question.** {run.get('question', '')}", "", "> " + st.replace("\n", "\n> "), ""]
    structure = (report or {}).get("structure") or {}
    if structure:
        conf = (structure.get("direct_answer") or {}).get("confidence") or {}
        if conf.get("band"):
            lines += [f"**Confidence (computed): {conf['band']} · {conf.get('score')}/100** — " + "; ".join(conf.get("drivers") or []), ""]
    if records:
        lines += ["## Outcome records", "", "Every figure below was counted from the twins' answers.", ""]
        for r in records:
            eq = r.get("equity") or {}
            lines.append(f"- **{r.get('label')}** — {_fmt(r.get('estimate') or {})}; confidence {(r.get('confidence') or {}).get('score')}/100"
                         + (f"; equity: {eq['most']['label']} vs {eq['least']['label']}, gap {eq.get('gap')} points, {'a real gap' if eq.get('significant') else 'not distinguishable at this size'}" if eq.get("available") else "; equity: no deprivation levels")
                         + (f"; {len(r.get('sources') or [])} document(s) cited by the twins" if r.get("sources") else ""))
        lines.append("")
    bars = (structure.get("outcome") or {}).get("barriers") if structure else None
    if bars and bars.get("items"):
        lines += [f"## What's in the way — {bars.get('outcome', '')}", ""]
        for k, it in enumerate(bars["items"], 1):
            names = [agents.get(a) for a in it.get("agent_ids") or [] if agents.get(a)]
            lines.append(f"{k}. **{it.get('theme')}** — {it.get('count')} twins, weight {round(float(it.get('weight_mean') or 0))}/100"
                         + (f"; removed by {', '.join(it.get('removals') or [])}" if it.get("removals") else "") + (f"; raised by {', '.join(names[:4])}" if names else ""))
        lines.append("")
    cands = (structure.get("outcome") or {}).get("candidates") if structure else None
    if cands and cands.get("items"):
        lines += ["## Where the population drops off — candidate outcomes", ""]
        if cands.get("funnel"):
            lines += ["Funnel: " + " → ".join(f"{f.get('label')} {round(float(f.get('share') or 0) * 100)}%" for f in cands["funnel"]), ""]
        for it in cands["items"]:
            bars = "; ".join(f"{b.get('theme')} ({b.get('count')} twins)" for b in (it.get("barriers") or []))
            lines.append(f"{it.get('rank')}. **{it.get('from')} → {it.get('to')}** — {round(float(it.get('conversion') or 0) * 100)}% get through "
                         f"(95% CI {round(float(it.get('low') or 0) * 100)}–{round(float(it.get('high') or 0) * 100)}%, {it.get('stuck')} of {it.get('n')} stuck)"
                         + (f"; barriers: {bars}" if bars else ""))
        lines.append("")
    if report and report.get("answer"):
        lines += ["## The report", "", resolve_citations(report["answer"], agents=agents, records=by_id, facts=facts, items=items), ""]
    cav = (structure.get("outcome") or {}).get("caveats") if structure else None
    if cav:
        lines += ["## What would change this", ""] + [f"- {c.get('text')}" for c in cav] + [""]
    lines += ["---", "", st, ""]
    return "\n".join(lines)


# ── the bundle ───────────────────────────────────────────────────────────────

async def bundle(session_id: str) -> bytes:
    from app.models.agent import SpawnedAgent
    from app.models.report import ReportQuery
    from app.services.simulation import figures as figures_mod
    from app.services.simulation import records as records_mod

    run = await run_record(session_id)
    st = statement(run)
    records = await records_mod.records_for_session(session_id)
    ledger = await figures_mod.load_ledger(session_id)
    async with dbm.AsyncSessionLocal() as db:
        agents = (await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == session_id))).scalars().all()
        latest = (await db.execute(select(ReportQuery).where(ReportQuery.session_id == session_id, ReportQuery.structure.isnot(None)).order_by(ReportQuery.created_at.desc()))).scalars().first()
    names = {a.id: a.name for a in agents}
    report = {"id": latest.id, "created_at": latest.created_at.isoformat() if latest.created_at else None, "answer": latest.answer, "sources": latest.sources, "structure": latest.structure} if latest else None

    stamp = {"statement": st}
    files = {
        "STATEMENT.txt": st,
        "run.json": json.dumps({**stamp, **run}, indent=2, default=str),
        "records.json": json.dumps({**stamp, "records": records}, indent=2, default=str),
        "records.csv": "# " + st.replace("\n", " ") + "\n" + _csv(records_rows(records), RECORD_COLUMNS),
        "splits.csv": "# " + st.replace("\n", " ") + "\n" + _csv(split_rows(records), SPLIT_COLUMNS),
        "report.json": json.dumps({**stamp, "report": report}, indent=2, default=str),
        "report.md": client_markdown(run=run, report=report, records=records, agents=names, ledger=ledger),
        "sources.json": json.dumps({**stamp, **ledger}, indent=2, default=str),
        "roster.csv": "# " + st.replace("\n", " ") + "\n" + _csv(roster_rows(agents), ROSTER_COLUMNS),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()
