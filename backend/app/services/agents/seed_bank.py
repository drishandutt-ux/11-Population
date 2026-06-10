"""Pre-built agent bank — powers FAST mode.

FAST mode does NOT call the LLM at spawn time. Instead it samples personas from a
diverse, topic-agnostic bank that is generated procedurally (no API key needed) and
cached on disk as ``app/data/agent_bank.json``. Each persona carries the full 112-dial
psychological profile, dials spread across the 0-10 range so the population is visibly
diverse. Personas are generic; they only become topic-aware when they post (the post
LLM call grounds them in the query + knowledge graph).

``sample_bank`` returns ready-to-persist ``AgentProfile`` objects honoring the requested
count, stance split and humanity/coverage — instantly.
"""
from __future__ import annotations

import json
import os
import random
import uuid
import copy

from app.services.agents.profiles import AgentProfile, AVATAR_COLORS

_BANK_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "agent_bank.json")
_BANK_SIZE = 500
_BUILD_SEED = 1101  # fixed so the committed bank is reproducible

# ── Exact 112-dial schema (group -> leaf keys), mirrors agent_factory.DIALS_SCHEMA ──
DIAL_GROUPS: dict[str, list[str]] = {
    "sentiment": ["joy", "sadness", "anger", "fear", "disgust", "surprise", "trust", "anticipation",
                  "pride", "shame", "guilt", "envy", "awe", "nostalgia", "relief", "boredom",
                  "loneliness", "love", "hope", "anxiety", "confusion", "curiosity", "frustration"],
    "motivation": ["desire", "urgency", "need_intensity", "aspiration", "self_improvement", "escape",
                   "comfort", "pleasure", "mastery", "autonomy", "status", "belonging", "security",
                   "novelty", "convenience", "control"],
    "habit": ["cue_strength", "action_simplicity", "reward_immediacy", "reward_intensity",
              "repeat_frequency", "environmental_fit", "ritual_potential", "dependency_risk",
              "switching_cost", "routine_compatibility", "habit_pull"],
    "trust": ["credibility", "transparency", "social_proof", "authority", "consistency",
              "privacy_comfort", "safety", "fairness", "reliability", "reversibility", "guarantee_strength"],
    "friction": ["cognitive_load", "time_cost", "money_pain", "ambiguity", "choice_overload",
                 "technical_difficulty", "emotional_resistance", "embarrassment_risk", "social_risk",
                 "regret_risk", "friction"],
    "identity": ["self_fit", "tribe_fit", "values_fit", "aesthetic_fit", "cultural_fit",
                 "life_stage_fit", "status_lift", "taste_fit", "belonging_fit", "identity_fit"],
    "commercial": ["purchase_intent", "willingness_to_pay", "perceived_value", "premium_justification",
                   "repeat_intent", "referral_intent", "churn_risk", "upgrade_intent",
                   "objection_intensity", "price_pain"],
    "product": ["ease", "reward_clarity", "shareability", "delight", "usefulness", "memorability",
                "clarity", "confidence", "satisfaction", "emotional_fit"],
    "composite": ["human_resonance", "product_emotional_fit", "retention_potential", "share_potential",
                  "desire_trust", "habit_potential", "virality_potential", "product_humanity",
                  "emotional_risk", "adoption_readiness"],
}

# ── Component pools (kept compact but varied) ───────────────────────────────────
_FIRST = ["Aisha", "Marcus", "Priya", "Liam", "Sofia", "Kenji", "Amara", "Noah", "Mei", "Diego",
          "Fatima", "Owen", "Ines", "Tariq", "Lena", "Hugo", "Yara", "Sven", "Nia", "Caleb",
          "Rosa", "Idris", "Anouk", "Mateo", "Zoe", "Rafael", "Greta", "Omar", "Hana", "Theo",
          "Lucia", "Dmitri", "Sade", "Felix", "Naomi", "Arjun", "Clara", "Bilal", "Esme", "Joon",
          "Maya", "Ruben", "Talia", "Andre", "Keira", "Hassan", "Petra", "Cyrus", "Nora", "Levi",
          "Imani", "Pablo", "Saoirse", "Viktor", "Dalia", "Emeka", "Freya", "Rashid", "Ingrid", "Cole"]
_LAST = ["Okafor", "Reyes", "Sharma", "Walsh", "Bianchi", "Tanaka", "Mbeki", "Cohen", "Lin", "Castro",
         "Haddad", "Murphy", "Costa", "Rahman", "Novak", "Dubois", "Saleh", "Andersson", "Mensah", "Brooks",
         "Vargas", "Khan", "Jansen", "Romero", "Park", "Silva", "Schmidt", "Aziz", "Yamada", "Becker",
         "Moreno", "Ivanov", "Adeyemi", "Fischer", "Watanabe", "Nair", "Webb", "Farah", "Klein", "Cho",
         "Petrov", "Ortega", "Byrne", "Kowalski", "Osei", "Bauer", "Holm", "Da Silva", "Iqbal", "Reid"]

