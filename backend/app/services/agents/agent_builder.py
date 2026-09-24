"""Agent Builder: one hand-authored twin at a time.

The analyst writes the person in words — name, job, place, background, how they relate to the
topic, how they decide and behave — and either sets the 112 dials by hand, sets some and leaves
the rest to the system, or leaves them all to the system. `build_profile` reads the words and
tunes every dial the analyst did not fix, relative to the session's query, the same way a spawn
would. An authored twin is never stored loose: it joins a lineup (an `AgentPreset`), new or
existing, and reaches a session when that lineup is loaded.

Pure helpers (`normalise_authored_agent`, `merge_fixed_dials`, `complete_dials`) do no I/O so
the validation rules are testable without a model.
"""
from __future__ import annotations

import json
import random
from typing import Any, Optional

from app.core.config import get_settings
from app.services.agents.agent_factory import DIALS_SCHEMA
from app.services.agents.profiles import AVATAR_COLORS
from app.services.evidence.llm import analyze, clip, i, obj, s

#: group → ordered dial keys, parsed from the same schema the spawn prompts use.
DIAL_KEYS: dict[str, list[str]] = {g: list(v.keys()) for g, v in json.loads(DIALS_SCHEMA).items()}
DIAL_COUNT = sum(len(v) for v in DIAL_KEYS.values())

#: The authored character fields (brief L3-01 / L3-04): free text, each optional.
CHARACTER_KEYS = ("decision_rules", "behaviour", "vocabulary", "information_diet", "failure_modes")
CHARACTER_LABELS = {
    "decision_rules": "HOW YOU DECIDE",
    "behaviour": "HOW YOU BEHAVE",
    "vocabulary": "HOW YOU TALK",
    "information_diet": "WHERE YOUR INFORMATION COMES FROM",
    "failure_modes": "WHERE YOU GO WRONG",
}
DEMOGRAPHIC_KEYS = ("gender", "region", "income_band", "education", "occupation", "geo_behavior")
STANCES = ("direct", "indirect", "neutral")

_TEXT_LIMITS = {"name": 100, "role": 150, "background": 2000, "correlation": 600, "debate_style": 600}


class AuthoredAgentError(ValueError):
    """The draft cannot become a twin yet; the message says what is missing."""


def _int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _text(v: Any, limit: int = 2000) -> str:
    return clip(str(v or "").strip(), limit)


def clean_fixed_dials(fixed: Any) -> dict[str, dict[str, int]]:
    """Keep only real dial keys with integer 0-10 values: `{group: {dial: value}}`."""
    out: dict[str, dict[str, int]] = {}
    if not isinstance(fixed, dict):
        return out
    for g, keys in DIAL_KEYS.items():
        grp = fixed.get(g)
        if not isinstance(grp, dict):
            continue
        for k in keys:
            if k in grp and grp[k] is not None and str(grp[k]).strip() != "":
                out.setdefault(g, {})[k] = _int(grp[k], 0, 10, 5)
    return out


def complete_dials(dials: Any) -> bool:
    """True when every one of the 112 dials carries a value."""
    fixed = clean_fixed_dials(dials)
    return sum(len(v) for v in fixed.values()) == DIAL_COUNT


def merge_fixed_dials(generated: Any, fixed: Any) -> dict[str, dict[str, int]]:
    """The full 112-dial profile: the model's values everywhere the analyst left the dial to the
    system, the analyst's value wherever they fixed one. Missing model values fall back to 5."""
    gen = clean_fixed_dials(generated)
    fix = clean_fixed_dials(fixed)
    out: dict[str, dict[str, int]] = {}
    for g, keys in DIAL_KEYS.items():
        out[g] = {}
        for k in keys:
            if k in fix.get(g, {}):
                out[g][k] = fix[g][k]
            else:
                out[g][k] = gen.get(g, {}).get(k, 5)
    return out


def clean_character(ch: Any) -> Optional[dict[str, str]]:
    if not isinstance(ch, dict):
        return None
    out = {k: _text(ch.get(k), 1500) for k in CHARACTER_KEYS if _text(ch.get(k), 1500)}
    return out or None


