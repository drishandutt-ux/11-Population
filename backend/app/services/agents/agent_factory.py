import json
import re
import uuid
import random
import asyncio
from typing import Optional
from app.core.config import get_settings
from app.core.monitoring import tracked_messages_create
from app.services.agents.profiles import AgentProfile, AVATAR_COLORS
from app.services.knowledge_graph.lightrag_service import get_lightrag, query_rag
import anthropic

DIALS_SCHEMA = """{
  "sentiment": {"joy":0,"sadness":0,"anger":0,"fear":0,"disgust":0,"surprise":0,"trust":0,"anticipation":0,"pride":0,"shame":0,"guilt":0,"envy":0,"awe":0,"nostalgia":0,"relief":0,"boredom":0,"loneliness":0,"love":0,"hope":0,"anxiety":0,"confusion":0,"curiosity":0,"frustration":0},
  "motivation": {"desire":0,"urgency":0,"need_intensity":0,"aspiration":0,"self_improvement":0,"escape":0,"comfort":0,"pleasure":0,"mastery":0,"autonomy":0,"status":0,"belonging":0,"security":0,"novelty":0,"convenience":0,"control":0},
  "habit": {"cue_strength":0,"action_simplicity":0,"reward_immediacy":0,"reward_intensity":0,"repeat_frequency":0,"environmental_fit":0,"ritual_potential":0,"dependency_risk":0,"switching_cost":0,"routine_compatibility":0,"habit_pull":0},
  "trust": {"credibility":0,"transparency":0,"social_proof":0,"authority":0,"consistency":0,"privacy_comfort":0,"safety":0,"fairness":0,"reliability":0,"reversibility":0,"guarantee_strength":0},
  "friction": {"cognitive_load":0,"time_cost":0,"money_pain":0,"ambiguity":0,"choice_overload":0,"technical_difficulty":0,"emotional_resistance":0,"embarrassment_risk":0,"social_risk":0,"regret_risk":0,"friction":0},
  "identity": {"self_fit":0,"tribe_fit":0,"values_fit":0,"aesthetic_fit":0,"cultural_fit":0,"life_stage_fit":0,"status_lift":0,"taste_fit":0,"belonging_fit":0,"identity_fit":0},
  "commercial": {"purchase_intent":0,"willingness_to_pay":0,"perceived_value":0,"premium_justification":0,"repeat_intent":0,"referral_intent":0,"churn_risk":0,"upgrade_intent":0,"objection_intensity":0,"price_pain":0},
  "product": {"ease":0,"reward_clarity":0,"shareability":0,"delight":0,"usefulness":0,"memorability":0,"clarity":0,"confidence":0,"satisfaction":0,"emotional_fit":0},
  "composite": {"human_resonance":0,"product_emotional_fit":0,"retention_potential":0,"share_potential":0,"desire_trust":0,"habit_potential":0,"virality_potential":0,"product_humanity":0,"emotional_risk":0,"adoption_readiness":0}
}"""

# Agents are generated in batches so a large population never exceeds the model's
# output token limit (one giant call truncates the JSON → unterminated-string errors).
_BATCH_SIZE = 10

_SYSTEM_PROMPT = """You are an expert behavioral psychologist and simulation designer. You create deeply realistic
human personas for multi-agent debate simulations. Each agent gets a full psychological dial profile (112 values, all integers 0-10)
that reflects their emotional state, motivations, habits, trust patterns, friction points, identity fit,
commercial intent, product experience, and composite readiness scores — all relative to the topic being debated."""


_DIALS_INSTRUCTIONS = """DIALS INSTRUCTIONS:
- All dial values are integers 0-10 (0=none/lowest, 10=extreme/highest)
- Tune each dial to reflect this specific agent's psychological profile RELATIVE TO THE QUERY topic
- sentiment: their current emotional state about this topic
- motivation: what drives their engagement with this topic
- habit: their behavioral patterns around this category
- trust: their trust/skepticism profile
- friction: barriers they personally experience
- identity: how much the topic aligns with their self-concept
- commercial: their commercial relationship with this space
- product: how they experience products/services in this space
- composite: aggregate derived scores (compute from other dials logically)
- Make dials CONSISTENT with the agent's background, role, stance, and personality
- Direct agents should have higher credibility/authority; neutral agents higher confusion/ambiguity friction
- MAXIMIZE DIVERSITY: use the FULL 0-10 range ACROSS the population. Do NOT cluster values around 5. Make some agents intensely emotional (8-10 on several sentiment dials) and others cold and flat (0-2). Two agents discussing the same topic should have visibly DIFFERENT emotional and motivational profiles — no two agents should feel the same.
- SENTIMENT IS PRIMARY: the sentiment group is the strongest driver of how an agent speaks. Give every agent a distinct emotional signature — a couple of dominant emotions that run hot (7-10) and others that are clearly low — rather than a flat, even spread."""


