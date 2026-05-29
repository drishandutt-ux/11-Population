import json
import uuid
import random
from app.core.config import get_settings
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


async def generate_agents(
    session_id: str,
    query: str,
    count: int,
    profile_query: str = "",
    direct_pct: int = 33,
    indirect_pct: int = 33,
    neutral_pct: int = 34,
    doc_context: str = "",
) -> list[AgentProfile]:
    settings = get_settings()
    rag = await get_lightrag(session_id)
    kg_summary = await query_rag(rag, query, mode="hybrid")

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Calculate counts from percentages
    direct_count = max(1, round(count * direct_pct / 100))
    indirect_count = max(1, round(count * indirect_pct / 100))
    neutral_count = max(0, count - direct_count - indirect_count)
    # Adjust for rounding
    total = direct_count + indirect_count + neutral_count
    if total < count:
        neutral_count += count - total
    elif total > count:
        neutral_count = max(0, neutral_count - (total - count))

    profile_context = ""
    if profile_query:
        profile_context = f"\nAUDIENCE PROFILE INSTRUCTIONS:\n{profile_query}\n"
        profile_context += "Use this to shape agent demographics, backgrounds, and psychological dials.\n"
    if doc_context:
        profile_context += f"\nSURVEY / PROFILE DATA (translate to dial values):\n{doc_context[:8000]}\n"

    system = """You are an expert behavioral psychologist and simulation designer. You create deeply realistic
human personas for multi-agent debate simulations. Each agent gets a full psychological dial profile (112 values, all integers 0-10)
that reflects their emotional state, motivations, habits, trust patterns, friction points, identity fit,
commercial intent, product experience, and composite readiness scores — all relative to the topic being debated."""

    prompt = f"""Create {count} diverse agent personas to debate and analyze this topic:

QUERY: {query}

KNOWLEDGE CONTEXT:
{kg_summary[:2500]}
{profile_context}
Generate exactly:
- {direct_count} DIRECT agents: domain experts, practitioners directly in this field
- {indirect_count} INDIRECT agents: adjacent-field experts who bring cross-domain perspective
- {neutral_count} NEUTRAL agents: skeptics, journalists, general public, contrarians

Return a JSON array with exactly {count} objects. Each object MUST have ALL of these keys:
{{
  "name": "Full Name",
  "age": <integer 25-65>,
  "role": "Job Title / Role",
  "background": "2-3 sentence professional background",
  "stance": "direct" | "indirect" | "neutral",
  "correlation": "1 sentence: how they relate to the topic",
  "personality": ["trait1", "trait2", "trait3"],
  "debate_style": "1 sentence describing how they argue",
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

Return ONLY the JSON array, no markdown, no explanation."""

    response = await client.messages.create(
        model=settings.model_orchestration,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()

    agent_dicts = json.loads(raw)
    profiles = []
    used_colors = []
    for d in agent_dicts:
        color = random.choice([c for c in AVATAR_COLORS if c not in used_colors] or AVATAR_COLORS)
        used_colors.append(color)
        profiles.append(
            AgentProfile(
                id=str(uuid.uuid4()),
                session_id=session_id,
                name=d["name"],
                age=int(d.get("age", 35)),
                role=d["role"],
                background=d["background"],
                stance=d["stance"],
                correlation=d["correlation"],
                personality=d.get("personality", []),
                debate_style=d.get("debate_style", "thoughtful"),
                energy=round(random.uniform(0.3, 1.0), 2),
                avatar_color=color,
                dials=d.get("dials", {}),
            )
        )
    return profiles