def clean_demographics(d: Any) -> dict[str, str]:
    if not isinstance(d, dict):
        return {}
    return {k: _text(d.get(k), 1200 if k == "geo_behavior" else 200) for k in DEMOGRAPHIC_KEYS if _text(d.get(k), 1200)}


def normalise_authored_agent(d: dict, *, taken_colors: Optional[list[str]] = None) -> dict:
    """Turn the builder's draft into the profile dict a lineup stores (the same shape
    `save_preset` writes). Raises AuthoredAgentError when the draft is not a twin yet."""
    if not isinstance(d, dict):
        raise AuthoredAgentError("Each agent must be an object")
    name = _text(d.get("name"), _TEXT_LIMITS["name"])
    role = _text(d.get("role"), _TEXT_LIMITS["role"])
    background = _text(d.get("background"), _TEXT_LIMITS["background"])
    if not name:
        raise AuthoredAgentError("Give the agent a name")
    if not role:
        raise AuthoredAgentError(f"Give {name} a job or role")
    if not background:
        raise AuthoredAgentError(f"Write a short description of {name}")
    dials = d.get("dials")
    if not complete_dials(dials):
        raise AuthoredAgentError(f"{name}'s sentiment profile is incomplete — build it (or set every dial) before saving")
    stance = str(d.get("stance") or "neutral").strip().lower()
    if stance not in STANCES:
        stance = "neutral"
    personality = d.get("personality") or []
    if isinstance(personality, str):
        personality = [p.strip() for p in personality.split(",")]
    personality = [_text(p, 40) for p in personality if _text(p, 40)][:8]
    demographics = clean_demographics(d.get("demographics"))
    if demographics.get("occupation") is None and role:
        demographics["occupation"] = role
    colors = [c for c in AVATAR_COLORS if c not in (taken_colors or [])] or AVATAR_COLORS
    color = d.get("avatar_color") if isinstance(d.get("avatar_color"), str) and d["avatar_color"].startswith("#") else random.choice(colors)
    energy = d.get("energy")
    try:
        energy = round(max(0.3, min(1.0, float(energy))), 2)
    except (TypeError, ValueError):
        energy = round(random.uniform(0.3, 1.0), 2)
    return {
        "name": name,
        "age": _int(d.get("age"), 16, 100, 35),
        "role": role,
        "background": background,
        "stance": stance,
        "correlation": _text(d.get("correlation"), _TEXT_LIMITS["correlation"]) or f"{role}; sees the topic from their own life and work.",
        "personality": personality or ["thoughtful"],
        "debate_style": _text(d.get("debate_style"), _TEXT_LIMITS["debate_style"]) or "Says what they think, in their own words.",
        "energy": energy,
        "avatar_color": color,
        "dials": clean_fixed_dials(dials),
        "humanity": _int(d.get("humanity"), 0, 100, 50),
        "segment": _text(d.get("segment"), 120) or None,
        "demographics": demographics,
        "character": clean_character(d.get("character")),
        "authored": True,
    }


# ── Build sentiment profile ───────────────────────────────────────────────────

_SYSTEM = """You are an expert behavioural psychologist and simulation designer. An analyst has written one
persona for a multi-agent debate simulation in their own words. Read the person carefully and set their
112-value psychological dial profile (every value an integer 0-10) RELATIVE TO THE QUERY topic — exactly the
profile this specific person would carry into that topic. Also place them on the 0-100 Expert↔Reactive scale
(0 = a cold, evidence-led expert; 50 = an ordinary person who reasons but feels; 100 = raw gut reaction) from
how they are described, and write one short sentence for the analyst on the emotional signature you gave them."""

