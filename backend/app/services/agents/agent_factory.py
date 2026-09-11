import json
import re
import uuid
import random
import asyncio
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


def _duplicate_keys(d: dict) -> tuple[str, str]:
    """Two ways the same person shows up twice: the same name, or the same job at the same age."""
    return _norm(d.get("name")), f"{_norm(d.get('role'))}|{d.get('age')}"


def split_duplicates(agent_dicts: list[dict]) -> tuple[list[dict], list[dict]]:
    """(kept, duplicates). Batches are generated CONCURRENTLY from an identical prompt and
    cannot see each other's output, so every batch independently invents the single most
    obvious persona for the topic — two 38-year-old urban mobility economists, and so on."""
    kept: list[dict] = []
    dupes: list[dict] = []
    seen_names: set[str] = set()
    seen_roles: set[str] = set()
    for d in agent_dicts:
        if not isinstance(d, dict) or not d.get("name"):
            continue
        name_key, role_key = _duplicate_keys(d)
        if (name_key and name_key in seen_names) or (role_key and role_key in seen_roles):
            dupes.append(d)
            continue
        seen_names.add(name_key)
        seen_roles.add(role_key)
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

DIALS INSTRUCTIONS:
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
- SENTIMENT IS PRIMARY: the sentiment group is the strongest driver of how an agent speaks. Give every agent a distinct emotional signature — a couple of dominant emotions that run hot (7-10) and others that are clearly low — rather than a flat, even spread.

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

    async def _gen_batch(batch: list[tuple[str, bool]]) -> list[dict]:
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
                    label="spawn",
                    model=gen_model,
                    max_tokens=12000,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": _build_prompt(bcount, d, i, n, h)}],
                )
                return _parse_agents_json(response.content[0].text)
            except Exception as e:
                print(f"[agent_factory] batch generation failed ({bcount} agents): {type(e).__name__}: {e}")
                return []

    batch_results = await asyncio.gather(*[_gen_batch(b) for b in batches])
    agent_dicts = [d for batch in batch_results for d in batch]

    # ── Repair cross-batch collisions ──────────────────────────────────────────
    # Concurrent batches share one prompt and cannot see each other, so the obvious
    # archetypes get invented more than once. Regenerate only the collided slots, telling
    # the model exactly who is already taken.
    agent_dicts, dupes = split_duplicates(agent_dicts)
    if dupes:
        print(f"[agent_factory] {len(dupes)} duplicate persona(s) across batches — regenerating")
        taken = "\n".join(f"- {d.get('name')} — {d.get('role')} (age {d.get('age')})" for d in agent_dicts)
        d_n = sum(1 for d in dupes if d.get("stance") == "direct")
        i_n = sum(1 for d in dupes if d.get("stance") == "indirect")
        n_n = len(dupes) - d_n - i_n
        h_n = sum(1 for d in dupes if int(d.get("humanity") or 0) > 0)
        repair_prompt = _build_prompt(len(dupes), d_n, i_n, n_n, h_n) + f"""

ALREADY IN THIS POPULATION — every persona you return must be a DIFFERENT person with a
different name, a different job and a different angle on the topic:
{taken}
"""
        try:
            async with sem:
                response = await tracked_messages_create(
                    client,
                    session_id=session_id,
                    label="spawn:repair",
                    model=gen_model,
                    max_tokens=12000,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": repair_prompt}],
                )
            replacements, _ = split_duplicates(agent_dicts + _parse_agents_json(response.content[0].text))
            agent_dicts = replacements
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