_DIRECT_ROLES = [
    "Product Manager", "Software Engineer", "Data Scientist", "UX Researcher", "Operations Lead",
    "Founder / CEO", "Growth Marketer", "Financial Analyst", "Supply Chain Manager", "Clinical Researcher",
    "Mechanical Engineer", "Brand Strategist", "Venture Investor", "Quant Trader", "Civil Engineer",
    "Hospitality Director", "Retail Buyer", "Pharmacist", "Logistics Planner", "Cybersecurity Analyst",
    "Industrial Designer", "Sales Director", "Actuary", "Urban Planner", "Biotech Researcher",
]
_INDIRECT_ROLES = [
    "Behavioral Economist", "Sociologist", "Public Health Advisor", "Ethics Researcher", "Anthropologist",
    "Environmental Scientist", "Policy Analyst", "Educator", "Historian", "Systems Theorist",
    "Psychologist", "Architect", "Journalist (Tech)", "Lawyer", "Sustainability Consultant",
    "HR Business Partner", "Accessibility Specialist", "Game Designer", "Documentary Producer", "Economist",
]
_NEUTRAL_ROLES = [
    "Investigative Journalist", "Retiree", "Small Business Owner", "Stay-at-home Parent", "Student",
    "Rideshare Driver", "Nurse", "Teacher", "Skeptical Blogger", "Consumer Advocate",
    "Local Shopkeeper", "Freelancer", "Warehouse Worker", "Barista", "Civil Servant",
    "Influencer (mid-tier)", "Customer Support Rep", "Tradesperson", "Part-time Gig Worker", "Hobbyist",
]

_TRAITS = ["analytical", "skeptical", "warm", "blunt", "curious", "pragmatic", "idealistic", "cautious",
           "contrarian", "optimistic", "anxious", "competitive", "empathetic", "cynical", "meticulous",
           "impulsive", "diplomatic", "stubborn", "playful", "earnest", "detached", "passionate",
           "frugal", "status-driven", "loyal", "restless", "methodical", "irreverent", "nostalgic", "ambitious"]

_DEBATE_STYLES = [
    "marshals data and citations to make the case",
    "argues from lived experience and gut feeling",
    "asks probing questions before committing to a position",
    "cuts straight to the bottom line, impatient with nuance",
    "steelmans the other side, then dismantles it",
    "leans on analogies and storytelling",
    "plays devil's advocate to stress-test ideas",
    "reframes the question to expose hidden assumptions",
    "concedes small points to win the big one",
    "digs in and rarely budges once committed",
    "is collaborative and builds on others' points",
    "is contrarian for the sake of it",
    "focuses relentlessly on risks and downsides",
    "sells the upside with infectious enthusiasm",
    "speaks plainly and distrusts jargon",
]

_DIRECT_BG = [
    "Has spent over a decade in the field and has shipped real outcomes.",
    "Built and scaled teams that live and breathe this problem daily.",
    "Deep hands-on practitioner who has seen what works and what fails.",
    "Recognized specialist who advises others in the space.",
]
_INDIRECT_BG = [
    "Studies adjacent systems and brings a cross-disciplinary lens.",
    "Works one step removed but sees patterns insiders miss.",
    "Bridges this topic with a different domain entirely.",
    "Brings rigorous outside-in thinking shaped by another field.",
]
_NEUTRAL_BG = [
    "An ordinary person with no stake beyond being affected by the outcome.",
    "Watches from the sidelines and trusts very little of the hype.",
    "Cares mostly about how this plays out in everyday life.",
    "Has been burned before and approaches new claims warily.",
]


def _clamp(v: int) -> int:
    return max(0, min(10, int(round(v))))


def _mean(*vals: int) -> int:
    return _clamp(sum(vals) / max(1, len(vals)))