#: How many characters of an uploaded survey reach the prompt. The frontend trims to the same
#: number and says so, so a large survey is never silently cut twice.
SURVEY_CHAR_LIMIT = 8000


def _mirror_block(count: int) -> str:
    """Instructions for building the population FROM a survey rather than around it.

    Without this the stance quota wins: the model fills its "direct = domain expert" slots with
    invented analysts, and a 24-respondent consumer panel ends up diluted by people who were
    never in it."""
    return f"""
SURVEY FIDELITY — THIS IS THE PRIMARY INSTRUCTION:
- The survey above is a REAL PANEL. Build this population FROM those respondents. Each agent
  must correspond to a specific respondent: keep their age, city, occupation, income band,
  commute and behaviour, and translate their scored answers into the matching dials.
- Their own words in any comment field are the best evidence you have — let them set the
  agent's register, vocabulary and what they care about.
- Do NOT invent domain experts, analysts, consultants or industry insiders to fill a quota.
  If the panel is made of ordinary consumers, the population is made of ordinary consumers.
- Assign each agent the stance that HONESTLY follows from their own relationship to the topic
  (direct = they live this decision or work in it, indirect = adjacent experience, neutral =
  little stake or undecided). Ignore any requested stance percentages — the panel decides.
- Only if there are fewer respondents than the {count} agents requested may you add further
  people, and they must be plausible members of the same population, not experts about it.
"""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


#: Two people with the same job title this far apart in age are plausibly two real people;
#: closer than this and they are the same persona invented twice.
_CLONE_AGE_WINDOW = 6


def role_head(role: str) -> str:
    """The job itself, stripped of employer and embellishment.

    "Urban Mobility Economist, Transport Policy Institute" and "Urban Mobility Economist,
    University of Leeds" are the same persona wearing different lanyards; comparing whole role
    strings misses that, which is how three urban mobility economists reached one roster."""
    # "/" matters: the model often writes "Retired Police Sergeant / Sceptical Cyclist", and
    # two of those are one persona twice however differently the second half is phrased.
    head = re.split(r"[,(/|·—–]| and | at | for | with ", str(role or ""), maxsplit=1)[0]
    return _norm(head)


def split_duplicates(agent_dicts: list[dict]) -> tuple[list[dict], list[dict]]:
    """(kept, duplicates).

    A duplicate is the same name, or the same job title at a similar age. Batches are
    generated from one prompt and cannot see each other, so each independently invents the
    obvious persona for the topic — and when a survey is mirrored, several batches each turn
    the same respondent into an agent."""
    kept: list[dict] = []
    dupes: list[dict] = []
    seen_names: set[str] = set()
    seen_roles: list[tuple[str, int]] = []
    for d in agent_dicts:
        if not isinstance(d, dict) or not d.get("name"):
            continue
        name_key = _norm(d.get("name"))
        head = role_head(d.get("role"))
        try:
            age = int(d.get("age") or 0)
        except (TypeError, ValueError):
            age = 0
        clash = (name_key and name_key in seen_names) or any(
            head and head == h and abs(age - a) <= _CLONE_AGE_WINDOW for h, a in seen_roles
        )
        if clash:
            dupes.append(d)
            continue
        seen_names.add(name_key)
        seen_roles.append((head, age))
        kept.append(d)
    return kept, dupes


def uniquify_names(agent_dicts: list[dict]) -> list[dict]:
    """Last-resort guarantee that no two agents share a name, for when a repair call fails.
    A renamed twin is still a twin, but at least the roster is navigable."""
    seen: set[str] = set()
    for d in agent_dicts:
        base = str(d.get("name") or "Unnamed")
        name = base
        n = 2
        while _norm(name) in seen:
            parts = base.split()
            name = f"{parts[0]} {chr(64 + n)}. {' '.join(parts[1:])}" if len(parts) > 1 else f"{base} {n}"
            n += 1
        seen.add(_norm(name))
        d["name"] = name
    return agent_dicts


