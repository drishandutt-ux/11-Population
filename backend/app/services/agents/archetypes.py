"""Archetypes: twin = archetype template + sampled attribute vector + retrieved local context
(brief L3-02). The model writes texture only.

An archetype is a hand-authored twin (Agent Builder, §7.10) promoted to a mould. When a Studio
segment is cast from one:

  1. `sample_attributes`  draws each persona's facts before any model call — age, gender, place,
                          income, education from the segment, and a cell on every sampling-frame
                          dimension drawn from the published shares (the segment's own cell most of
                          the time). Numbers, not the model, decide who exists.
  2. `local_context`      pulls the graph entities and relations that mention the persona's place
                          and role — no LLM call — so the writer sees that slice, not the whole brief.
  3. `cast_prompt`        asks the model for a name, a life story, the place paragraph and small
                          dial deviations; the archetype's character, debate style, stance and dial
                          priors are stated as rules it may not change.
  4. `enforce_archetype`  makes the rules true whatever the model returned: the drawn facts win,
                          dials stay within DIAL_DRIFT of the archetype, humanity within
                          HUMANITY_DRIFT, and the character text is copied verbatim.

Pure functions except `local_context` (reads the session graph from disk/DB cache).
"""
from __future__ import annotations

import json
import random
import re
from typing import Any, Optional

from app.services.agents.agent_builder import CHARACTER_KEYS, DIAL_KEYS, clean_fixed_dials

#: How far a cast persona's dial may sit from the archetype's (each way, 0-10 scale).
DIAL_DRIFT = 2
#: How far its Expert↔Reactive value may sit from the archetype's (0-100 scale).
HUMANITY_DRIFT = 10
#: Share of personas that take the segment's own frame cell when it has one; the rest are drawn from the published shares.
SEGMENT_CELL_SHARE = 0.75

_STOP = {"the", "and", "of", "in", "a", "an", "for", "with", "to", "on", "who", "at", "or", "by", "from", "their", "they", "are", "is",
         "people", "person", "group", "segment", "local", "general", "public", "members", "workers", "adults", "residents", "practice", "partner", "senior", "junior",
         # place and setting words: a "GP partner in a coastal practice" is a GP, not a match for every coastal segment
         "coastal", "community", "town", "towns", "area", "areas", "urban", "rural", "deprived", "affluent", "regional", "national", "england", "english", "uk", "nhs",
         "high-street", "street", "seafront", "village", "city", "county", "north", "south", "east", "west"}
_ROLE_SYNONYMS = {
    "gp": {"gp", "gps", "doctor", "doctors", "physician", "physicians", "practitioner", "practitioners"},
    "pharmacist": {"pharmacist", "pharmacists", "pharmacy"},
    "nurse": {"nurse", "nurses", "nursing"},
    "consultant": {"consultant", "consultants", "specialist", "specialists"},
    "patient": {"patient", "patients"},
    "carer": {"carer", "carers", "caregiver", "caregivers"},
    "commissioner": {"commissioner", "commissioners", "commissioning", "icb"},
    "teacher": {"teacher", "teachers", "teaching"},
    "student": {"student", "students"},
    "retired": {"retired", "retiree", "retirees", "pensioner", "pensioners"},
}


def _tokens(*texts: Any) -> set[str]:
    out: set[str] = set()
    for t in texts:
        if isinstance(t, (list, tuple)):
            out |= _tokens(*t)
            continue
        for w in re.findall(r"[a-z][a-z\-]+", str(t or "").lower()):
            if w in _STOP or len(w) < 2:
                continue
            for canon, syns in _ROLE_SYNONYMS.items():
                if w in syns:
                    w = canon
                    break
            out.add(w)
    return out


def _job_head(role: Any) -> str:
    """The job itself: "GP partner in a coastal practice" → "GP partner"; "Nurse, Blackpool" → "Nurse"."""
    return re.split(r"[,(/|·—–]| in | at | for | with | of | from | and ", str(role or ""), maxsplit=1)[0]


