"""How a twin's setup becomes its answer (2026-10-28).

The setup-sensitivity test (docs/simbench-diagnostics.md §7) showed that a twin's answer follows the
model's idea of "people like this", not the twin's own configuration: stripping a twin to its
demographics left the population's pooled answer within 0.03 of the full one and its accuracy
unchanged. Drishan: *make agent responses solely based on their config and not what Haiku thinks
of it.* Three engines, chosen per Forms run with `spec.answer_engine`:

- ``persona`` (default) — today's path: the full persona prompt, one model call per twin.
- ``strict`` — one call per twin, but the group-level topic line is dropped, the twin's core facts
  (demographics + core attitudes) sit beside the question, the twin must answer from them and name
  the ones that decided it (``facts_used``).
- ``map`` — one call per QUESTION: the model writes a response map (an average adult's chances in
  that country and year, and how far each core fact moves each option); every twin's chances are
  then calculated from its own facts, with no call per twin. Who the population is — and so its
  pooled answer — comes from the twins' configuration by construction. Single-choice questions
  only; anything else falls back to ``persona``.

Core attitudes (``ATTITUDES``) are ten 0-10 positions every twin now carries in
``demographics["attitudes"]``: written by the persona writer from the segment, or, for twins built
before them, inferred once from the twin's own written life (``ensure_attitudes``).
"""
from __future__ import annotations

import asyncio
import math
from typing import Any, Optional

ENGINES = ("persona", "strict", "map")

# name → (label, what 0 means, what 10 means)
ATTITUDES: dict[str, tuple[str, str, str]] = {
    "left_right": ("Left–right placement", "far left", "far right"),
    "religiosity": ("How religious", "not at all", "very religious"),
    "trust_government": ("Trust in government and institutions", "none at all", "complete"),
    "trust_people": ("Trust in other people", "you can't be too careful", "most people can be trusted"),
    "tradition_change": ("Tradition or change", "holds to tradition", "open to change"),
    "economic_security": ("Financial security", "struggling to get by", "comfortable"),
    "life_satisfaction": ("Satisfaction with life", "very dissatisfied", "very satisfied"),
    "national_pride": ("National pride", "none", "very proud"),
    "political_interest": ("Interest in politics", "none", "very interested"),
    "environment_concern": ("Concern for the environment", "none", "very concerned"),
}
ATTITUDES_SCHEMA_TEXT = ('"attitudes": {' + ", ".join(f'"{k}": <0-10>' for k in ATTITUDES) + "}")
ATTITUDES_INSTRUCTIONS = (
    "CORE ATTITUDES (\"attitudes\"): ten positions from 0 to 10 — "
    + "; ".join(f"{k}: {lab} (0 {lo} – 10 {hi})" for k, (lab, lo, hi) in ATTITUDES.items())
    + ". Set them as this person actually holds them, consistent with their life and segment. Where a trait defines "
    "who this person is (a self-described liberal, a weekly churchgoer, someone struggling to pay the bills), set it "
    "where real people with that trait actually sit — a self-described liberal is 1-3 on left_right, a weekly "
    "churchgoer 8-10 on religiosity — not pulled to the middle. The positions that do not define them vary the way "
    "they really do among such people. Never set all ten the same.")

INCOME_LEVELS = ["low", "lower-middle", "middle", "upper-middle", "high"]
EDUCATION_LEVELS = ["secondary", "some college", "degree", "postgraduate"]
# The reference adult the response map's base is written for: every feature is entered as its
# distance from this person, scaled by the feature's range, so a population that sits away from
# the reference moves the answer — the pooled answer comes from who is in it.
REFERENCE = {"age": 45.0, "female": 0.5, "income": 2.0, "education": 1.0, **{k: 5.0 for k in ATTITUDES}}
RANGE = {"age": 60.0, "female": 1.0, "income": 4.0, "education": 3.0, **{k: 10.0 for k in ATTITUDES}}
FEATURE_LABELS = {"age": "Age (18 to 90)", "female": "Is a woman (0 or 1)", "income": "Income (low to high)",
                  "education": "Education (secondary to postgraduate)", **{k: f"{v[0]} (0 {v[1]} – 10 {v[2]})" for k, v in ATTITUDES.items()}}