async def generate_agents(
    session_id: str,
    query: str,
    count: int,
    profile_query: str = "",
    direct_pct: int = 33,
    indirect_pct: int = 33,
    neutral_pct: int = 34,
    doc_context: str = "",
    humanity: int = 0,
    humanity_coverage: int = 0,
    mode: str = "pro",
    evidence_brief: str = "",
    mirror_survey: bool = False,
) -> list[AgentProfile]:
    """Curate a population with the LLM. This is the PRO path (FAST mode samples the
    pre-built bank instead — see seed_bank.sample_bank). Pro uses the Sonnet tier and a
    deeper prompt that pushes a wide spread of expertise, intelligence and emotion."""
    settings = get_settings()
    gen_model = settings.orchestration_model(mode)
    rag = await get_lightrag(session_id)
    kg_summary = await query_rag(rag, query, mode="hybrid")

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # ── Population-level distribution ──────────────────────────────────────────
    direct_count = max(1, round(count * direct_pct / 100))
    indirect_count = max(1, round(count * indirect_pct / 100))
    neutral_count = max(0, count - direct_count - indirect_count)
    total = direct_count + indirect_count + neutral_count
    if total < count:
        neutral_count += count - total
    elif total > count:
        neutral_count = max(0, neutral_count - (total - count))

    humanity = max(0, min(100, humanity))
    humanity_coverage = max(0, min(100, humanity_coverage))
    humanized_count = round(count * humanity_coverage / 100) if humanity > 0 else 0
    humanized_count = max(0, min(count, humanized_count))

    profile_context = ""
    if profile_query:
        profile_context = f"\nAUDIENCE PROFILE INSTRUCTIONS:\n{profile_query}\n"
        profile_context += "Use this to shape agent demographics, backgrounds, and psychological dials.\n"
    if doc_context:
        profile_context += f"\nSURVEY / PROFILE DATA (translate to dial values):\n{doc_context[:SURVEY_CHAR_LIMIT]}\n"
        if mirror_survey:
            profile_context += _mirror_block(count)
    if evidence_brief:
        profile_context += (
            f"\n{evidence_brief[:3500]}\n"
            "GROUNDING RULES: build the population from the groups observed above. Match their stances and their share of the "
            "conversation, give agents the arguments and phrasings those groups actually use, take demographic and place signals "
            "from the evidence, and set the sentiment/trust dials to reflect each group's observed mood. Do not invent groups the "
            "evidence contradicts; where the evidence is silent, fall back to plausible domain experts and sceptics.\n"
        )

    def _humanity_block(batch_count: int, humanized: int) -> str:
        if humanized > 0 and humanity > 0:
            return f"""
HUMANITY / EMOTIONAL REGISTER (critical):
- Exactly {humanized} of the {batch_count} agents must be HIGH-HUMANITY everyday people — set their "humanity" field to {humanity}. These agents react from EMOTION and gut feeling, NOT expert analysis. For them: push sentiment dials WIDE and INTENSE (strong joy / anger / fear / anxiety / hope / love / frustration as fits the persona), keep trust.credibility and trust.authority LOW (they don't cite data or defer to authority), and keep composite analytical scores modest. They are plain-spoken, can be biased or inconsistent, and value how they FEEL over being correct.
- The remaining {batch_count - humanized} agents are analytical/expert — set their "humanity" field to 0: evidence-driven, measured, higher credibility/authority.
- Spread humanity across stances (a high-humanity agent can still be direct/indirect/neutral)."""
        return '\n- Set the "humanity" field to 0 for every agent (all analytical/expert register).'

    pro_depth_block = ""
    if mode == "pro":
        pro_depth_block = """
PRO DEPTH (curate carefully — these agents will reason on a stronger model):
- Spread INTELLIGENCE and EXPERTISE widely: include a few genuinely sharp domain authorities, several competent middle-of-the-road voices, and a few who are plainly out of their depth, confused, or simply wrong. Not everyone should sound smart.
- Spread ARTICULACY and REGISTER: some precise and rigorous, some rambling, some blunt and plain-spoken, some performatively confident while shallow.
- Make backgrounds SPECIFIC and textured (a real-sounding career arc, a concrete stake), not generic. Give each a believable reason to hold the view they hold.
- Reactions should range from measured and evidence-led to impulsive, defensive, or emotionally reactive — match each to the persona's dials."""

    def _build_prompt(batch_count: int, d: int, i: int, n: int, h: int) -> str:
        return f"""Create {batch_count} diverse agent personas to debate and analyze this topic:

QUERY: {query}

KNOWLEDGE CONTEXT:
{kg_summary[:2500]}
{profile_context}
Generate exactly:
- {d} DIRECT agents: domain experts, practitioners directly in this field
- {i} INDIRECT agents: adjacent-field experts who bring cross-domain perspective
- {n} NEUTRAL agents: skeptics, journalists, general public, contrarians
{_humanity_block(batch_count, h)}
{pro_depth_block}

Return a JSON array with exactly {batch_count} objects. Each object MUST have ALL of these keys:
{{
  "name": "Full Name",
  "age": <integer 25-65>,
  "role": "Job Title / Role",
  "background": "2-3 sentence professional background",
  "stance": "direct" | "indirect" | "neutral",
  "correlation": "1 sentence: how they relate to the topic",
  "personality": ["trait1", "trait2", "trait3"],
  "debate_style": "1 sentence describing how they argue",
  "humanity": <integer 0-100>,
  "dials": {DIALS_SCHEMA}
}}

{_DIALS_INSTRUCTIONS}

Return ONLY the JSON array, no markdown, no explanation."""

    # ── Build per-agent slots (stance + humanity flag), shuffled so the humanized
    #    subset and stances are spread evenly across batches ─────────────────────
    slots: list[tuple[str, bool]] = (
        [("direct", False)] * direct_count
        + [("indirect", False)] * indirect_count
        + [("neutral", False)] * neutral_count
    )
    order = list(range(len(slots)))
    random.shuffle(order)
    for j in order[:humanized_count]:
        slots[j] = (slots[j][0], True)
    random.shuffle(slots)

    batches = [slots[k:k + _BATCH_SIZE] for k in range(0, len(slots), _BATCH_SIZE)]

    # Bound how many persona-generation batches hit the API at once, so a 1000-agent
    # spawn (100 batches) doesn't fire 100 concurrent calls and trip rate limits.
    sem = asyncio.Semaphore(max(1, settings.spawn_concurrency))

    def _taken_block(taken: list[dict]) -> str:
        if not taken:
            return ""
        listed = "\n".join(f"- {t.get('name')} — {t.get('role')} (age {t.get('age')})" for t in taken[:40])
        return f"""

ALREADY IN THIS POPULATION — every persona you return must be a DIFFERENT person: a different
name, a different job title, a different angle. Do not produce a variation of anyone below.
{listed}
"""

    async def _gen_batch(batch: list[tuple[str, bool]], taken: list[dict], label: str = "spawn") -> list[dict]:
        bcount = len(batch)
        if bcount == 0:
            return []
        d = sum(1 for s, _ in batch if s == "direct")
        i = sum(1 for s, _ in batch if s == "indirect")
        n = sum(1 for s, _ in batch if s == "neutral")
        h = sum(1 for _, hf in batch if hf)
        async with sem:
            try:
                response = await tracked_messages_create(
                    client,
                    session_id=session_id,
                    label=label,
                    model=gen_model,
                    max_tokens=12000,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": _build_prompt(bcount, d, i, n, h) + _taken_block(taken)}],
                )
                return _parse_agents_json(response.content[0].text)
            except Exception as e:
                print(f"[agent_factory] batch generation failed ({bcount} agents): {type(e).__name__}: {e}")
                return []

    # Prevention beats repair: run the FIRST batch alone, then hand its roster to all the
    # others so they build around it instead of re-inventing the same obvious personas. Costs
    # one round-trip of latency, not one extra call — the remaining batches still run
    # concurrently.
    agent_dicts: list[dict] = []
    if batches:
        agent_dicts = await _gen_batch(batches[0], [])
        if len(batches) > 1:
            rest = await asyncio.gather(*[_gen_batch(b, agent_dicts) for b in batches[1:]])
            for r in rest:
                agent_dicts.extend(r)

    # ── Repair cross-batch collisions ──────────────────────────────────────────
    # Concurrent batches share one prompt and cannot see each other, so the obvious
    # archetypes get invented more than once. Regenerate only the collided slots, telling
    # the model exactly who is already taken.
    agent_dicts, dupes = split_duplicates(agent_dicts)
    if dupes:
        print(f"[agent_factory] {len(dupes)} duplicate persona(s) across batches — regenerating")
        slots = [(str(d.get("stance") or "neutral"), int(d.get("humanity") or 0) > 0) for d in dupes]
        try:
            replacements = await _gen_batch(slots, agent_dicts, label="spawn:repair")
            agent_dicts, _ = split_duplicates(agent_dicts + replacements)
        except Exception as e:  # noqa: BLE001 — a failed repair must not lose the population
            print(f"[agent_factory] duplicate repair failed: {type(e).__name__}: {e}")
            agent_dicts = uniquify_names(agent_dicts + dupes)

    if not agent_dicts:
        raise RuntimeError(
            "Agent generation produced no valid personas — the model output could not be parsed "
            "(check the ANTHROPIC_API_KEY and try again)."
        )

    # ── Build AgentProfile objects ─────────────────────────────────────────────
    profiles: list[AgentProfile] = []
    used_colors: list[str] = []
    for d in agent_dicts:
        if not isinstance(d, dict) or not d.get("name"):
            continue
        color = random.choice([c for c in AVATAR_COLORS if c not in used_colors] or AVATAR_COLORS)
        used_colors.append(color)
        stance = d.get("stance", "neutral")
        if stance not in ("direct", "indirect", "neutral"):
            stance = "neutral"
        try:
            profiles.append(
                AgentProfile(
                    id=str(uuid.uuid4()),
                    session_id=session_id,
                    name=str(d.get("name", "Unnamed")),
                    age=int(d.get("age", 35) or 35),
                    role=str(d.get("role", "Participant")),
                    background=str(d.get("background", "")),
                    stance=stance,
                    correlation=str(d.get("correlation", "")),
                    personality=d.get("personality", []) or [],
                    debate_style=str(d.get("debate_style", "thoughtful")),
                    energy=round(random.uniform(0.3, 1.0), 2),
                    avatar_color=color,
                    dials=d.get("dials", {}) or {},
                    humanity=int(d.get("humanity", 0) or 0),
                )
            )
        except Exception as e:
            print(f"[agent_factory] skipping malformed agent: {type(e).__name__}: {e}")
            continue

    return profiles