def _archetype_tokens(arch: dict) -> set[str]:
    """Job tokens only — the head of the role and the occupation, never the place or setting the
    role string mentions (that is what cast a GP archetype onto "older coastal residents")."""
    prof = arch.get("profile") if isinstance(arch.get("profile"), dict) else arch
    demo = prof.get("demographics") if isinstance(prof.get("demographics"), dict) else {}
    return _tokens(_job_head(arch.get("role")), _job_head(prof.get("role")), _job_head(demo.get("occupation")))


def match_archetype(seg: dict, archetypes: list[dict]) -> Optional[dict]:
    """The archetype whose job best matches the segment's name, description and typical
    occupations, or None when nothing overlaps. Deterministic: ties go to the earliest."""
    d = seg.get("demographics") or {}
    seg_tokens = _tokens(seg.get("name"), d.get("occupations"))
    desc_tokens = _tokens(seg.get("description"))
    best, best_score = None, 0.0
    for arch in archetypes:
        at = _archetype_tokens(arch)
        if not at:
            continue
        job_hits = len(at & seg_tokens)
        if not job_hits:
            continue  # the description alone never casts a segment: it mentions GPs in every patient segment too
        score = 2.0 * job_hits + 1.0 * len(at & desc_tokens)
        if score > best_score:
            best, best_score = arch, score
    return best if best_score >= 2.0 else None


def assign_archetypes(segments: list[dict], archetypes: list[dict], *, keep_manual: bool = True) -> list[dict]:
    """Set `archetype_id` / `archetype_name` on every segment that matches one. A segment the
    analyst already pointed at an archetype (or explicitly cleared, `archetype_id == ""`) is left alone."""
    for seg in segments:
        if keep_manual and "archetype_id" in seg and seg.get("archetype_manual"):
            continue
        m = match_archetype(seg, archetypes)
        seg["archetype_id"] = m["id"] if m else ""
        seg["archetype_name"] = m["name"] if m else ""
    return segments


def archetype_summary(profile: dict) -> str:
    """One line for a picker: job, place, register, the first character rule."""
    demo = profile.get("demographics") if isinstance(profile.get("demographics"), dict) else {}
    ch = profile.get("character") if isinstance(profile.get("character"), dict) else {}
    bits = [str(profile.get("role") or "")]
    if demo.get("region"):
        bits.append(str(demo["region"]))
    h = profile.get("humanity")
    if isinstance(h, int):
        bits.append(f"expert↔reactive {h}")
    first = next((str(ch[k]).strip() for k in CHARACTER_KEYS if str(ch.get(k) or "").strip()), "")
    if first:
        bits.append(first[:90] + ("…" if len(first) > 90 else ""))
    return " · ".join(b for b in bits if b)


# ── 1. the attribute vector ───────────────────────────────────────────────────

def _age_bounds(cat: dict) -> Optional[tuple[int, int]]:
    from app.services.population.frame import _age_bounds as fb
    return fb(cat)


def _draw(rng: random.Random, cats: list[dict]) -> Optional[dict]:
    weights = [max(0.0, float(c.get("share_pct") or 0)) for c in cats]
    if not cats or sum(weights) <= 0:
        return rng.choice(cats) if cats else None
    return rng.choices(cats, weights=weights, k=1)[0]


