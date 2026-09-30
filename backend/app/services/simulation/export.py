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
    # Ingested text that never became an evidence row (a pasted document, a file) still grounded
    # the twins: it is counted here so the statement never says "no evidence" beside 86 documents.
    chunks = int(run.get("ingested_chunks") or 0)
    parts = [f"{v} {k}" for k, v in sorted(ev.items())] + ([f"{chunks} ingested text passages"] if chunks else [])
    ev_line = ", ".join(parts) or "no evidence items"
    return (
        "SYNTHETIC POPULATION STATEMENT\n"
        f"Every figure in this output was produced by {n} synthetic twins: language-model personas written from the evidence on file, "
        f"not survey respondents, patients, clinicians or members of the public. The population was {calibrated}"
        + (f"; the distribution of {', '.join(est)} was model-estimated, not published" if est else "") + ". "
        f"Its knowledge was limited to the evidence gathered for this session ({ev_line}); each twin was given only what a person of its place, role and register could plausibly reach. "
        "Shares and intervals describe this synthetic panel, not a real population, and every number was counted from the twins' answers, never typed by a model. "
        "Any headcount is a published or client-supplied denominator multiplied by a simulated share, and is no more real than the share. "
        "This output must not be used as evidence of what real people think or will do, as a substitute for research with real participants, "
        "for clinical, regulatory or safety decisions, or to describe any individual. It is a modelling aid for forming and testing hypotheses before real research. "
        f"Generated {run.get('generated_at', '')} for the question: \"{run.get('question', '')}\"."
    )


# ── the run record ───────────────────────────────────────────────────────────

async def _rules(session_id: str) -> list[dict]:
    try:
        from app.services.measurement import levers
        return await levers.rules_for_session(session_id)
    except Exception:  # noqa: BLE001
        return []


async def run_record(session_id: str) -> dict:
    from app.models.agent import SpawnedAgent
    from app.models.evidence import Evidence
    from app.models.kg import KnowledgeGraph
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
        chunks = None
        try:
            chunks = (await db.execute(select(KnowledgeGraph.chunks).where(KnowledgeGraph.session_id == session_id))).scalar_one_or_none()
        except Exception:  # noqa: BLE001
            chunks = None
        probes = (await db.execute(select(Probe).where(Probe.session_id == session_id, Probe.status == "complete").order_by(Probe.created_at))).scalars().all()
        exps = (await db.execute(select(Experiment).where(Experiment.session_id == session_id, Experiment.status == "complete").order_by(Experiment.created_at))).scalars().all()
        reports = (await db.execute(select(ReportQuery).where(ReportQuery.session_id == session_id, ReportQuery.structure.isnot(None)).order_by(ReportQuery.created_at))).scalars().all()
    bld = None
    try:
        bld = await latest_build(session_id)
    except Exception:  # noqa: BLE001
        pass
    rep = ((bld.frame or {}).get("report") if bld and bld.frame else None) or {}
    from app.services.population.frame import dimension_labels
    names = dimension_labels(rep)
    snapshot = None
    try:
        snapshot = await scoping.snapshot_of(session_id)
    except Exception:  # noqa: BLE001
        pass
    return {
        "session_id": session_id, "question": sess.query if sess else "", "title": sess.title if sess else "",
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "population": {"n": int(n), "build_id": bld.id if bld else None, "mode": getattr(bld, "mode", None) if bld else None},
        # Dimension names as a reader knows them ("Age and life stage"), never keys ("age_lifecycle").
        "frame": {"level": rep.get("level") or "none", "matched_exactly": names(rep.get("matched_exactly") or []), "weighted_only": names(rep.get("weighted_only") or []),
                  "estimated": names(rep.get("estimated") or []), "ess": rep.get("ess"), "thin_cells": rep.get("thin_cells") or [], "geography": (bld.frame or {}).get("geography") if bld and bld.frame else None,
                  "sizing": (bld.frame or {}).get("sizing") if bld and bld.frame else None},
        "evidence": {str(k): int(v) for k, v in ev_rows},
        "ingested_chunks": len(chunks or []),
        "scoping_snapshot": snapshot,
        # The assumption log (brief L4-01 / L4-02): every calibration rule, reviewed or not, that a lever run could have used.
        "calibration_rules": await _rules(session_id),
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
                  "equity_least_value", "equity_gap", "equity_significant", "top_barrier", "top_candidate", "top_candidate_people", "top_candidate_movable_share", "top_candidate_movable_people", "headcount_basis", "sources_cited", "caveats"]


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
            "top_candidate_people": (r.get("candidates") or [{}])[0].get("stuck_people") if r.get("candidates") else "",
            "top_candidate_movable_share": ((r.get("candidates") or [{}])[0].get("movability") or {}).get("movable_share", "") if r.get("candidates") else "",
            "top_candidate_movable_people": ((r.get("candidates") or [{}])[0].get("movability") or {}).get("movable_people", "") if r.get("candidates") else "",
            "headcount_basis": ((r.get("headcount") or {}).get("denominator") or {}).get("basis", "") if (r.get("headcount") or {}).get("available") else "",
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

