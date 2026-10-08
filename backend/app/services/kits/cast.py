"""Writing personas from kit cards: the facts and beliefs are drawn; the model writes the life.

Like casting from an archetype (services/agents/archetypes.py), but the mould is a published
segment: its psychology, information diet and way of talking come from the kit, and each card
carries the person's own facts (age, gender, region, ethnicity, education, past vote) and the
beliefs this particular person holds. The model's job is texture — a name, a life, a job — and
whatever it returns, the card's facts are enforced afterwards."""
from __future__ import annotations

from typing import Any, Optional

# Card keys → how they read in the prompt.
_FACT_LABELS = {
    "age": "age", "gender": "gender", "region": "region", "ethnicity": "ethnicity", "education": "education",
    "ge2019": "voted in the 2019 general election", "eu2016": "EU referendum 2016", "income_band": "household income",
    "tenure": "housing", "religion": "religion", "work": "work", "settlement": "lives in", "class": "sees themselves as",
}

_EDU_TO_BAND = {"degree": "degree", "no degree": "secondary", "postgraduate": "postgraduate", "some college": "some college", "secondary": "secondary"}
_GENERATION_OF = [("Gen Z (18-24)", 18, 24), ("Millennials (25-40)", 25, 40), ("Gen X (41-55)", 41, 55),
                  ("Baby Boomers (56-74)", 56, 74), ("Silent Gen (75+)", 75, 120)]


def _generation(age: int) -> Optional[str]:
    for label, lo, hi in _GENERATION_OF:
        if lo <= age <= hi:
            return label
    return None


def _strength(t: float) -> str:
    return "holds the segment's outlook firmly" if t >= 0.67 else "holds it moderately, with some exceptions" if t >= 0.34 else "holds it loosely; closer to the middle than most of the segment"


def card_line(c: dict) -> str:
    facts = []
    for k in ("age", "gender", "region", "settlement", "ethnicity", "education", "income_band", "class", "tenure", "work", "religion", "ge2019", "eu2016"):
        if c.get(k) not in (None, ""):
            facts.append(f"{_FACT_LABELS[k]}: {c[k]}")
    beliefs = "\n".join(f"    - {b}" for b in c.get("beliefs") or [])
    life = "; ".join(c.get("facts") or [])
    return (f"SLOT {c['slot']}: " + "; ".join(facts) + f"\n  How firmly: {_strength(float(c.get('typicality') or 0.5))}"
            + (f"\n  Facts of their life (build the background around these): {life}" if life else "")
            + (f"\n  What this person believes (their own mix — keep every one):\n{beliefs}" if beliefs else ""))


def segment_block(kseg: dict) -> str:
    ch = kseg.get("character") or {}
    lines = [f"THE SEGMENT (published segmentation): {kseg['name']} — {kseg.get('tagline', '')}",
             f"Who they are: {kseg.get('summary', '')}"]
    if kseg.get("psychology"):
        lines.append("Their psychology: " + "; ".join(kseg["psychology"]))
    if kseg.get("priorities"):
        lines.append("What they care about most: " + ", ".join(kseg["priorities"]))
    if ch.get("information_diet"):
        lines.append(f"Where their information comes from: {ch['information_diet']}")
    if ch.get("vocabulary"):
        lines.append(f"How they talk: {ch['vocabulary']}")
    if kseg.get("life"):
        lines.append("Typical circumstances: " + "; ".join(kseg["life"]))
    if kseg.get("pen_portrait"):
        lines.append(f"A typical member, as the researchers portray one (do not copy them — write different people): {kseg['pen_portrait']}")
    findings = list(kseg.get("findings") or []) + [e.get("finding") for e in kseg.get("evidence") or [] if isinstance(e, dict) and e.get("finding")]
    if findings:
        lines.append("What the research found about this segment (let it shape their lives and views, as a tendency not a rule):\n" + "\n".join(f"  - {f}" for f in findings[:14]))
    quotes = [q.get("quote") if isinstance(q, dict) else str(q) for q in kseg.get("voice") or []]
    if quotes:
        lines.append("In their own words (focus groups):\n" + "\n".join(f"  “{q}”" for q in quotes[:6]))
    return "\n".join(lines) + "\n"