def sample_attributes(seg: dict, frame: Optional[dict], n: int, *, seed: Optional[int] = None) -> list[dict]:
    """`n` slots of fixed facts for one segment: age, gender, region, income, education and a
    cell on every frame dimension. Regions rotate through the segment's list; the gender split
    is honoured exactly; frame cells follow the published shares except that the segment's own
    cell (when the planner gave one) is taken SEGMENT_CELL_SHARE of the time."""
    rng = random.Random(seed if seed is not None else f"{seg.get('id')}:{seg.get('name')}:{n}")
    d = seg.get("demographics") or {}
    lo, hi = int(d.get("age_min") or 18), int(d.get("age_max") or 75)
    if hi < lo:
        lo, hi = hi, lo
    regions = [r for r in (d.get("regions") or []) if r]
    rng.shuffle(regions)
    female = int(d.get("gender_female_pct") if d.get("gender_female_pct") is not None else 50)
    n_female = round(n * female / 100)
    genders = ["female"] * n_female + ["male"] * (n - n_female)
    rng.shuffle(genders)
    dims = (frame or {}).get("dimensions") or []
    targets = (frame or {}).get("targets") or {}
    seg_cells = seg.get("frame_values") or {}
    slots: list[dict] = []
    for k in range(n):
        slot: dict[str, Any] = {
            "slot": k + 1,
            "age": rng.randint(lo, hi),
            "gender": genders[k] if k < len(genders) else "female",
            "region": regions[k % len(regions)] if regions else "",
            "income_band": str(d.get("income_band") or "mixed"),
            "education": str(d.get("education") or "mixed"),
            "frame": {},
        }
        for dim in dims:
            key = dim.get("key")
            tg = targets.get(key) or {}
            cats = [c for c in (tg.get("categories") or []) if c.get("label")]
            own = seg_cells.get(key)
            chosen: Optional[dict] = None
            if cats and (not own or rng.random() >= SEGMENT_CELL_SHARE):
                chosen = _draw(rng, cats)
            label = chosen["label"] if chosen else (own or "")
            if not label:
                continue
            slot["frame"][key] = label
            attr = tg.get("proxy_attribute") if tg.get("status") == "proxy" else dim.get("attribute")
            if chosen and attr == "age":
                b = _age_bounds(chosen)
                if b:
                    a_lo, a_hi = max(b[0], lo), min(b[1], hi)
                    slot["age"] = rng.randint(a_lo, a_hi) if a_lo <= a_hi else rng.randint(b[0], b[1])
            elif chosen and attr == "gender":
                lab = label.lower()
                slot["gender"] = "female" if lab.startswith(("f", "w")) else "male" if lab.startswith(("m",)) else slot["gender"]
            elif chosen and attr == "income":
                slot["income_band"] = label
            elif chosen and attr == "education":
                slot["education"] = label
        slots.append(slot)
    return slots


# ── 2. local context ──────────────────────────────────────────────────────────

def local_context(session_id: str, region: str, role: str, *, max_chars: int = 700) -> str:
    """The graph entities and relations that mention this place and job — the retrieved slice
    the writer grounds one twin in. Empty when the graph has nothing for them."""
    try:
        from app.services.knowledge_graph.lightrag_service import get_kg_context_string
        terms = sorted(_tokens(region, role))
        if not terms:
            return ""
        text = get_kg_context_string(session_id, max_entities=12, max_relations=10, focus_terms=terms)
    except Exception:  # noqa: BLE001
        return ""
    if "ENTITIES: none" in text:
        return ""
    return text[:max_chars]


# ── 3. the prompt ─────────────────────────────────────────────────────────────

_CHARACTER_LABELS = {
    "decision_rules": "How they decide", "behaviour": "How they behave", "vocabulary": "How they talk",
    "information_diet": "Where their information comes from", "failure_modes": "Where they go wrong",
}


def archetype_block(arch: dict) -> str:
    prof = arch.get("profile") if isinstance(arch.get("profile"), dict) else arch
    ch = prof.get("character") if isinstance(prof.get("character"), dict) else {}
    rules = "\n".join(f"  {_CHARACTER_LABELS[k]}: {str(ch[k]).strip()}" for k in CHARACTER_KEYS if str(ch.get(k) or "").strip()) or "  (none written)"
    dials = clean_fixed_dials(prof.get("dials"))
    return f"""THE ARCHETYPE every persona in this batch is cast from — "{arch.get('name')}", {prof.get('role')}:
Background of the mould (for tone only; do NOT copy it): {prof.get('background', '')}
Personality: {', '.join(prof.get('personality') or []) or 'unspecified'}
Debate style: {prof.get('debate_style', '')}
Relationship to the topic: {prof.get('correlation', '')}
Expert↔Reactive: {prof.get('humanity', 50)} (keep every persona within ±{HUMANITY_DRIFT})
Rules of the mould (these decide how each persona thinks and acts; you may NOT change them):
{rules}
Dial priors (0-10; every persona starts here and may move each dial by at most ±{DIAL_DRIFT}, only to reflect their fixed facts and place):
{json.dumps(dials, separators=(',', ':'))}
"""


