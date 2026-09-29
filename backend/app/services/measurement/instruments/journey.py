"""Journey — candidate outcomes, one per step where the population drops off (brief L7-01).

The analyst used to have to nominate one outcome up front and then ask what stands in its way.
This tool turns that round. The system proposes the JOURNEY — the ordered steps a person passes
through on the way to the outcome the session question is about (`suggest_stages`: from the
question, the evidence brief, the sampling frame and the knowledge graph; the analyst edits it
before running). Every twin then places itself on that journey: the furthest step it (or the
people it serves) has actually reached, whether it will make the next step, and if not what
stops it and what would move it. From those answers the tool COUNTS a funnel — the share
reaching each step — and, at every step where twins get stuck, a CANDIDATE OUTCOME:

    "share of those at <step k> who reach <step k+1>"

with its modelled conversion and interval, the gap, how many twins are stuck there, the
barriers at that step coded and ranked exactly as the Barriers tool ranks them (who raised
each, what they cited, what would remove it), the deprivation split and a computed confidence.
Candidates are ranked by how many twins are stuck there, then by the size of the gap. That is
the root-cause analysis the TPO framework asks for, run as a model: the client gets the set
of outcomes worth pursuing rather than being asked to name one.

Generic by design: a journey is whatever steps fit the question — the brief's clinical
template (at risk → aware → assessed → initiated → retained → outcome) for a treatment
question, take-up steps for a service, adoption steps for a product. Which steps carry a
candidate is decided by the panel's answers, not fixed by the tool. Each candidate has a
stable id (`<probe id>:<from>-><to>`) so headcounts (L7-02), movability (L7-03), the portfolio
(L7-07) and a commitment (L7-08) can build on the same object.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.services.evidence.llm import analyze, arr, clip, enum, i, obj, s
from app.services.measurement import stats
from app.services.measurement.probe import split_keys
from app.services.measurement.instruments import InputField, Instrument, Kpi, Metric, register
from app.services.measurement.instruments.barriers import BARRIER_KEY, BARRIER_THEME, REMOVAL_KEY, rank_barriers, trace_evidence
from app.services.measurement.themes import apply_themes
from app.services.population import equity as equity_mod

MIN_STAGES = 3
MAX_STAGES = 8
PROGRESS = ("yes", "unlikely", "no")
STUCK = ("unlikely", "no")
MAX_BARRIER_THEMES = 12   # coded across every step at once, so a step's barriers share one vocabulary


# ── the journey itself ───────────────────────────────────────────────────────

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:40]


def stages_of(spec: dict) -> list[dict]:
    """The ordered steps from the spec, normalised: `{key, label, definition}` each. Accepts a
    list of dicts, a list of strings or one string with a step per line; keys are `step1 …`."""
    raw = spec.get("stages")
    items: list[Any]
    if isinstance(raw, str):
        items = [x.strip() for x in raw.splitlines() if x.strip()]
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    out: list[dict] = []
    for x in items:
        if isinstance(x, dict):
            label = str(x.get("label") or "").strip()
            definition = str(x.get("definition") or "").strip()
        else:
            label = str(x or "").strip()
            definition = ""
        if not label:
            continue
        out.append({"key": f"step{len(out) + 1}", "label": label[:80], "definition": definition[:240], "slug": _slug(label)})
    return out


def journey_text(stages: list[dict]) -> str:
    lines = [f"{k}. [{st['key']}] {st['label']}" + (f" — {st['definition']}" if st.get("definition") else "") for k, st in enumerate(stages, 1)]
    return "\n".join(lines)


def schema_for(spec: dict) -> dict:
    stages = stages_of(spec)
    keys = [st["key"] for st in stages] or ["step1", "step2", "step3"]
    return obj({
        "reasoning": s("2-3 sentences, in character: where you (or the people you serve) honestly are on this journey, and why you stop where you stop"),
        "answering_for": enum(["myself", "people I serve"],
                              "myself = you are one of the people this journey is about; people I serve = you are a professional answering for the people you see"),
        "reached": enum(keys, "The furthest step you (or most of the people you serve) have ACTUALLY reached, by its key"),
        "progress": enum(list(PROGRESS), "Whether you (they) will reach the NEXT step from there: yes / unlikely / no. yes when already at the last step"),
        "barrier": s("If unlikely or no: the single biggest thing stopping the next step, in 3-10 words of your own. Empty when yes."),
        "removal": s("If unlikely or no: what would have to change for the next step to happen, in 3-12 words. Empty when yes."),
        "weight": i("How decisive that barrier is for whether the next step happens, 0 (barely) to 100 (decisive); 0 when yes"),
    })


def question_for(spec: dict) -> str:
    stages = stages_of(spec)
    return (
        "THE JOURNEY (the steps, in order, on the way to the outcome in the question):\n" + journey_text(stages)
        + "\n\nWhere are you on it? Give the key of the furthest step you (or most of the people you serve) have actually reached, "
          "say whether you will make the next step, and if not, what stops you and what would move you."
    )


DIRECTIVE = """