def _build_dials(rng: random.Random, stance: str) -> dict:
    dials: dict[str, dict[str, int]] = {}

    # Sentiment: give each persona a distinct emotional signature (a few hot, a few cold)
    sent_keys = DIAL_GROUPS["sentiment"]
    dominant = rng.sample(sent_keys, rng.randint(2, 3))
    suppressed = rng.sample([k for k in sent_keys if k not in dominant], rng.randint(3, 4))
    sentiment = {}
    for k in sent_keys:
        if k in dominant:
            sentiment[k] = rng.randint(7, 10)
        elif k in suppressed:
            sentiment[k] = rng.randint(0, 2)
        else:
            sentiment[k] = rng.randint(2, 7)
    dials["sentiment"] = sentiment

    # Other groups: random spread with light stance bias
    def spread(keys, lo=0, hi=10):
        return {k: rng.randint(lo, hi) for k in keys}

    motivation = spread(DIAL_GROUPS["motivation"])
    habit = spread(DIAL_GROUPS["habit"])
    trust = spread(DIAL_GROUPS["trust"])
    friction = spread(DIAL_GROUPS["friction"])
    identity = spread(DIAL_GROUPS["identity"])
    commercial = spread(DIAL_GROUPS["commercial"])
    product = spread(DIAL_GROUPS["product"])

    if stance == "direct":
        trust["credibility"] = rng.randint(6, 10)
        trust["authority"] = rng.randint(6, 10)
        trust["consistency"] = rng.randint(5, 10)
        motivation["mastery"] = rng.randint(6, 10)
        product["confidence"] = rng.randint(6, 10)
        sentiment["confusion"] = min(sentiment["confusion"], rng.randint(0, 3))
    elif stance == "neutral":
        trust["credibility"] = rng.randint(0, 4)
        trust["authority"] = rng.randint(0, 4)
        friction["ambiguity"] = rng.randint(5, 10)
        commercial["objection_intensity"] = rng.randint(5, 10)
        sentiment["confusion"] = max(sentiment["confusion"], rng.randint(4, 8))

    dials["motivation"] = motivation
    dials["habit"] = habit
    dials["trust"] = trust
    dials["friction"] = friction
    dials["identity"] = identity
    dials["commercial"] = commercial
    dials["product"] = product

    # Composite: loosely derived from the groups above (logical, not random)
    dials["composite"] = {
        "human_resonance": _mean(sentiment["love"], sentiment["hope"], sentiment["joy"]),
        "product_emotional_fit": _mean(product["emotional_fit"], product["delight"], product["satisfaction"]),
        "retention_potential": _mean(habit["repeat_frequency"], product["satisfaction"], 10 - commercial["churn_risk"]),
        "share_potential": _mean(product["shareability"], commercial["referral_intent"], identity["tribe_fit"]),
        "desire_trust": _mean(motivation["desire"], trust["credibility"]),
        "habit_potential": _mean(habit["habit_pull"], habit["cue_strength"], habit["repeat_frequency"]),
        "virality_potential": _mean(product["shareability"], motivation["status"], identity["tribe_fit"]),
        "product_humanity": _mean(sentiment["trust"], product["emotional_fit"]),
        "emotional_risk": _mean(friction["emotional_resistance"], friction["regret_risk"], sentiment["anxiety"]),
        "adoption_readiness": _mean(motivation["desire"], commercial["purchase_intent"], 10 - friction["friction"]),
    }
    return dials


def _build_persona(rng: random.Random, stance: str) -> dict:
    if stance == "direct":
        role = rng.choice(_DIRECT_ROLES); bg = rng.choice(_DIRECT_BG)
        corr = f"Works directly in this space as a {role.lower()}."
    elif stance == "indirect":
        role = rng.choice(_INDIRECT_ROLES); bg = rng.choice(_INDIRECT_BG)
        corr = f"Comes at the topic sideways, through {role.lower()} work."
    else:
        role = rng.choice(_NEUTRAL_ROLES); bg = rng.choice(_NEUTRAL_BG)
        corr = "Affected by the outcome but has no professional stake in it."

    name = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
    return {
        "name": name,
        "age": rng.randint(20, 68),
        "role": role,
        "background": bg,
        "stance": stance,
        "correlation": corr,
        "personality": rng.sample(_TRAITS, 3),
        "debate_style": rng.choice(_DEBATE_STYLES),
        "energy": round(rng.uniform(0.3, 1.0), 2),
        "avatar_color": rng.choice(AVATAR_COLORS),
        "dials": _build_dials(rng, stance),
        "humanity": 0,
    }


def build_bank(n: int = _BANK_SIZE, seed: int = _BUILD_SEED) -> list[dict]:
    """Procedurally generate a diverse, topic-agnostic persona bank (reproducible)."""
    rng = random.Random(seed)
    # ~40% direct, ~35% indirect, ~25% neutral
    n_direct = round(n * 0.40)
    n_indirect = round(n * 0.35)
    n_neutral = n - n_direct - n_indirect
    bank = []
    for stance, cnt in (("direct", n_direct), ("indirect", n_indirect), ("neutral", n_neutral)):
        for _ in range(cnt):
            bank.append(_build_persona(rng, stance))
    rng.shuffle(bank)
    return bank