def cast_prompt(query: str, kseg: dict, cards: list[dict], constraints_text: str, taken_text: str,
                dynamic_prompt: str = "", dynamic_schema: str = "") -> str:
    from app.services.agents.agent_factory import DIALS_SCHEMA, _DIALS_INSTRUCTIONS
    n = len(cards)
    return f"""Write {n} people for a synthetic panel of the British public. They will be surveyed and will debate this topic:

QUERY: {query}

{segment_block(kseg)}
{constraints_text}{dynamic_prompt}
THE FIXED FACTS AND BELIEFS for each person (drawn from the segment's published make-up — do NOT change any of them):
{chr(10).join(card_line(c) for c in cards)}
{taken_text}
Your job is TEXTURE ONLY. For each slot write a different, ordinary member of the public who fits the facts and holds exactly those beliefs:
- a real-sounding name that fits their age, place and background (no two alike, none matching anyone already in the panel)
- "town": a real town or city inside their region
- "occupation" / "role": a job or situation that fits their age, education and segment (retired, carer, student and unemployed are all fine); ordinary jobs, not experts on the topic
- "background": 2-3 sentences of their life — household, work, money, health, what their week looks like — consistent with the facts
- "correlation": one sentence on how THIS person relates to the topic, from their own life (most people have no special stake)
- "geo_behavior": 2-3 sentences written to them as "you" on how their place shapes their take on THIS query
- "personality", "debate_style": consistent with the segment's psychology and how firmly they hold it
- "humanity": feeling-vs-logic 0-100, in the segment's usual register
- "dials": consistent with the facts, the beliefs and the segment — trust dials follow their trust in institutions, sentiment follows their mood
Do NOT make them more informed, more articulate or more moderate than the segment is. Do NOT give them views beyond their beliefs that contradict them.

Return a JSON array with exactly {n} objects, one per slot, in slot order. Each object MUST have ALL of these keys:
{{
  "slot": <the slot number>,
  "name": "Full Name",
  "town": "a real town in their region",
  "role": "Job Title / Situation as it would appear on a panel card",
  "occupation": "their job or situation, in a few words",
  "income_band": "low" | "lower-middle" | "middle" | "upper-middle" | "high",
  "background": "2-3 sentence life background",
  "correlation": "1 sentence",
  "personality": ["trait1", "trait2", "trait3"],
  "debate_style": "1 sentence",
  "geo_behavior": "2-3 sentence paragraph addressed to the persona as 'you'",
  "humanity": <integer 0-100>,
{dynamic_schema}  "dials": {DIALS_SCHEMA}
}}

{_DIALS_INSTRUCTIONS}

Return ONLY the JSON array, no markdown, no explanation."""


def enforce(kseg: dict, card: dict, d: dict) -> dict:
    """The card's facts and beliefs overwrite whatever came back; the segment's character is copied in."""
    d = dict(d)
    age = int(card.get("age") or d.get("age") or 40)
    d["age"] = age
    if card.get("gender"):
        d["gender"] = str(card["gender"]).lower()
    region = card.get("region") or ""
    town = str(d.get("town") or "").strip()
    d["region"] = f"{town}, {region}" if town and region and region.lower() not in town.lower() else (region or town)
    if card.get("education"):
        d["education"] = _EDU_TO_BAND.get(str(card["education"]).lower(), str(card["education"]).lower())
    if card.get("income_band"):
        d["income_band"] = card["income_band"]
    frame = dict(d.get("frame") or {}) if isinstance(d.get("frame"), dict) else {}
    if region:
        frame["region"] = region
    gen = _generation(age)
    if gen:
        frame["age"] = gen
    if card.get("gender"):
        frame["gender"] = str(card["gender"]).capitalize()
    for k in ("ge2019", "ethnicity", "education", "eu2016"):
        if card.get(k):
            frame[k] = card[k]
    d["frame"] = frame
    d["stance"] = "neutral"
    from app.services.agents.agent_factory import hint_band
    lo, hi = hint_band(kseg.get("humanity_hint"))
    try:
        h = int(d.get("humanity") or (lo + hi) // 2)
    except (TypeError, ValueError):
        h = (lo + hi) // 2
    d["humanity"] = max(lo, min(hi, h))
    ch = {k: str(v).strip() for k, v in (kseg.get("character") or {}).items() if str(v or "").strip()}
    ch["beliefs"] = list(card.get("beliefs") or [])
    if card.get("facts"):
        ch["life_facts"] = list(card["facts"])
    ch["kit"] = {"segment": kseg["name"], "segment_id": kseg["id"], "typicality": card.get("typicality"),
                 "facts": {k: card[k] for k in ("ethnicity", "ge2019", "eu2016", "settlement", "class", "tenure", "religion", "work") if card.get(k)}}
    d["character"] = ch
    d["_cast"] = True
    return d


def pair(cards: list[dict], dicts: list[dict]) -> list[tuple[dict, dict]]:
    from app.services.agents.archetypes import pair_slots
    return pair_slots(cards, dicts)


def as_text(v: Any) -> str:
    return str(v or "").strip()