def _parse_agents_json(raw: str) -> list[dict]:
    """Parse the model's JSON array of agents, tolerating truncated/partial output
    by salvaging the complete top-level objects that were emitted."""
    if not raw:
        return []
    raw = raw.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("`").strip()

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict):
            return [data]
        return []
    except Exception:
        # Truncated or malformed — salvage every complete {...} object
        return _salvage_objects(raw)


def _salvage_objects(raw: str) -> list[dict]:
    """Walk the string and json.loads each balanced top-level {...} block, skipping
    a truncated final object. Quote/escape aware so braces inside strings are ignored."""
    objs: list[dict] = []
    depth = 0
    start = None
    in_str = False
    esc = False
    for idx, ch in enumerate(raw):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        obj = json.loads(raw[start:idx + 1])
                        if isinstance(obj, dict):
                            objs.append(obj)
                    except Exception:
                        pass
                    start = None
    return objs


# ── Population Studio: build the roster from an approved segment plan ─────────────────────────

_DEMOGRAPHIC_KEYS = ("gender", "region", "income_band", "education", "occupation")


def _segment_block(seg: dict, n: int, humanized: int) -> str:
    """The segment spec as the persona prompt sees it. Everything the plan fixed is stated as
    a hard constraint so ten personas from one segment are ten different people from the SAME
    slice of the population, not ten variations on the topic's obvious archetype."""
    d = seg.get("demographics") or {}
    sent = seg.get("sentiment") or {}
    regions = ", ".join(d.get("regions") or []) or "unspecified"
    occupations = ", ".join(d.get("occupations") or []) or "whatever fits the segment"
    female = d.get("gender_female_pct")
    female_line = f"roughly {female}% women, the rest men (a non-binary person is fine where plausible)" if isinstance(female, int) else "a plausible mix"
    emotions = ", ".join(sent.get("top_emotions") or []) or "as fits each person"
    args = "\n".join(f"  - {a}" for a in (seg.get("arguments") or [])[:5]) or "  - (none given; infer from the segment)"
    evidence = "\n".join(f"  - {e}" for e in (seg.get("evidence") or [])[:4])
    return f"""THE SEGMENT (every persona in this batch belongs to it):
Name: {seg.get('name')}
Who they are: {seg.get('description')}
Stance: {seg.get('stance')} (every persona in this batch has this stance)
Ages: {d.get('age_min', 18)} to {d.get('age_max', 75)} — spread the {n} personas across this range, not clustered
Gender: {female_line}
Where they live: {regions}
Income band: {d.get('income_band', 'mixed')} · Education: {d.get('education', 'mixed')}
Typical occupations: {occupations}
Mood on the topic: {sent.get('mood', 'mixed')}, emotional temperature {sent.get('temperature', 5)}/10, dominant emotions: {emotions}
Arguments this group actually makes (use their phrasing, vary it per person):
{args}
{('Evidence behind this segment:' + chr(10) + evidence) if evidence else ''}
Why this segment exists: {seg.get('rationale', '')}
Humanity: exactly {humanized} of the {n} personas are high-humanity everyday people (set "humanity" to the value given below); the rest are analytical (humanity 0).
"""


