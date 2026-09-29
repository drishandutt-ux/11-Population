"""Barriers — ranked barrier attribution per gap (brief L6-05), as a Lab tool.

Every gap a report shows ("63% are not in favour", "the poorest fifth answer differently") needs
its *why*, in order, and traceable. This instrument asks each twin one structured question about
an outcome — is something in the way for you, what is it, what would remove it, how much does it
matter — then codes the free-text answers into at most seven shared barriers (and removals) after
the run, ranks them by how many twins cited each, and traces every barrier to the twins who raised
it and to the evidence those twins could actually see (the scoped knowledge units, L1-04).

Generic by design: a barrier is whatever the twins say stands in the way of the outcome the
analyst typed. The result is an outcome record like any other (`records.py`), and the report
may name barriers only from its ranked list.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from app.services.evidence.llm import enum, i, obj, s
from app.services.measurement import stats
from app.services.measurement.probe import split_keys
from app.services.measurement.instruments import InputField, Instrument, Kpi, Metric, register
from app.services.measurement.themes import apply_themes, theme_key_for

BARRIER_KEY = "barrier"
REMOVAL_KEY = "removal"
BARRIER_THEME = theme_key_for(BARRIER_KEY)
REMOVAL_THEME = theme_key_for(REMOVAL_KEY)
MAX_EVIDENCE = 5

SCHEMA = obj({
    "reasoning": s("2-3 sentences, in character: whether this outcome would actually happen for you, and what gets in the way"),
    "blocked": enum(["yes", "partly", "no"],
                    "yes = something stops this outcome for you; partly = it would happen with difficulty or delay; no = nothing is in the way"),
    "barrier": s("If yes or partly: the single biggest thing in the way, in 3-10 words of your own. Empty when no."),
    "removal": s("If yes or partly: what would have to change for it to happen, in 3-12 words. Empty when no."),
    "weight": i("How much this barrier matters to whether the outcome happens for you, 0 (barely) to 100 (decisive); 0 when no"),
})

DIRECTIVE = """