YOU ARE PLACING YOURSELF ON A JOURNEY, NOT WRITING A POST.
- This answer is private. Say where you honestly are, from your own life — not where you would like to be.
- If you are a professional who serves these people (a clinician, a pharmacist, a caseworker, a teacher, a seller), answer
  for the people you actually see: the step most of them reach, and what stops the next one. Set answering_for accordingly.
- "reached" is a step you have actually completed, by its key. Do not skip ahead to a step you hope for.
- "progress" is honest: yes only if the next step really would happen for you (or them) as things stand.
- Be concrete about the barrier: "the 8am phone scramble for a GP slot" not "access"; "£9.90 per item" not "cost".
- The removal is the one change that would make the next step happen — something a partner could do, not a wish."""


# ── counting ─────────────────────────────────────────────────────────────────

def _index(stages: list[dict]) -> dict[str, int]:
    return {st["key"]: k for k, st in enumerate(stages)}


def _stuck(answer: dict) -> bool:
    return answer.get("progress") in STUCK


def _through(answer: dict, k: int, idx: dict[str, int]) -> bool:
    """Whether this answer counts as reaching step k+1: already past it, or at it and going on."""
    at = idx.get(answer.get("reached"), -1)
    return at > k or (at == k and answer.get("progress") == "yes")


def _conversion(rows: list[dict], k: int, idx: dict[str, int]) -> dict:
    return stats.share_of([r["answer"] for r in rows], lambda a: _through(a, k, idx))


def _completed(rows: list[dict], last: int, idx: dict[str, int]) -> dict:
    return stats.share_of([r["answer"] for r in rows], lambda a: idx.get(a.get("reached"), -1) >= last)


def funnel_of(rows: list[dict], stages: list[dict]) -> list[dict]:
    """Share of all who answered that reached each step (cumulative), with the count at exactly that step."""
    idx = _index(stages)
    n = len(rows)
    out = []
    for k, st in enumerate(stages):
        reached = sum(1 for r in rows if idx.get(r["answer"].get("reached"), -1) >= k)
        at = sum(1 for r in rows if idx.get(r["answer"].get("reached"), -1) == k)
        w = stats.wilson(reached, n) if n else {"share": 0.0, "low": 0.0, "high": 0.0}
        out.append({"key": st["key"], "label": st["label"], "definition": st.get("definition", ""), "reached": reached, "at": at,
                    "share": w["share"], "low": w["low"], "high": w["high"]})
    return out


def transitions_of(rows: list[dict], stages: list[dict], *, seed: int = 0) -> list[dict]:
    """One entry per step → next step: who is at risk (reached this step or beyond), who gets
    through, who is stuck, the modelled conversion with its interval, the gap, the ranked barriers
    among the stuck, the splits and the deprivation block."""
    idx = _index(stages)
    out = []
    for k in range(len(stages) - 1):
        frm, to = stages[k], stages[k + 1]
        at_risk = [r for r in rows if idx.get(r["answer"].get("reached"), -1) >= k]
        stuck_rows = [r for r in at_risk if idx.get(r["answer"].get("reached"), -1) == k and _stuck(r["answer"])]
        conv = _conversion(at_risk, k, idx) if at_risk else {"share": 0.0, "low": 0.0, "high": 0.0, "n": 0, "successes": 0}
        segments = {key: stats.segment(at_risk, key, lambda rs, k=k: _conversion(rs, k, idx)) for key in split_keys(at_risk)} if at_risk else {}
        segments = {sk: v for sk, v in segments.items() if v}
        barriers = rank_barriers(at_risk, seed=seed, blocked_by=lambda a, k=k: idx.get(a.get("reached"), -1) == k and _stuck(a)) if at_risk else []
        out.append({
            "id": f"{frm['key']}->{to['key']}",   # the record prefixes the probe id: `<probe>:<from>-><to>`
            "step": k + 1,
            "from": {"key": frm["key"], "label": frm["label"]},
            "to": {"key": to["key"], "label": to["label"]},
            "label": f"Share of those at '{frm['label']}' who reach '{to['label']}'",
            "n": len(at_risk),
            "through": int(conv.get("successes") or 0),
            "stuck": len(stuck_rows),
            "conversion": conv["share"], "low": conv["low"], "high": conv["high"],
            "gap": round(1.0 - float(conv["share"]), 4) if at_risk else None,
            "barriers": barriers,
            "removals": barriers[0]["removals"] if barriers else [],
            "segments": segments,
            "equity": equity_mod.equity_block(segments.get(equity_mod.KEY)),
        })
    return out


def candidates_of(transitions: list[dict]) -> list[dict]:
    """The candidate outcomes: every step where at least one twin is stuck, ranked by how many
    are stuck there, then by the size of the gap, then journey order."""
    cands = [dict(t) for t in transitions if t.get("stuck")]
    cands.sort(key=lambda t: (-t["stuck"], -(t.get("gap") or 0), t["step"]))
    for r, c in enumerate(cands, 1):
        c["rank"] = r
    return cands


def aggregate(rows: list[dict], spec: dict) -> dict:
    if not rows:
        return {"n": 0, "sentence": "No answers yet."}
    stages = stages_of(spec)
    if len(stages) < 2:
        return {"n": len(rows), "sentence": "The journey needs at least two steps."}
    seed = int(spec.get("seed") or 0)
    idx = _index(stages)
    last = len(stages) - 1
    rows = [r for r in rows if r["answer"].get("reached") in idx]
    if not rows:
        return {"n": 0, "sentence": "No twin placed itself on the journey."}
    head = _completed(rows, last, idx)
    funnel = funnel_of(rows, stages)
    transitions = transitions_of(rows, stages, seed=seed)
    candidates = candidates_of(transitions)
    segments = {key: stats.segment(rows, key, lambda rs: _completed(rs, last, idx)) for key in split_keys(rows)}
    segments = {k: v for k, v in segments.items() if v}
    margin = round((head["high"] - head["low"]) / 2 * 100)
    top = candidates[0] if candidates else None
    sentence = f"{stats.pct(head['share'])} reach '{stages[last]['label']}', ±{margin} points ({head['successes']} of {head['n']})"
    if top:
        tb = top["barriers"][0] if top["barriers"] else None
        sentence += (f"; the biggest drop-off is {top['from']['label']} → {top['to']['label']}: {stats.pct(top['conversion'])} get through, "
                     f"{top['stuck']} twin{'s' if top['stuck'] != 1 else ''} stuck"
                     + (f", top barrier \"{tb['theme']}\"" if tb else "") + ".")
    else:
        sentence += "; nobody reports being stuck at any step."
    return {
        "n": len(rows),
        "headline": {"metric": "completed_share", "label": f"Reach '{stages[last]['label']}'", **head},
        "sentence": sentence,
        "stages": stages,
        "funnel": funnel,
        "transitions": transitions,
        "candidates": candidates,
        "answering_for": stats.distribution([r["answer"].get("answering_for", "") for r in rows]),
        "progress": stats.distribution([r["answer"].get("progress", "") for r in rows]),
        "segments": segments,
        "barriers_coded": any(r["answer"].get(BARRIER_THEME) for r in rows),
    }


# ── after the run ────────────────────────────────────────────────────────────

def _candidate_barriers(agg: dict) -> list[dict]:
    """The barrier dicts to trace: every transition's list. The candidates are rebuilt from the
    transitions first so both hold the SAME dicts and the evidence lands in both."""
    if agg.get("transitions"):
        agg["candidates"] = candidates_of(agg["transitions"])
    return [b for t in (agg.get("transitions") or []) for b in (t.get("barriers") or [])]


async def postprocess(probe_ids: list[str], model: str) -> None:
    await apply_themes(probe_ids, model=model, fields=[BARRIER_KEY, REMOVAL_KEY], max_themes=MAX_BARRIER_THEMES)
    for pid in probe_ids:
        try:
            await trace_evidence(pid, collect=_candidate_barriers)
        except Exception as e:  # noqa: BLE001 — tracing is a convenience; the ranking stands without it
            print(f"[journey] evidence tracing failed for {pid}: {type(e).__name__}: {e}")


# ── proposing the journey ────────────────────────────────────────────────────

SUGGEST_SCHEMA = obj({
    "outcome": s("The outcome the question is really about, as one short noun phrase (the last step of the journey)"),
    "stages": arr(obj({
        "label": s("2-5 word name of the step, e.g. 'Assessed by a GP', 'Tried the service once'"),
        "definition": s("One sentence: who counts as having reached this step (a person can be said to be here or not)"),
    }), f"{MIN_STAGES}-{MAX_STAGES} ordered steps a person passes through on the way to the outcome, first to last; the last step IS the outcome", max_items=MAX_STAGES),
    "basis": s("One line on what in the material the steps were drawn from, or 'general knowledge' when nothing in the material described the path"),
})

SUGGEST_SYSTEM = (
    "You design the journey a person passes through on the way to an outcome, so that a panel can be asked where it drops off. "
    "Given a question, the place it is about and what is known, propose the ordered steps: each step is a state a person is either "
    "in or not (undiagnosed → diagnosed; aware → tried once → uses weekly), specific to this question and this population, in the "
    "language of the people in it. Between 3 and 8 steps, first to last; the last step is the outcome itself. For a treatment "
    "question the steps usually run: at risk (meets the criteria, unaware) → aware and seeking → assessed by the right professional "
    "→ started (first dose actually taken) → still on it at a horizon → outcome achieved. For a service or a product they run from "
    "unaware to regular use. Do not pad with steps nobody could be placed at. Use the record tool."
)


async def suggest_stages(session_id: str, question: str, *, mode: str = "pro") -> dict:
    """Propose the journey for this session's question from what the session knows: the
    evidence brief, the sampling frame and the knowledge graph. One strong-tier call."""
    from app.core.config import get_settings

    context_parts: list[str] = []
    try:
        from app.services.evidence.brief import brief_for_prompt
        from app.services.evidence.loop import latest_run
        run = await latest_run(session_id)
        if run and run.brief:
            context_parts.append("EVIDENCE BRIEF:\n" + brief_for_prompt(run.brief, 2500))
    except Exception:  # noqa: BLE001 — research is optional context
        pass
    try:
        from app.services.population.builder import latest_build
        from app.services.population.frame import frame_block_for_prompt
        bld = await latest_build(session_id)
        if bld and bld.frame:
            context_parts.append(frame_block_for_prompt(bld.frame))
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services.knowledge_graph.lightrag_service import get_kg_context_string
        kg = get_kg_context_string(session_id, max_entities=30, max_relations=20)
        if kg and "ENTITIES: none" not in kg:
            context_parts.append("WHAT IS KNOWN:\n" + clip(kg, 2500))
    except Exception:  # noqa: BLE001
        pass
    user = f"THE QUESTION: {question}\n\n" + ("\n\n".join(context_parts) if context_parts else "(no material gathered yet — draw the steps from the question alone)") + "\n\nPropose the journey."
    settings = get_settings()
    result = await analyze(SUGGEST_SCHEMA, SUGGEST_SYSTEM, user, session_id=session_id, label="journey_stages",
                           model=settings.orchestration_model(mode), max_tokens=1200)
    stages = stages_of({"stages": result.get("stages") or []})[:MAX_STAGES]
    return {"outcome": str(result.get("outcome") or "")[:120], "stages": stages, "basis": str(result.get("basis") or "")[:200],
            "grounded": bool(context_parts)}


# ── the instrument ───────────────────────────────────────────────────────────

class JourneyInstrument(Instrument):
    def schema_for(self, spec: dict) -> dict:  # type: ignore[override]
        return schema_for(spec)

    def question_for(self, spec: dict) -> str:  # type: ignore[override]
        return question_for(spec)

    def validate(self, spec: dict) -> list[str]:  # type: ignore[override]
        stages = stages_of(spec)
        if len(stages) < MIN_STAGES:
            return [f"The journey needs at least {MIN_STAGES} steps (it has {len(stages)})."]
        if len(stages) > MAX_STAGES:
            return [f"The journey can have at most {MAX_STAGES} steps (it has {len(stages)})."]
        seen = set()
        for st in stages:
            if st["slug"] in seen:
                return [f"Two steps are called '{st['label']}'."]
            seen.add(st["slug"])
        return []


INPUTS = (
    InputField(
        key="stages", type="stages", label="The journey", required=True,
        help="The ordered steps a person passes through on the way to the outcome in the question. Proposed from what the session knows; edit before running.",
    ),
)

KPIS = (
    Kpi("completed_share", "Reach the outcome", "share", "Share of all who answered that have reached the last step, with a Wilson interval."),
)

METRICS = (
    Metric("progress", "Will make the next step", "share", lambda a: 1.0 if a.get("progress") == "yes" else 0.0, primary=True,
           help="Share who say the next step will happen for them as things stand."),
    Metric("weight", "Barrier weight", "mean", lambda a: float(a.get("weight") or 0), help="0-100 among everyone (0 when the next step will happen)."),
)

INSTRUMENT = register(JourneyInstrument(
    key="journey",
    label="Journey",
    description="Where the population drops off and what to pursue: the system proposes the steps to the outcome, every twin says how far it gets and what stops the next step, and the tool hands back one candidate outcome per drop-off, ranked, with its barriers.",
    answer_schema=schema_for({}),
    question="Where are you on this journey, and what stops the next step?",
    directive=DIRECTIVE,
    aggregate=aggregate,
    inputs=INPUTS,
    kpis=KPIS,
    metrics=METRICS,
    decision_key="progress",
    driver_key=BARRIER_THEME,
    page="journey",
    max_tokens=650,
    version=1,
    stimulus_key="stimulus",
    postprocess=postprocess,
    form="journey",
))