def _constraints_block(constraints: dict) -> str:
    """Population-wide dials as prompt text. Only the dials that were moved off 'mixed' are
    stated, so the model is not told to honour a constraint the user never set."""
    if not constraints:
        return ""
    lines: list[str] = []
    demo = constraints.get("demographics") or {}
    if demo.get("age_min") is not None or demo.get("age_max") is not None:
        lines.append(f"- Ages must fall between {demo.get('age_min', 18)} and {demo.get('age_max', 80)}.")
    if demo.get("age_skew") and demo.get("age_skew") != "even":
        lines.append(f"- The population skews {demo['age_skew']} within that range.")
    if demo.get("regions"):
        lines.append(f"- Everyone lives in: {', '.join(demo['regions'])}. Use real towns, cities and areas inside these places.")
    if demo.get("urban_rural") and demo.get("urban_rural") != "mixed":
        lines.append(f"- Settlement type: mostly {demo['urban_rural']}.")
    if demo.get("income") and demo.get("income") != "mixed":
        lines.append(f"- Household income: mostly {demo['income']}.")
    if demo.get("education") and demo.get("education") != "mixed":
        lines.append(f"- Education: mostly {demo['education']}.")
    if demo.get("notes"):
        lines.append(f"- Also: {demo['notes']}")
    sent = constraints.get("sentiment") or {}
    if not sent.get("follow_evidence", True) and isinstance(sent.get("mood"), dict):
        m = sent["mood"]
        lines.append(f"- Population mood target: {m.get('for', 0)}% for, {m.get('against', 0)}% against, {m.get('mixed', 0)}% mixed or undecided.")
    for key, label in (("temperature", "emotional temperature (0 calm, 10 heated)"), ("trust_in_institutions", "trust in institutions and official bodies"),
                       ("price_sensitivity", "price sensitivity"), ("tech_savviness", "comfort with technology"), ("openness_to_change", "openness to change")):
        v = sent.get(key)
        if isinstance(v, (int, float)) and int(v) != 5:
            lines.append(f"- Population-wide {label}: {int(v)}/10 — shift the matching dials accordingly.")
    if constraints.get("profile_query"):
        lines.append(f"- Audience profile from the analyst: {constraints['profile_query']}")
    if not lines:
        return ""
    return "POPULATION-WIDE DIALS (set by the analyst; honour them):\n" + "\n".join(lines) + "\n"