def slots_block(slots: list[dict], contexts: dict[str, str]) -> str:
    lines = []
    for s in slots:
        place = s['region'] or "the segment's area"
        facts = f"age {s['age']}, {s['gender']}, lives in {place}, {s['income_band']} household income, education: {s['education']}"
        if s.get("frame"):
            facts += "; frame cells: " + ", ".join(f"{k} = {v}" for k, v in s["frame"].items())
        ctx = contexts.get(s.get("region") or "", "")
        lines.append(f"SLOT {s['slot']}: {facts}" + (f"\n  What we know about their place: {ctx}" if ctx else ""))
    return "\n".join(lines)


def cast_prompt(query: str, seg: dict, arch: dict, slots: list[dict], contexts: dict[str, str], constraints_text: str, taken_text: str,
                facets_prompt: str = "", dynamic_prompt: str = "", dynamic_schema: str = "") -> str:
    from app.services.agents.agent_factory import DIALS_SCHEMA
    n = len(slots)
    return f"""Cast {n} personas from ONE archetype for a synthetic population that will debate and be surveyed on this topic:

QUERY: {query}

{archetype_block(arch)}
THE SEGMENT they belong to: {seg.get('name')} — {seg.get('description', '')}
Stance: {seg.get('stance')} (every persona in this batch has this stance)
Mood on the topic: {(seg.get('sentiment') or {}).get('mood', 'mixed')}; arguments this group makes: {'; '.join((seg.get('arguments') or [])[:4]) or 'infer from the archetype'}
{constraints_text}{facets_prompt}{dynamic_prompt}
THE FIXED FACTS for each persona (drawn from the sampling frame — do NOT change any of them):
{slots_block(slots, contexts)}
{taken_text}
Your job is TEXTURE ONLY. For each slot write a different person who lives by the archetype's rules:
- a real-sounding name that fits their place and background (no two alike, none matching anyone already in the population)
- a 2-3 sentence life story consistent with the fixed facts and the archetype's job and rules
- "correlation": one sentence on how THIS person relates to the topic
- "geo_behavior": 2-3 sentences written to them as "you" on how their place shapes their take on THIS query — concrete, local, no clichés
- "occupation" / "role": the archetype's job, adapted to their place and age (a title, not a new profession)
- "personality": the archetype's traits, at most one added or swapped
- "debate_style": the archetype's, rephrased in their own register
- "humanity": within ±{HUMANITY_DRIFT} of the archetype's
- "dials": start from the archetype's priors and move a dial by at most ±{DIAL_DRIFT} only where the fixed facts or the place justify it (money_pain where income is tight, trust where the place is sceptical …)
Do NOT invent new decision rules, new information sources or a different temperament — the archetype decides those.

Return a JSON array with exactly {n} objects, one per slot, in slot order. Each object MUST have ALL of these keys:
{{
  "slot": <the slot number>,
  "name": "Full Name",
  "role": "Job Title / Role as it would appear on a panel card",
  "occupation": "their job, in a few words",
  "background": "2-3 sentence life and professional background",
  "correlation": "1 sentence",
  "personality": ["trait1", "trait2", "trait3"],
  "debate_style": "1 sentence",
  "geo_behavior": "2-3 sentence paragraph addressed to the persona as 'you'",
  "facets": {{"<population facet key>": "<one of its labels>", ...}} — one entry per POPULATION FACET listed above; {{}} when none were given,
  "humanity": <integer 0-100>,
{dynamic_schema}  "dials": {DIALS_SCHEMA}
}}

Return ONLY the JSON array, no markdown, no explanation."""


# ── 4. enforcement ────────────────────────────────────────────────────────────

def _int(v: Any, default: int) -> int:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