YOU ARE SAYING WHAT STANDS IN THE WAY, NOT WRITING A POST.
- This answer is private. Say what would really stop the outcome for you and people like you.
- Be concrete about the barrier: "monthly GP reviews I cannot get to" not "access"; "£200 a month" not "cost".
- The removal is the one change that would make it happen for you — a thing someone could do, not a wish.
- "no" means genuinely nothing is in the way for you. Do not invent a barrier to have something to say."""

OUTCOME_SUGGESTIONS = (
    "You take up this offer / service as described",
    "You go along with the decision in the question",
    "This happens for you and people like you within a year",
    "You switch from what you do now to this",
)


def _blocked(rows: list[dict]) -> dict:
    return stats.share_of([r["answer"].get("blocked") for r in rows], lambda v: v in ("yes", "partly"))


def _twin(r: dict) -> dict:
    a = r["answer"]
    return {"agent_id": r["agent_id"], "name": r["agent"].get("name", ""), "role": r["agent"].get("role", ""),
            "blocked": a.get("blocked", ""), "barrier": a.get(BARRIER_KEY, ""), "removal": a.get(REMOVAL_KEY, ""),
            "weight": int(a.get("weight") or 0), "reasoning": a.get("reasoning", ""),
            "deprivation": (r.get("segments") or {}).get("deprivation", "")}


def is_blocked(answer: dict) -> bool:
    return answer.get("blocked") in ("yes", "partly")


def rank_barriers(rows: list[dict], *, seed: int = 0, blocked_by: Callable[[dict], bool] = is_blocked) -> list[dict]:
    """The ranked list: one entry per coded barrier (falling back to the raw phrase before coding),
    with its share of all who answered, mean weight, the removals its twins named, and the twins.
    `blocked_by` says which answers carry a barrier (the Journey tool passes its own test)."""
    blocked = [r for r in rows if blocked_by(r["answer"])]
    groups: dict[str, list[dict]] = {}
    for r in blocked:
        key = str(r["answer"].get(BARRIER_THEME) or r["answer"].get(BARRIER_KEY) or "").strip()
        if not key:
            continue
        groups.setdefault(key, []).append(r)
    n = len(rows)
    out = []
    for theme, rs in groups.items():
        w = stats.wilson(len(rs), n) if n else {"share": 0.0, "low": 0.0, "high": 0.0}
        weights = [int(r["answer"].get("weight") or 0) for r in rs]
        removals = stats.distribution([str(r["answer"].get(REMOVAL_THEME) or r["answer"].get(REMOVAL_KEY) or "").strip() for r in rs
                                       if str(r["answer"].get(REMOVAL_THEME) or r["answer"].get(REMOVAL_KEY) or "").strip()])[:4]
        twins = sorted((_twin(r) for r in rs), key=lambda t: -t["weight"])
        out.append({
            "theme": theme, "count": len(rs), "share": w["share"], "low": w["low"], "high": w["high"],
            "weight_mean": round(sum(weights) / len(weights), 1) if weights else 0.0,
            "score": round(len(rs) * (sum(weights) / len(weights) if weights else 0) / 100.0, 2),   # count × mean weight
            "removals": removals, "agent_ids": [t["agent_id"] for t in twins], "twins": twins[:12],
            "evidence": [],   # filled after the run by `trace_evidence`
        })
    out.sort(key=lambda b: (-b["count"], -b["weight_mean"], b["theme"]))
    return out


def aggregate(rows: list[dict], spec: dict) -> dict:
    if not rows:
        return {"n": 0, "sentence": "No answers yet."}
    seed = int(spec.get("seed") or 0)
    answers = [r["answer"] for r in rows]
    head = _blocked(rows)
    weight = stats.mean_ci([int(a.get("weight") or 0) for a in answers if a.get("blocked") in ("yes", "partly")] or [0], seed=seed)
    barriers = rank_barriers(rows, seed=seed)
    segments = {key: stats.segment(rows, key, lambda rs: _blocked(rs)) for key in split_keys(rows)}
    segments = {k: v for k, v in segments.items() if v}
    top = barriers[0] if barriers else None
    margin = round((head["high"] - head["low"]) / 2 * 100)
    sentence = (
        f"{stats.pct(head['share'])} see something in the way, ±{margin} points ({head['successes']} of {head['n']})"
        + (f"; the biggest barrier is \"{top['theme']}\" ({top['count']} twins, weight {top['weight_mean']:.0f}/100)" if top else "")
        + (f", then \"{barriers[1]['theme']}\" ({barriers[1]['count']})" if len(barriers) > 1 else "") + "."
    )
    return {
        "n": len(rows),
        "headline": {"metric": "blocked_share", "label": "See a barrier", **head},
        "sentence": sentence,
        "blocked": stats.distribution([a.get("blocked", "") for a in answers]),
        "weight": weight,
        "barriers": barriers,
        "barriers_coded": any(a.get(BARRIER_THEME) for a in answers),
        "segments": segments,
        "outcome": str(spec.get("outcome") or "")[:300],
    }


_STOP = {"that", "this", "with", "have", "from", "they", "there", "their", "would", "about", "which", "when", "what", "will", "them", "then", "than",
         "into", "over", "more", "some", "most", "much", "only", "very", "just", "your", "cannot", "could", "should", "were", "been", "being", "does", "month"}


def _terms(text: str) -> set[str]:
    import re
    return {w for w in re.findall(r"[a-z£]{4,}", str(text or "").lower()) if w not in _STOP}


def _all_barriers(agg: dict) -> list[dict]:
    return list(agg.get("barriers") or [])


async def trace_evidence(probe_id: str, *, collect: Callable[[dict], list[dict]] = _all_barriers) -> None:
    """For every ranked barrier, the knowledge units the citing twins could actually see that
    speak to it: each twin's scoped retrieval for the barrier's own words, units counted across
    the twins, the top few kept with their source and provenance class. Quiet when the session
    is not scoped. `collect` returns the barrier dicts to trace inside the aggregates (the
    Journey tool nests its lists under each candidate); they are updated in place."""
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified
    from app.core import database as dbm
    from app.models.agent import SpawnedAgent
    from app.models.measurement import Probe
    from app.services.scoping import service as scoping

    async with dbm.AsyncSessionLocal() as db:
        probe = await db.get(Probe, probe_id)
        if not probe or not isinstance(probe.aggregates, dict):
            return
        agg = dict(probe.aggregates)
        targets = collect(agg)
        if not targets:
            return
        if not await scoping.is_scoped(probe.session_id):
            return
        agents = {a.id: a for a in (await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == probe.session_id))).scalars().all()}
        # What the twins actually cited comes first (L6-05: traceable to the documents used).
        from app.models.measurement import ProbeAnswer
        answers = {a.agent_id: (a.answer or {}) for a in (await db.execute(select(ProbeAnswer).where(ProbeAnswer.probe_id == probe_id))).scalars().all()}
        for b in targets:
            used: dict[str, dict] = {}
            for aid in b.get("agent_ids") or []:
                for u in (answers.get(aid) or {}).get("used_units") or []:
                    e = used.setdefault(u["unit_id"], {**u, "twins": 0, "basis": "used"})
                    e["twins"] += 1
            if used:
                b["evidence"] = sorted(used.values(), key=lambda e: (-e["twins"], e["provenance_class"]))[:MAX_EVIDENCE]
                continue
            # A unit counts only when it speaks to this barrier: it shares a word (4+ letters) with
            # the coded label or with the twins' own barrier phrases. Scoping decides who could see
            # it; the words decide whether it is about this.
            terms = _terms(b.get("theme", "")) | set().union(*(_terms(t.get("barrier", "")) for t in (b.get("twins") or [])))
            seen: dict[str, dict] = {}
            for aid in b.get("agent_ids") or []:
                agent = agents.get(aid)
                if not agent:
                    continue
                got = await scoping.retrieval_for_agent(probe.session_id, agent, b["theme"], purpose="barrier", limit=6, log=False)
                if not got:
                    continue
                _, res, _, _ = got
                for r in res.get("visible") or []:
                    u = r["unit"]
                    if terms and not (terms & _terms(u.get("text", ""))):
                        continue
                    e = seen.setdefault(u["id"], {"unit_id": u["id"], "source_ref": u.get("source_ref", ""), "provenance_class": u.get("provenance_class", ""),
                                                   "trust_tier": u.get("trust_tier", ""), "text": str(u.get("text") or "")[:220], "twins": 0, "route": r.get("route", ""), "basis": "could_see"})
                    e["twins"] += 1
            b["evidence"] = sorted(seen.values(), key=lambda e: (-e["twins"], e["provenance_class"]))[:MAX_EVIDENCE]
        probe.aggregates = agg
        flag_modified(probe, "aggregates")
        await db.commit()


async def postprocess(probe_ids: list[str], model: str) -> None:
    await apply_themes(probe_ids, model=model, fields=[BARRIER_KEY, REMOVAL_KEY])
    for pid in probe_ids:
        try:
            await trace_evidence(pid)
        except Exception as e:  # noqa: BLE001 — tracing is a convenience; the ranking stands without it
            print(f"[barriers] evidence tracing failed for {pid}: {type(e).__name__}: {e}")


INPUTS = (
    InputField(
        key="outcome", type="textarea", label="The outcome", required=True,
        help="The thing you want to happen, as the twin would experience it. Every twin is asked what stands in its way for them.",
        placeholder="You take up this offer as described",
        default_from="session_query",
        suggestions=OUTCOME_SUGGESTIONS,
    ),
)

KPIS = (
    Kpi("blocked_share", "See a barrier", "share", "Share who say something is in the way (yes or partly), with a Wilson interval."),
    Kpi("weight", "Barrier weight", "mean", "Among those blocked: how decisive the barrier is, 0-100."),
)

METRICS = (
    Metric("blocked", "See a barrier", "share", lambda a: 1.0 if a.get("blocked") in ("yes", "partly") else 0.0, primary=True,
           help="Share who see something in the way."),
    Metric("weight", "Barrier weight", "mean", lambda a: float(a.get("weight") or 0), help="0-100 among everyone (0 when nothing is in the way)."),
)

INSTRUMENT = register(Instrument(
    key="barriers",
    label="Barriers",
    description="What stands in the way of an outcome, ranked: every twin names its biggest barrier and what would remove it; the answers are coded into shared barriers, ranked by who cited them, and traced to the twins and the evidence behind each.",
    answer_schema=SCHEMA,
    question="Would this outcome actually happen for you? What is the single biggest thing in the way, and what would have to change?",
    directive=DIRECTIVE,
    aggregate=aggregate,
    inputs=INPUTS,
    kpis=KPIS,
    metrics=METRICS,
    decision_key="blocked",
    driver_key=BARRIER_THEME,
    page="barriers",
    max_tokens=600,
    version=1,
    stimulus_key="outcome",
    postprocess=postprocess,
))