def _plan_prompt(query: str, seg: dict, n: int, humanized: int, humanity: int, constraints: dict, kg_summary: str, evidence_text: str, taken: list[dict]) -> str:
    doc = (constraints or {}).get("doc_context") or ""
    doc_block = f"\nSURVEY / PROFILE DATA (translate to dial values where a respondent fits this segment):\n{doc[:SURVEY_CHAR_LIMIT]}\n" if doc else ""
    return f"""Create {n} distinct personas for a synthetic population that will debate and be surveyed on this topic:

QUERY: {query}

{_segment_block(seg, n, humanized)}
{_constraints_block(constraints)}
KNOWLEDGE CONTEXT:
{kg_summary[:2000]}
{('EVIDENCE:' + chr(10) + evidence_text[:3500]) if evidence_text else ''}
{doc_block}
Rules:
- All {n} are members of THIS segment: same stance, inside the age range, matching the gender split, living in the places named, with occupations and circumstances that fit. Within that, make them {n} clearly DIFFERENT people — different names, jobs, life situations, reasons for their view, and ways of talking.
- Give each a specific, textured background (a real-sounding life, a concrete stake) and a believable reason to hold the view they hold. Some are sharp, some are muddled; some calm, some heated — match the segment's temperature on average.
- High-humanity personas (humanity = {humanity}) react from feeling, keep trust.credibility and trust.authority LOW, and run 2-3 sentiment dials hot (7-10). Analytical personas (humanity = 0) are measured and evidence-led.
- SENTIMENT IS PRIMARY: give every persona a distinct emotional signature with a couple of dominant emotions running hot and others clearly low. Use the full 0-10 range across the batch; do not cluster on 5.
{_taken_block_text(taken)}
Return a JSON array with exactly {n} objects. Each object MUST have ALL of these keys:
{{
  "name": "Full Name",
  "age": <integer inside the segment's range>,
  "gender": "female" | "male" | "non-binary",
  "region": "town or area, country — inside the segment's places",
  "income_band": "low" | "lower-middle" | "middle" | "upper-middle" | "high",
  "education": "secondary" | "some college" | "degree" | "postgraduate",
  "occupation": "their job or situation (e.g. 'retired', 'student', 'carer')",
  "role": "Job Title / Role as it would appear on a panel card",
  "background": "2-3 sentence life and professional background",
  "stance": "{seg.get('stance', 'neutral')}",
  "correlation": "1 sentence: how they relate to the topic",
  "personality": ["trait1", "trait2", "trait3"],
  "debate_style": "1 sentence describing how they argue",
  "humanity": <integer 0-100>,
  "dials": {DIALS_SCHEMA}
}}

{_DIALS_INSTRUCTIONS}

Return ONLY the JSON array, no markdown, no explanation."""