def _opt(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _fmt(est: dict) -> str:
    """The estimate for the document. A missing interval is left out, never written as 0–0; a
    missing value reads 'not counted'."""
    v = est.get("value")
    n_part = f"n={est.get('n', 0)}"
    if v is None:
        return f"not counted ({n_part})"
    lo, hi = _opt(est.get("low")), _opt(est.get("high"))
    if est.get("format") == "share":
        ci = f"95% CI {round(lo * 100)}–{round(hi * 100)}%, " if lo is not None and hi is not None else ""
        return f"{round(float(v) * 100)}% ({ci}{n_part})"
    if est.get("format") == "lift":
        from app.services.simulation.records import round_half_up as rh
        ci = f"95% CI {rh(lo * 100):+d} to {rh(hi * 100):+d}, " if lo is not None and hi is not None else ""
        return f"{rh(float(v) * 100):+d} points ({ci}{n_part})"
    return f"{v} ({n_part})"


def _conf(r: dict) -> str:
    s = (r.get("confidence") or {}).get("score")
    return f"confidence {s}/100" if s is not None else "confidence not computed"


def _equity(eq: Optional[dict]) -> str:
    if eq is None:
        return "equity: not cut by deprivation for this kind of record"
    if not eq.get("available"):
        return "equity: no deprivation levels"
    gap = eq.get("gap")
    gap_text = f"gap {gap} points, {'a real gap' if eq.get('significant') else 'not distinguishable at this size'}" if gap is not None else "gap not computed"
    return f"equity: {eq['most']['label']} vs {eq['least']['label']}, {gap_text}"


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
    # A twin is named once per paragraph. A later citation of the same twin that points at a
    # statement ("his [[A7#P12]] claim") is a pointer with nothing to point to on paper, so it
    # goes; a later plain citation keeps the name (it may be a list). Adjacent duplicates of
    # one twin — name + handle in reports stored before collapse_repeats — fold first.
    from app.services.simulation.citations import collapse_repeats
    def twins(line: str) -> str:
        seen: set[str] = set()
        def sub(m):
            tid, again = m.group(1), m.group(1) in seen
            seen.add(tid)
            if again and "|post:" in m.group(0):
                return ""
            return agents.get(tid, "a twin")
        return TWIN_RE.sub(sub, line)
    out = "\n".join(twins(line) for line in collapse_repeats(text).split("\n"))
    out = RECORD_RE.sub(rec, out)
    out = FACT_RE.sub(fact, out)
    out = EVID_RE.sub(item, out)
    out = UNSOURCED_RE.sub(lambda m: f"{m.group(1)} [unsourced — typed by the model, not counted]", out)
    return re.sub(r"[ \t]{2,}", " ", out)


def _people_range(it: dict) -> str:
    lo, hi = _opt(it.get("stuck_low")), _opt(it.get("stuck_high"))
    if lo is None or hi is None:
        return "range not counted"
    return "held fixed" if int(lo) == int(hi) else f"{int(lo):,}–{int(hi):,}"


def client_markdown(*, run: dict, report: Optional[dict], records: list[dict], agents: dict[str, str], ledger: dict) -> str:
    from app.services.simulation.structure import coverage_line
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
        cov = structure.get("coverage")
        if cov:
            based, missing = coverage_line(cov)
            lines += [f"**What this report rests on.** {based[0].upper() + based[1:]}." + (f" Not run in this session: {missing} — the report says so where it matters rather than estimating what they would have shown." if missing else ""), ""]
    if records:
        lines += ["## Outcome records", "", "Every figure below was counted from the twins' answers. Where a tool was run more than once at the same step, only the latest run is listed.", ""]
        for r in records:
            est = r.get("estimate") or {}
            figure = _fmt(est)
            # A shift record that moved nobody reads as words, not as "+0 points".
            if r.get("summary") and (est.get("format") == "lift") and not est.get("significant"):
                figure = f"{r['summary']} ({figure})"
            runs = r.get("runs") or {}
            lines.append(f"- **{r.get('label')}** — {figure}; {_conf(r)}; {_equity(r.get('equity'))}"
                         + (f"; {len(r.get('sources') or [])} document(s) cited by the twins" if r.get("sources") else "")
                         + (f"; latest of {runs['count']} runs" if int(runs.get('count') or 0) > 1 else ""))
        lines.append("")
    bars = (structure.get("outcome") or {}).get("barriers") if structure else None
    if bars and bars.get("items"):
        lines += [f"## What's in the way — {bars.get('outcome', '')}", ""]
        for k, it in enumerate(bars["items"], 1):
            names = [agents.get(a) for a in it.get("agent_ids") or [] if agents.get(a)]
            w = _opt(it.get("weight_mean"))
            lines.append(f"{k}. **{it.get('theme')}** — {it.get('count')} twins" + (f", weight {round(w)}/100" if w is not None else "")
                         + (f"; removed by {', '.join(it.get('removals') or [])}" if it.get("removals") else "") + (f"; raised by {', '.join(names[:4])}" if names else ""))
        lines.append("")
    cands = (structure.get("outcome") or {}).get("candidates") if structure else None
    if cands and cands.get("items"):
        lines += ["## Where the population drops off — candidate outcomes", ""]
        hc = cands.get("headcount") or {}
        if hc.get("available"):
            lines += ["Headcounts: " + hc.get("sentence", "") + " Headcounts are published (or client-supplied) denominators multiplied by the simulated shares, and inherit every caveat below.", ""]
        else:
            lines += ["Headcounts: not available — " + (hc.get("reason") or "no sizing figure on file."), ""]
        if cands.get("funnel"):
            lines += ["Funnel: " + " → ".join(f"{f.get('label')} {round(float(f.get('share') or 0) * 100)}%" + (f" (≈{int(f['people']):,} people)" if f.get("people") is not None else "") for f in cands["funnel"]), ""]
        lines += ["Candidates are ranked by the movable gap first: the share of the stuck whose barrier a single partner could reach, from what the twins said would remove it.", ""]
        for it in cands["items"]:
            bars = "; ".join(f"{b.get('theme')} ({b.get('count')} twins" + (f"; {b.get('reach')}" + (f": {b.get('lever')}" if b.get("lever") else "") if b.get("reach") else "") + ")" for b in (it.get("barriers") or []))
            mv = it.get("movability") or {}
            mv_text = (f"; movable {round(float(mv.get('movable_share') or 0) * 100)}%" + (f" (≈{int(mv['movable_people']):,} people)" if mv.get("movable_people") is not None else "")
                       + (f", needs the system {round(float(mv.get('system_share') or 0) * 100)}%" if mv.get("system_share") else "")
                       + (f", structural {round(float(mv.get('structural_share') or 0) * 100)}%" if mv.get("structural_share") else "")) if mv.get("scored") else "; movability not scored"
            conv, lo, hi = _opt(it.get("conversion")), _opt(it.get("low")), _opt(it.get("high"))
            conv_text = (f"{round(conv * 100)}% get through " if conv is not None else "share not counted ") + (
                f"(95% CI {round(lo * 100)}–{round(hi * 100)}%, " if lo is not None and hi is not None else "(") + f"{it.get('stuck')} of {it.get('n')} stuck)"
            lines.append(f"{it.get('rank')}. **{it.get('from')} → {it.get('to')}** — {conv_text}"
                         + (f"; ≈{int(it['stuck_people']):,} people stuck ({_people_range(it)})" if it.get("stuck_people") is not None else "")
                         + mv_text
                         + (f"; barriers: {bars}" if bars else ""))
        lines.append("")
    cms = (structure.get("outcome") or {}).get("commitments") if structure else None
    if cms:
        lines += ["## Committed outcomes — the frozen forecasts", "",
                  "Each commitment is a copy of the modelled baseline as it stood when the outcome was chosen; later work in the session does not change it. "
                  "An observed result is a figure entered by hand with its source; whether it sits inside the modelled interval is counted, not judged.", ""]
        for k, c in enumerate(cms, 1):
            t = c.get("target") or {}
            cp = c.get("comparison")
            conv, lo, hi = _opt(c.get("conversion")), _opt(c.get("low")), _opt(c.get("high"))
            forecast = (f"forecast {round(conv * 100)}% get through" if conv is not None else "forecast not counted") + (
                f" (95% CI {round(lo * 100)}–{round(hi * 100)}%, " if lo is not None and hi is not None else " (") + f"{c.get('stuck')} of {c.get('n')} stuck)"
            ev_n, rules_n = int(c.get("evidence_items") or 0), int(c.get("rules") or 0)
            on_file = (f"{ev_n} evidence item{'s' if ev_n != 1 else ''}" if ev_n else "no evidence items") + " and " + (f"{rules_n} calibration rule{'s' if rules_n != 1 else ''}" if rules_n else "no calibration rules") + " on file"
            frame_text = f"matched to published distributions: {c.get('frame_level')}" if c.get("frame_level") and c.get("frame_level") != "none" else "not matched to published distributions"
            line = (f"{k}. **{c.get('from')} → {c.get('to')}** — committed by {c.get('committed_by') or 'nobody'}" + (f" on {str(c.get('committed_at'))[:10]}" if c.get("committed_at") else "") + f"; {forecast}"
                    + (f"; ≈{int(c['stuck_people']):,} people stuck ({_people_range(c)})" if c.get("stuck_people") is not None else "")
                    + f"; population build {c.get('build_id') or 'unknown'} ({c.get('population_n')} twins, {frame_text}); {on_file}"
                    + (f"; target {round(float(t['value']) * 100)}%" + (f" by {t['horizon']}" if t.get("horizon") else "") if t.get("value") is not None else "; no target set"))
            if cp:
                line += (f"; **observed {round(float(cp.get('observed') or 0) * 100)}%** on {cp.get('observed_date')} ({cp.get('observed_source')}): {round(float(cp.get('delta') or 0) * 100):+d} points against the forecast, "
                         + ("inside" if cp.get("inside_interval") else "outside") + " the modelled interval"
                         + (("; target " + ("met" if cp.get("target_met") else "not met")) if "target_met" in cp else ""))
            else:
                line += "; no observed result yet"
            if c.get("status") == "superseded":
                line += "; superseded by a later commitment"
            elif c.get("status") == "closed":
                line += f"; closed by {c.get('closed_by') or 'nobody'}" + (f" ({c.get('close_note')})" if c.get("close_note") else "")
            lines.append(line)
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
    # Every run stays in the export, superseded ones included; the report page shows the latest per tool and step.
    records = await records_mod.records_for_session(session_id, latest_only=False)
    ledger = await figures_mod.load_ledger(session_id)
    async with dbm.AsyncSessionLocal() as db:
        agents = (await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == session_id))).scalars().all()
        latest = (await db.execute(select(ReportQuery).where(ReportQuery.session_id == session_id, ReportQuery.structure.isnot(None)).order_by(ReportQuery.created_at.desc()))).scalars().first()
    names = {a.id: a.name for a in agents}
    report = {"id": latest.id, "created_at": latest.created_at.isoformat() if latest.created_at else None, "answer": latest.answer, "sources": latest.sources, "structure": latest.structure} if latest else None
    # The document lists the records the report was written from (latest per tool and step).
    doc_records = records_mod.latest_runs(list(records))

    stamp = {"statement": st}
    files = {
        "STATEMENT.txt": st,
        "run.json": json.dumps({**stamp, **run}, indent=2, default=str),
        "records.json": json.dumps({**stamp, "records": records}, indent=2, default=str),
        "records.csv": "# " + st.replace("\n", " ") + "\n" + _csv(records_rows(records), RECORD_COLUMNS),
        "splits.csv": "# " + st.replace("\n", " ") + "\n" + _csv(split_rows(records), SPLIT_COLUMNS),
        "report.json": json.dumps({**stamp, "report": report}, indent=2, default=str),
        "report.md": client_markdown(run=run, report=report, records=doc_records, agents=names, ledger=ledger),
        "sources.json": json.dumps({**stamp, **ledger}, indent=2, default=str),
        "roster.csv": "# " + st.replace("\n", " ") + "\n" + _csv(roster_rows(agents), ROSTER_COLUMNS),
    }
    # Commitments (brief L7-08): every frozen baseline as its own file, so the client keeps it outside the tool.
    try:
        from app.services.measurement import commitments as commitments_mod
        for c in await commitments_mod.list_for_session(session_id):
            files[f"commitments/{c['id']}.json"] = json.dumps({**stamp, "commitment": c}, indent=2, default=str)
    except Exception as e:  # noqa: BLE001
        print(f"[export] commitments unavailable for {session_id}: {type(e).__name__}: {e}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()