MAX_EFFECT = 6.0


def engine_of(spec: dict) -> str:
    e = str((spec or {}).get("answer_engine") or "persona").strip().lower()
    return e if e in ENGINES else "persona"


def attitudes_of(agent) -> dict[str, float]:
    demo = getattr(agent, "demographics", None) or {}
    raw = demo.get("attitudes") if isinstance(demo, dict) else None
    out: dict[str, float] = {}
    if isinstance(raw, dict):
        for k in ATTITUDES:
            try:
                out[k] = max(0.0, min(10.0, float(raw.get(k))))
            except (TypeError, ValueError):
                continue
    return out


def clean_attitudes(raw: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    if isinstance(raw, dict):
        for k in ATTITUDES:
            try:
                out[k] = int(round(max(0.0, min(10.0, float(raw.get(k))))))
            except (TypeError, ValueError):
                continue
    return out


def features(agent) -> dict[str, float]:
    """The twin's numeric core facts — what the response map is applied to."""
    demo = getattr(agent, "demographics", None) or {}
    f: dict[str, float] = {}
    if getattr(agent, "age", None):
        f["age"] = float(agent.age)
    g = str(demo.get("gender") or "").lower()
    if g in ("female", "woman", "f"):
        f["female"] = 1.0
    elif g in ("male", "man", "m"):
        f["female"] = 0.0
    inc = str(demo.get("income_band") or "").lower()
    if inc in INCOME_LEVELS:
        f["income"] = float(INCOME_LEVELS.index(inc))
    edu = str(demo.get("education") or "").lower()
    if edu in EDUCATION_LEVELS:
        f["education"] = float(EDUCATION_LEVELS.index(edu))
    f.update(attitudes_of(agent))
    return f


def facts_block(agent) -> str:
    """The strict engine's anchor: the twin's own facts, in words, beside the question."""
    demo = getattr(agent, "demographics", None) or {}
    lines = [f"- Age: {agent.age}"]
    for key, label in (("gender", "Gender"), ("region", "Where you live"), ("occupation", "Work"), ("income_band", "Income"), ("education", "Education")):
        if demo.get(key):
            lines.append(f"- {label}: {demo[key]}")
    for k, v in attitudes_of(agent).items():
        lab, lo, hi = ATTITUDES[k]
        lines.append(f"- {lab}: {v:g}/10 (0 {lo}, 10 {hi})")
    return "\n".join(lines)


STRICT_RULE = """

HOW YOU ANSWER THIS FORM: you are one particular person, not a spokesperson for any group. Your answer
comes from YOUR FACTS (listed beside the question) and your own life — never from what people of your
age, country, religion or politics are "supposed" to think. Where one of your facts bears on a
question, let your chances follow it as strongly as you hold it. Where none of them does, do not
reach for a stereotype: spread your chances the way an undecided person would. In "facts_used",
name the facts that decided your answer."""

FACTS_USED = "facts_used"


def with_facts_used(schema: dict) -> dict:
    from app.services.evidence.llm import arr, s
    props = dict(schema.get("properties") or {})
    props[FACTS_USED] = arr(s(), "the facts from YOUR FACTS that decided your answer, by their label (empty if none bore on it)", max_items=6)
    req = list(schema.get("required") or [])
    if FACTS_USED not in req:
        req.append(FACTS_USED)
    return {**schema, "properties": props, "required": req}


def strict_block(agent) -> str:
    return "YOUR FACTS (answer from these, as this one person):\n" + facts_block(agent)


# ── the response map ──────────────────────────────────────────────────────────

def map_ready(spec: dict) -> bool:
    """The map engine handles single-choice likelihood questions; a form with anything else
    (routed follow-ups, multi, grids, plain picks) falls back to the persona engine."""
    from app.services.measurement.instruments import survey
    qs = survey.normalise(spec.get("questions"))
    return bool(qs) and survey.distribution_mode(spec) and all(q["type"] == "single" and not q.get("show_if") for q in qs)


def _map_schema(n_options: int, feats: list[str]) -> dict:
    from app.services.evidence.llm import i, obj, s
    opt = [f"o{k + 1}" for k in range(n_options)]
    return obj({
        "reasoning": s("2-4 sentences: which personal facts really move answers to this question, from what is known of real survey data"),
        "base": obj({o: i(f"option {k + 1}: chance (0-100) for the reference adult") for k, o in enumerate(opt)}),
        "effects": obj({f: obj({o: i("-6 to 6: log-odds change for this option going from the lowest to the highest value of this fact; 0 = no real bearing") for o in opt})
                        for f in feats}),
    })


async def response_map(*, question: str, options: list[str], country: str, year: str, population: str,
                       session_id: Optional[str], model: Optional[str]) -> dict:
    """One call: the reference adult's chances and each core fact's pull on each option."""
    from app.services.evidence.llm import analyze
    feats = list(FEATURE_LABELS)
    ref = (f"an adult in {country or 'the country'}{' in ' + year if year else ''} who is 45, has a middle income and a "
           "secondary education, and sits at 5 on every scale below (half man, half woman)")
    user = (f"QUESTION: {question}\nOPTIONS:\n" + "\n".join(f"{k + 1}. {o}" for k, o in enumerate(options))
            + f"\n\nTHE REFERENCE ADULT: {ref}.\n\nTHE PERSONAL FACTS (each twin has its own values):\n"
            + "\n".join(f"- {f}: {FEATURE_LABELS[f]}" for f in feats)
            + f"\n\nThe population being answered for (for context only — do NOT write its answer into the base; "
              f"its members' own facts will move the answer): {population}")
    system = ("You build a response model for one survey question. Give (1) \"base\": the chance of each option for the "
              "REFERENCE ADULT described — not for the population — and (2) \"effects\": for every personal fact, the "
              "change in the log-odds of each option when the fact moves from its lowest to its highest value (-6 to +6). "
              "Make the sizes realistic, from what is known in real survey data: a fact that sharply divides answers gets a "
              "large effect (political leaning on approval of a sitting president or party: 4-6; religiosity on how often "
              "someone prays or attends services: 4-6), a modest association 1-2, and 0 wherever the fact has no real "
              "bearing. Do not encode stereotypes about groups: only the individual fact's own association.")
    out = await analyze(_map_schema(len(options), feats), system, user, session_id=session_id, label="probe:map", model=model, max_tokens=3000)
    return clean_map(out, len(options))


def clean_map(raw: dict, n: int) -> dict:
    opt = [f"o{k + 1}" for k in range(n)]
    base = {o: max(0.5, float(((raw or {}).get("base") or {}).get(o) or 0)) for o in opt}
    eff: dict[str, dict[str, float]] = {}
    for f in FEATURE_LABELS:
        row = ((raw or {}).get("effects") or {}).get(f) or {}
        eff[f] = {o: max(-MAX_EFFECT, min(MAX_EFFECT, float(row.get(o) or 0))) for o in opt}
    return {"base": base, "effects": eff, "reasoning": str((raw or {}).get("reasoning") or "")[:600]}


def apply_map(m: dict, feats: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    """A twin's chances from its own facts: log(base) + Σ effect × (value − reference) / range, softmaxed.
    A fact the twin lacks sits at the reference (no pull). Returns chances 0-100 and the facts that
    moved it most, for the answer's reasoning."""
    opt = list(m["base"])
    logit = {o: math.log(m["base"][o]) for o in opt}
    pulls: list[tuple[float, str]] = []
    for f, row in m["effects"].items():
        if f not in feats:
            continue
        x = (feats[f] - REFERENCE[f]) / RANGE[f]
        if x == 0:
            continue
        size = 0.0
        for o in opt:
            d = row.get(o, 0.0) * x
            logit[o] += d
            size += abs(d)
        if size:
            pulls.append((size, f))
    top = max(logit.values())
    exp = {o: math.exp(v - top) for o, v in logit.items()}
    tot = sum(exp.values())
    chances = {o: round(100 * v / tot, 2) for o, v in exp.items()}
    return chances, [f for _, f in sorted(pulls, reverse=True)[:3]]


def map_reasoning(top: list[str], feats: dict[str, float]) -> str:
    if not top:
        return "Answered from the response map at the reference values (none of my facts moved it)."
    bits = []
    for f in top:
        v = feats[f]
        if f in ATTITUDES:
            bits.append(f"{ATTITUDES[f][0].lower()} {v:g}/10")
        elif f == "age":
            bits.append(f"age {v:g}")
        elif f == "female":
            bits.append("a woman" if v >= 0.5 else "a man")
        elif f == "income":
            bits.append(f"{INCOME_LEVELS[int(v)]} income")
        elif f == "education":
            bits.append(f"{EDUCATION_LEVELS[int(v)]} education")
    return "Calculated from my own facts — mostly " + ", ".join(bits) + "."


async def maps_for_spec(spec: dict, *, country: str, year: str, population: str, session_id: Optional[str], model: Optional[str]) -> dict[str, dict]:
    """One response map per question of the form (built side by side)."""
    from app.services.measurement.instruments import survey
    qs = survey.normalise(spec.get("questions"))
    maps = await asyncio.gather(*[response_map(question=q["text"], options=q["options"], country=country, year=year,
                                               population=population, session_id=session_id, model=model) for q in qs])
    return {q["key"]: m for q, m in zip(qs, maps)}


def map_answer(maps: dict[str, dict], agent) -> dict:
    """The answer a twin gives under the map engine — the same shape a likelihood answer has, so
    `realise`, aggregation and every reader treat it like any other."""
    feats = features(agent)
    ans: dict[str, Any] = {}
    reasons = []
    for key, m in maps.items():
        chances, top = apply_map(m, feats)
        ans[key] = chances
        reasons.append(map_reasoning(top, feats))
    ans["reasoning"] = reasons[0] if len(reasons) == 1 else " ".join(reasons)
    ans["can_answer"] = "yes"
    ans["_engine"] = "map"
    return ans


# ── core attitudes for twins built before them ────────────────────────────────

def _infer_schema(names: list[str]) -> dict:
    from app.services.evidence.llm import i, obj
    return obj({f"t{k}": obj({a: i(f"{ATTITUDES[a][0]} 0-10") for a in ATTITUDES}) for k in range(len(names))})


async def ensure_attitudes(session_id: str, *, context: str = "", model: Optional[str] = None, batch: int = 10, force: bool = False) -> int:
    """Give every twin in the session that lacks core attitudes a set, inferred once from its own
    written life (background, job, place, segment, standing). Returns how many were filled."""
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified
    from app.core import database as dbm
    from app.models.agent import SpawnedAgent
    from app.services.evidence.llm import analyze
    async with dbm.AsyncSessionLocal() as db:
        agents = [a for a in (await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == session_id))).scalars().all()
                  if force or not attitudes_of(a) or ((a.demographics or {}).get("attitudes_from") == "inferred" and force)]
    filled = 0

    async def one(chunk):
        nonlocal filled
        people = "\n\n".join(f"t{k}: {a.name}, {a.age}, {a.role}. Segment: {a.segment or '-'}. "
                              f"{(a.demographics or {}).get('region', '')}; {(a.demographics or {}).get('income_band', '')} income; "
                              f"{(a.demographics or {}).get('education', '')}. {a.background}" for k, a in enumerate(chunk))
        out = await analyze(_infer_schema([a.name for a in chunk]),
                            "You read short life descriptions and place each person on ten attitude scales, as that individual "
                            "most plausibly holds them, from their own life and the group they belong to. " + ATTITUDES_INSTRUCTIONS,
                            (f"CONTEXT: {context}\n\n" if context else "") + people, session_id=session_id, label="attitudes:infer",
                            model=model, max_tokens=2500)
        async with dbm.AsyncSessionLocal() as db:
            for k, a in enumerate(chunk):
                vals = clean_attitudes((out or {}).get(f"t{k}"))
                if not vals:
                    continue
                row = await db.get(SpawnedAgent, a.id)
                demo = dict(row.demographics or {})
                demo["attitudes"] = vals
                demo["attitudes_from"] = "inferred"
                row.demographics = demo
                flag_modified(row, "demographics")
                filled += 1
            await db.commit()

    await asyncio.gather(*[one(agents[k:k + batch]) for k in range(0, len(agents), batch)])
    return filled