# ── Disk cache ──────────────────────────────────────────────────────────────────
_bank_cache: list[dict] | None = None


def load_bank() -> list[dict]:
    global _bank_cache
    if _bank_cache is not None:
        return _bank_cache
    try:
        with open(_BANK_PATH, "r") as f:
            _bank_cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _bank_cache = build_bank()
        try:
            os.makedirs(os.path.dirname(_BANK_PATH), exist_ok=True)
            with open(_BANK_PATH, "w") as f:
                json.dump(_bank_cache, f)
        except OSError:
            pass
    return _bank_cache


def _jitter_dials(dials: dict, rng: random.Random) -> dict:
    """Small ±1 perturbation on a handful of dials so sampled clones diverge."""
    out = copy.deepcopy(dials)
    for group in out.values():
        if not isinstance(group, dict):
            continue
        for k in rng.sample(list(group.keys()), min(2, len(group))):
            group[k] = _clamp(group[k] + rng.choice((-1, 1)))
    return out


def _humanize(dials: dict, humanity: int, rng: random.Random) -> dict:
    """Push a persona toward the emotional/everyday register (mirrors agent_factory)."""
    out = copy.deepcopy(dials)
    trust = out.setdefault("trust", {})
    trust["credibility"] = rng.randint(0, 3)
    trust["authority"] = rng.randint(0, 3)
    sentiment = out.setdefault("sentiment", {})
    for k in rng.sample(["anger", "fear", "anxiety", "hope", "love", "frustration", "joy"], 2):
        sentiment[k] = rng.randint(7, 10)
    comp = out.setdefault("composite", {})
    comp["human_resonance"] = rng.randint(7, 10)
    comp["product_humanity"] = rng.randint(6, 10)
    return out


def sample_bank(
    session_id: str,
    count: int,
    direct_pct: int = 33,
    indirect_pct: int = 33,
    neutral_pct: int = 34,
    humanity: int = 0,
    humanity_coverage: int = 0,
) -> list[AgentProfile]:
    """Instantly assemble a population from the pre-built bank (no LLM)."""
    rng = random.Random()
    bank = load_bank()
    by_stance: dict[str, list[dict]] = {"direct": [], "indirect": [], "neutral": []}
    for p in bank:
        by_stance.get(p.get("stance", "neutral"), by_stance["neutral"]).append(p)

    # Deterministic per-stance counts (each gets >=1; neutral absorbs rounding)
    direct_count = max(1, round(count * direct_pct / 100))
    indirect_count = max(1, round(count * indirect_pct / 100))
    neutral_count = max(0, count - direct_count - indirect_count)
    total = direct_count + indirect_count + neutral_count
    if total < count:
        neutral_count += count - total
    elif total > count:
        neutral_count = max(0, neutral_count - (total - count))

    def pick(pool: list[dict], k: int) -> list[dict]:
        if k <= 0 or not pool:
            return []
        if k <= len(pool):
            return rng.sample(pool, k)
        return [rng.choice(pool) for _ in range(k)]  # with replacement

    chosen = (
        pick(by_stance["direct"], direct_count)
        + pick(by_stance["indirect"], indirect_count)
        + pick(by_stance["neutral"], neutral_count)
    )
    rng.shuffle(chosen)

    humanity = max(0, min(100, humanity))
    humanity_coverage = max(0, min(100, humanity_coverage))
    humanized_count = round(len(chosen) * humanity_coverage / 100) if humanity > 0 else 0
    humanized_idx = set(rng.sample(range(len(chosen)), min(humanized_count, len(chosen)))) if humanized_count else set()

    profiles: list[AgentProfile] = []
    used_names: dict[str, int] = {}
    used_colors: list[str] = []
    for i, p in enumerate(chosen):
        is_human = i in humanized_idx
        dials = _jitter_dials(p["dials"], rng)
        if is_human:
            dials = _humanize(dials, humanity, rng)

        name = p["name"]
        if name in used_names:
            used_names[name] += 1
            name = f"{name} ({used_names[name]})"
        else:
            used_names[name] = 1

        color = rng.choice([c for c in AVATAR_COLORS if c not in used_colors] or AVATAR_COLORS)
        used_colors.append(color)

        profiles.append(
            AgentProfile(
                id=str(uuid.uuid4()),
                session_id=session_id,
                name=name,
                age=int(p["age"]),
                role=p["role"],
                background=p["background"],
                stance=p["stance"],
                correlation=p["correlation"],
                personality=list(p["personality"]),
                debate_style=p["debate_style"],
                energy=round(rng.uniform(0.3, 1.0), 2),
                avatar_color=color,
                dials=dials,
                humanity=humanity if is_human else 0,
            )
        )
    return profiles