def _taken_block_text(taken: list[dict]) -> str:
    if not taken:
        return ""
    listed = "\n".join(f"- {t.get('name')} — {t.get('role')} (age {t.get('age')})" for t in taken[-40:])
    return f"""
ALREADY IN THIS POPULATION — every persona you return must be a DIFFERENT person (different name, job and angle) from everyone below:
{listed}
"""


def profile_from_dict(d: dict, session_id: str, color: str, segment: str = "") -> Optional[AgentProfile]:
    """One model-written persona dict → AgentProfile, or None when it is unusable."""
    if not isinstance(d, dict) or not d.get("name"):
        return None
    stance = d.get("stance", "neutral")
    if stance not in ("direct", "indirect", "neutral"):
        stance = "neutral"
    demographics = {k: str(d.get(k) or "").strip() for k in _DEMOGRAPHIC_KEYS if d.get(k)}
    try:
        return AgentProfile(
            id=str(uuid.uuid4()),
            session_id=session_id,
            name=str(d.get("name", "Unnamed")),
            age=int(d.get("age", 35) or 35),
            role=str(d.get("role") or d.get("occupation") or "Participant"),
            background=str(d.get("background", "")),
            stance=stance,
            correlation=str(d.get("correlation", "")),
            personality=d.get("personality", []) or [],
            debate_style=str(d.get("debate_style", "thoughtful")),
            energy=round(random.uniform(0.3, 1.0), 2),
            avatar_color=color,
            dials=d.get("dials", {}) or {},
            humanity=int(d.get("humanity", 0) or 0),
            segment=segment,
            demographics=demographics,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[agent_factory] skipping malformed agent: {type(e).__name__}: {e}")
        return None


async def generate_agents_from_plan(
    session_id: str,
    query: str,
    segments: list[dict],
    constraints: dict,
    *,
    mode: str = "fast",
    evidence_text: str = "",
    on_progress=None,
    should_stop=None,
) -> list[AgentProfile]:
    """Build the roster segment by segment from an approved Population Studio plan.

    Each segment's `count` is generated in batches of ≤10 on the mode's orchestration model
    (Fast = Haiku, Pro = Sonnet), every batch told who is already in the roster. `on_progress`
    (async, optional) is called as `(segment_name, done_in_segment, segment_count, done_total)`
    after every batch so the Studio log can narrate the build."""
    settings = get_settings()
    gen_model = settings.orchestration_model(mode)
    rag = await get_lightrag(session_id)
    kg_summary = await query_rag(rag, query, mode="hybrid")
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    sem = asyncio.Semaphore(max(1, settings.spawn_concurrency))

    humanity = max(0, min(100, int((constraints or {}).get("humanity") or 0)))
    coverage = max(0, min(100, int((constraints or {}).get("humanity_coverage") or 0)))

    all_dicts: list[dict] = []
    done_total = 0
    used_colors: list[str] = []
    profiles: list[AgentProfile] = []

    async def _batch(seg: dict, n: int, h: int, taken: list[dict], label: str) -> list[dict]:
        if should_stop and should_stop():
            return []  # the analyst stopped the build: batches not yet started are skipped, finished ones are kept
        async with sem:
            try:
                response = await tracked_messages_create(
                    client, session_id=session_id, label=label, model=gen_model, max_tokens=12000,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": _plan_prompt(query, seg, n, h, humanity, constraints, kg_summary, evidence_text, taken)}],
                )
                return _parse_agents_json(response.content[0].text)
            except Exception as e:  # noqa: BLE001
                print(f"[agent_factory] plan batch failed ({seg.get('name')}, {n}): {type(e).__name__}: {e}")
                return []

    progress_lock = asyncio.Lock()

    async def _segment(seg: dict) -> list[dict]:
        nonlocal done_total
        count = int(seg.get("count") or 0)
        if count <= 0:
            return []
        # How many of this segment are high-humanity: the population-wide coverage, nudged by
        # the segment's own register hint so an "expert" segment stays mostly analytical.
        hint = (seg.get("humanity_hint") or "").lower()
        seg_cov = coverage if humanity > 0 else 0
        if hint == "expert":
            seg_cov = min(seg_cov, 20)
        elif hint in ("defensive", "reactive"):
            seg_cov = max(seg_cov, 70) if humanity > 0 else 0
        humanized_total = round(count * seg_cov / 100)
        sizes = [_BATCH_SIZE] * (count // _BATCH_SIZE) + ([count % _BATCH_SIZE] if count % _BATCH_SIZE else [])
        # Spread the humanized slots across the batches.
        hum_per_batch: list[int] = []
        left = humanized_total
        for i, n in enumerate(sizes):
            share = round(humanized_total * n / count) if i < len(sizes) - 1 else left
            share = max(0, min(n, share, left))
            hum_per_batch.append(share)
            left -= share
        seg_dicts: list[dict] = []

        async def _note():
            nonlocal done_total
            async with progress_lock:
                if on_progress:
                    await on_progress(seg.get("name", ""), len(seg_dicts), count, done_total)

        # Within a segment: the first batch alone so the rest can build around it, then the
        # rest concurrently. Segments themselves run side by side (bounded by the semaphore) —
        # they are different slices of the population, so they rarely collide, and the
        # duplicate repair below catches the few that do.
        first = await _batch(seg, sizes[0], hum_per_batch[0], seg_dicts, "spawn:plan")
        seg_dicts.extend(first)
        done_total += len(first)
        await _note()
        if len(sizes) > 1:
            async def _rest(n: int, h: int):
                nonlocal done_total
                r = await _batch(seg, n, h, list(seg_dicts), "spawn:plan")
                seg_dicts.extend(r)
                done_total += len(r)
                await _note()
            await asyncio.gather(*[_rest(n, h) for n, h in zip(sizes[1:], hum_per_batch[1:])])
        for d in seg_dicts:
            d["stance"] = seg.get("stance", d.get("stance"))
            d["_segment"] = seg.get("name", "")
        return seg_dicts

    for part in await asyncio.gather(*[_segment(seg) for seg in segments]):
        all_dicts.extend(part)

    all_dicts, dupes = split_duplicates(all_dicts)
    if dupes:
        print(f"[agent_factory] {len(dupes)} duplicate persona(s) across plan batches — regenerating")
        by_seg: dict[str, list[dict]] = {}
        for d in dupes:
            by_seg.setdefault(d.get("_segment", ""), []).append(d)
        seg_by_name = {s.get("name", ""): s for s in segments}
        for name, ds in by_seg.items():
            seg = seg_by_name.get(name)
            if not seg:
                continue
            h = sum(1 for d in ds if int(d.get("humanity") or 0) > 0)
            try:
                repl = await _batch(seg, len(ds), h, all_dicts, "spawn:plan:repair")
                for d in repl:
                    d["stance"] = seg.get("stance", d.get("stance"))
                    d["_segment"] = name
                all_dicts, _ = split_duplicates(all_dicts + repl)
            except Exception as e:  # noqa: BLE001
                print(f"[agent_factory] plan duplicate repair failed: {type(e).__name__}: {e}")
                all_dicts = uniquify_names(all_dicts + ds)

    if not all_dicts and should_stop and should_stop():
        return []
    if not all_dicts:
        raise RuntimeError("Persona generation produced no valid personas — the model output could not be parsed (check the ANTHROPIC_API_KEY and try again).")

    for d in all_dicts:
        color = random.choice([c for c in AVATAR_COLORS if c not in used_colors] or AVATAR_COLORS)
        used_colors.append(color)
        p = profile_from_dict(d, session_id, color, segment=d.get("_segment", ""))
        if p:
            profiles.append(p)
    return profiles