def _dynamic_values(dials: Any) -> dict[str, int]:
    grp = (dials or {}).get("dynamic") if isinstance(dials, dict) else None
    if not isinstance(grp, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in grp.items():
        try:
            out[str(k)] = max(0, min(10, int(round(float(v)))))
        except (TypeError, ValueError):
            continue
    return out


def _enforce_dynamic(prior_dials: Any, got_dials: Any) -> dict[str, int]:
    """The question's dynamic dials (L3-04) obey the mould exactly like the fixed 112: where the
    archetype carries a value the cast persona stays within DIAL_DRIFT of it; where it does not
    (the mould was authored for another question), the persona writer's value stands."""
    prior, got = _dynamic_values(prior_dials), _dynamic_values(got_dials)
    out = dict(got)
    for k, p in prior.items():
        v = got.get(k, p)
        out[k] = max(0, min(10, max(p - DIAL_DRIFT, min(p + DIAL_DRIFT, v))))
    return out


def enforce_archetype(arch: dict, slot: dict, d: dict) -> dict:
    """Make the mould's rules true on one model-written persona: the slot's facts overwrite
    whatever was returned, dials clamp to the archetype ±DIAL_DRIFT, humanity ±HUMANITY_DRIFT,
    the character is copied verbatim, and the persona records what it was cast from."""
    prof = arch.get("profile") if isinstance(arch.get("profile"), dict) else arch
    d = dict(d)
    d["age"] = slot["age"]
    d["gender"] = slot["gender"]
    if slot.get("region"):
        d["region"] = slot["region"]
    d["income_band"] = slot["income_band"]
    d["education"] = slot["education"]
    d["frame"] = dict(slot.get("frame") or {})
    d["role"] = str(d.get("role") or prof.get("role") or "")
    d["occupation"] = str(d.get("occupation") or d["role"])
    if not d.get("background"):
        d["background"] = str(prof.get("background") or "")
    if not d.get("debate_style"):
        d["debate_style"] = str(prof.get("debate_style") or "")
    if not d.get("personality"):
        d["personality"] = list(prof.get("personality") or [])
    base_h = _int(prof.get("humanity"), 50)
    d["humanity"] = max(0, min(100, max(base_h - HUMANITY_DRIFT, min(base_h + HUMANITY_DRIFT, _int(d.get("humanity"), base_h)))))
    prior = clean_fixed_dials(prof.get("dials"))
    got = clean_fixed_dials(d.get("dials"))
    dials: dict[str, dict[str, int]] = {}
    for g, keys in DIAL_KEYS.items():
        dials[g] = {}
        for k in keys:
            p = prior.get(g, {}).get(k, 5)
            v = got.get(g, {}).get(k, p)
            dials[g][k] = max(0, min(10, max(p - DIAL_DRIFT, min(p + DIAL_DRIFT, v))))
    dyn = _enforce_dynamic(prof.get("dials"), d.get("dials"))
    if dyn:
        dials["dynamic"] = dyn
    d["dials"] = dials
    ch = {k: str(prof["character"][k]).strip() for k in CHARACTER_KEYS if isinstance(prof.get("character"), dict) and str(prof["character"].get(k) or "").strip()}
    ch["archetype"] = {"id": arch.get("id", ""), "name": arch.get("name", "")}
    d["character"] = ch
    d["_cast"] = True
    return d


def pair_slots(slots: list[dict], dicts: list[dict]) -> list[tuple[dict, dict]]:
    """Match returned personas to slots by their `slot` number; anything numbered outside the
    batch (a model counting from 1 again) or unnumbered is paired in order, so a batch is
    never lost to its numbering."""
    wanted = {s["slot"] for s in slots}
    usable = [d for d in dicts if isinstance(d, dict) and d.get("name")]
    by_slot: dict[int, dict] = {}
    leftovers: list[dict] = []
    for d in usable:
        try:
            n = int(d.get("slot"))
        except (TypeError, ValueError):
            n = None
        if n in wanted and n not in by_slot:
            by_slot[n] = d
        else:
            leftovers.append(d)
    out = []
    for s in slots:
        d = by_slot.get(s["slot"]) or (leftovers.pop(0) if leftovers else None)
        if d:
            out.append((s, d))
    return out