_RULES = """DIALS INSTRUCTIONS:
- All dial values are integers 0-10 (0=none/lowest, 10=extreme/highest), tuned to THIS person on THIS query.
- sentiment: their emotional state about this topic. Give a distinct signature — a couple of dominant
  emotions running hot (7-10) and others clearly low — not a flat spread around 5.
- motivation: what drives their engagement; habit: their patterns around this category; trust: their
  trust/scepticism profile; friction: the barriers they personally hit; identity: how far the topic fits
  who they are; commercial: their commercial relationship with this space; product: how they experience
  products/services here; composite: aggregates computed logically from the rest.
- Everything the analyst wrote is authoritative: the place they live, their income, education, how they
  decide, how they behave, where their information comes from and where they go wrong must all show in the
  dials (money_pain where money is tight, low trust.authority where they distrust institutions, and so on).
- Where the analyst has ALREADY FIXED a dial its value is given below; keep the rest consistent with it."""


def _dials_schema() -> dict:
    return obj({g: obj({k: i(f"{g}.{k} 0-10") for k in keys}) for g, keys in DIAL_KEYS.items()})


def _fixed_block(fixed: dict[str, dict[str, int]]) -> str:
    lines = [f"- {g}.{k} = {v}" for g, grp in fixed.items() for k, v in grp.items()]
    if not lines:
        return "The analyst fixed no dials; set all 112."
    return "DIALS THE ANALYST FIXED (do not change; make the rest consistent with them):\n" + "\n".join(lines)


def describe_draft(d: dict) -> str:
    """The persona as prose for the model, only the fields the analyst filled."""
    demo = d.get("demographics") if isinstance(d.get("demographics"), dict) else {}
    ch = d.get("character") if isinstance(d.get("character"), dict) else {}
    rows = [
        ("Name", d.get("name")), ("Age", d.get("age")), ("Job / role", d.get("role")), ("Gender", demo.get("gender")),
        ("Lives in", demo.get("region")), ("Household income", demo.get("income_band")), ("Education", demo.get("education")),
        ("Description", d.get("background")), ("Relationship to the topic", d.get("correlation")),
        ("Personality", ", ".join(d["personality"]) if isinstance(d.get("personality"), list) else d.get("personality")),
        ("Debate style", d.get("debate_style")), ("Stance", d.get("stance")),
        ("Expert↔Reactive set by the analyst (0-100)", d.get("humanity") if d.get("humanity_fixed") else None),
        ("How their place shapes them", demo.get("geo_behavior")),
        ("How they decide", ch.get("decision_rules")), ("How they behave", ch.get("behaviour")),
        ("How they talk", ch.get("vocabulary")), ("Where their information comes from", ch.get("information_diet")),
        ("Where they go wrong", ch.get("failure_modes")),
    ]
    return "\n".join(f"{k}: {_text(v, 1500)}" for k, v in rows if _text(v, 1500))


async def build_profile(session_id: str, query: str, draft: dict) -> dict:
    """Read the draft and return `{dials, humanity, reading}`: the full 112-dial profile with the
    analyst's fixed dials kept verbatim, a suggested Expert↔Reactive value (the analyst's own when
    they fixed it), and one sentence on the signature."""
    fixed = clean_fixed_dials(draft.get("dials"))
    prose = describe_draft(draft) or "(the analyst wrote nothing yet)"
    schema = obj({
        "dials": _dials_schema(),
        "humanity": i("0-100 Expert↔Reactive placement for this person"),
        "reading": s("One sentence for the analyst: the emotional signature and what drove it"),
    })
    user = f"""QUERY (the topic every dial is relative to): {clip(query, 1500)}

THE PERSON, AS THE ANALYST WROTE THEM:
{prose}

{_fixed_block(fixed)}

{_RULES}"""
    settings = get_settings()
    out = await analyze(schema, _SYSTEM, user, session_id=session_id, label="agent_builder", model=settings.model_pro_orchestration, max_tokens=6000)
    dials = merge_fixed_dials(out.get("dials"), fixed)
    humanity = _int(draft.get("humanity"), 0, 100, 50) if draft.get("humanity_fixed") else _int(out.get("humanity"), 0, 100, 50)
    return {"dials": dials, "humanity": humanity, "reading": _text(out.get("reading"), 400)}
