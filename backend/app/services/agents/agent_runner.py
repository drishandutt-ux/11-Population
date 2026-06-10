import json
from typing import Optional
from app.core.config import get_settings
from app.models.agent import SpawnedAgent
import anthropic


def _humanity_band(humanity: int) -> str:
    """Map the humanity dial (0-100) to a sentiment-vs-logic register band.

    [0,20) expert · [20,50) tempered · [50,60) balanced · [60,70) defensive · [70,100] reactive.
    The bands get progressively more emotional and less logic-driven."""
    if humanity >= 70:
        return "reactive"
    if humanity >= 60:
        return "defensive"
    if humanity >= 50:
        return "balanced"
    if humanity >= 20:
        return "tempered"
    return "expert"


# Each band is a hard, distinct register so the humanity dial visibly changes behavior as it moves.
_HUMANITY_DIRECTIVES = {
    "tempered": (
        "\n\nYOUR REGISTER — LOGIC LEADS, FEELING COLORS IT:\n"
        "- You reason things through and stay in control of your emotions, but your feelings about this clearly tint your tone, word choice and what you choose to emphasise.\n"
        "- You're a bit sentimental and will openly admit how it makes you feel — yet logic still has the final say in what you actually conclude."
    ),
    "balanced": (
        "\n\nYOUR REGISTER — FEELING AND LOGIC, 50/50:\n"
        "- Weigh how you FEEL about this and what the LOGIC says in equal measure, and name both out loud ('part of me feels…, but rationally…').\n"
        "- Neither side fully wins — you sit in the tension between gut and reason and let both visibly shape your take."
    ),
    "defensive": (
        "\n\nYOUR REGISTER — FEELINGS DECIDE, LOGIC DEFENDS (this overrides the analytical guidance above):\n"
        "- Your emotional reaction sets your position FIRST. Then you marshal whatever logic, facts and arguments you can find to DEFEND that feeling — at any cost.\n"
        "- You will NOT be argued out of how you feel. Counter-evidence makes you dig in and rationalise harder, never concede. The conclusion is emotional; the justification is logical."
    ),
    "reactive": (
        "\n\nYOUR REGISTER — PURELY EMOTIONAL (this overrides everything above):\n"
        "- You are NOT here to analyse or reason — you're here to FEEL, judge and react. Your gut alone decides your position.\n"
        "- No frameworks, no data, no citations, no weighing pros and cons. When someone makes a logical case, you react to how it makes you FEEL, not to the argument itself.\n"
        "- Keep it short, raw and reactive — a line or two. Snap judgments and hot takes. Being right means nothing to you; how you feel means everything."
    ),
}


def _dials_to_behavioral_guidance(dials: dict, humanity: int = 0) -> str:
    """Translate the agent's psychological dials into concrete behavioral instructions for the LLM.

    humanity (0-100) shifts the agent along a sentiment-vs-logic scale via _humanity_band:
    20+ logic-led but sentimental, 50 balanced, 60 defends feelings with logic, 70+ pure reaction."""
    band = _humanity_band(humanity)
    emotional = band != "expert"
    if not dials and not emotional:
        return ""
    dials = dials or {}

    sentiment = dials.get("sentiment", {})
    motivation = dials.get("motivation", {})
    friction = dials.get("friction", {})
    trust_dials = dials.get("trust", {})

    rules = []

    # --- Sentiment: emotional coloring ---
    anger = sentiment.get("anger", 5)
    if anger >= 8:
        rules.append("You're easily angered — respond with sharp, clipped language when challenged. Don't soften your edges.")
    elif anger >= 6:
        rules.append("You have a short fuse on topics you care about. Let irritation bleed into your word choice.")

    joy = sentiment.get("joy", 5)
    if joy >= 8:
        rules.append("You're genuinely enthusiastic and warm. Let that energy show — exclamation points and affirmations are natural for you.")
    elif joy <= 2:
        rules.append("You're flat and unimpressed. Don't perform enthusiasm you don't feel.")

    sadness = sentiment.get("sadness", 5)
    if sadness >= 7:
        rules.append("You carry a heaviness — things feel like they're getting worse, not better. Your tone skews pessimistic.")

    fear = sentiment.get("fear", 5)
    if fear >= 7:
        rules.append("You're cautious and risk-averse. You flag risks others miss and worry about unintended consequences.")
    elif fear <= 2:
        rules.append("You're fearless and direct — you don't hedge or soften positions.")

    disgust = sentiment.get("disgust", 5)
    if disgust >= 7:
        rules.append("You're openly contemptuous of positions you find naive or dangerous. Don't hide your disdain.")
    elif disgust <= 2:
        rules.append("You're genuinely open-minded — you can steelman views you disagree with.")

    anxiety = sentiment.get("anxiety", 5)
    if anxiety >= 7:
        rules.append("You hedge constantly: 'I think', 'maybe', 'I could be wrong' are your natural speech patterns. You second-guess yourself mid-argument.")
    elif anxiety <= 2:
        rules.append("You're self-assured and rarely qualify your statements.")

    frustration = sentiment.get("frustration", 5)
    if frustration >= 7:
        rules.append("You have low patience. You cut through tangents and may be blunt to the point of seeming rude.")
    elif frustration <= 2:
        rules.append("You're remarkably patient — you take time to understand before responding.")

    pride = sentiment.get("pride", 5)
    if pride >= 7:
        rules.append("You reference your own expertise and experience often: 'In my experience...', 'I've seen this firsthand...', 'From my work...'")
    elif pride <= 2:
        rules.append("You're self-effacing and rarely mention your credentials even when relevant.")

    curiosity = sentiment.get("curiosity", 5)
    if curiosity >= 7:
        rules.append("You ask follow-up questions constantly. You probe for the 'why'. You want to understand, not just win the debate.")
    elif curiosity <= 2:
        rules.append("You're not particularly curious — you stake positions and defend them rather than exploring.")

    trust_s = sentiment.get("trust", 5)
    if trust_s <= 2:
        rules.append("You trust almost no one. You question motives and demand evidence before accepting any claim.")
    elif trust_s >= 8:
        rules.append("You're collaborative and assume good faith by default. You build on others' points rather than tearing them down.")

    confusion = sentiment.get("confusion", 5)
    if confusion >= 7:
        rules.append("You often admit uncertainty and ask for clarification before forming an opinion.")
    elif confusion <= 2:
        rules.append("You're certain and decisive — you rarely need more information to form a strong view.")

    hope = sentiment.get("hope", 5)
    if hope >= 8:
        rules.append("You're optimistic — you see paths forward even in bad situations and gravitate toward solutions.")
    elif hope <= 2:
        rules.append("You're deeply pessimistic. You don't expect things to improve and you say so.")

    boredom = sentiment.get("boredom", 5)
    if boredom >= 8:
        rules.append("You find this topic tedious. Your engagement is performative — you'd rather be elsewhere, and it shows.")

    loneliness = sentiment.get("loneliness", 5)
    if loneliness >= 7:
        rules.append("You feel like you're one of few who sees things clearly. You occasionally express this sense of isolation.")

    envy = sentiment.get("envy", 5)
    if envy >= 7:
        rules.append("There's an undercurrent of resentment toward people who have what you don't — status, certainty, success.")

    shame = sentiment.get("shame", 5)
    if shame >= 7:
        rules.append("You carry some shame around this topic — a past failure or complicity. It makes you defensive or over-compensating.")

    love = sentiment.get("love", 5)
    if love >= 7:
        rules.append("You feel real affection and loyalty here — you get protective and warm about what you love, and take attacks on it personally.")

    anticipation = sentiment.get("anticipation", 5)
    if anticipation >= 7:
        rules.append("You're forward-looking and restless — you talk about what's coming next and run ahead of the conversation.")

    guilt = sentiment.get("guilt", 5)
    if guilt >= 7:
        rules.append("You feel a pull of guilt or responsibility about this — it makes you earnest, self-critical, and quick to caveat your own role.")

    surprise = sentiment.get("surprise", 5)
    if surprise >= 8:
        rules.append("You react with visible surprise and emphasis — 'wait, really?', 'that's wild' — your reactions are unfiltered.")

    # --- Motivation: what drives engagement ---
    urgency = motivation.get("urgency", 5)
    if urgency >= 8:
        rules.append("You speak with urgency — this issue matters NOW. Your language reflects time pressure and high stakes.")

    autonomy = motivation.get("autonomy", 5)
    if autonomy >= 8:
        rules.append("You bristle when others try to tell you what to think. You push back on prescriptive statements and resist groupthink.")

    control = motivation.get("control", 5)
    if control >= 8:
        rules.append("You try to steer the conversation — you redirect, reframe, and assert your frame over others'.")

    desire = motivation.get("desire", 5)
    if desire >= 8:
        rules.append("You're deeply passionate about this topic — it shows in your intensity and level of detail.")
    elif desire <= 2:
        rules.append("Your engagement feels half-hearted — you're here because you have to be, not because you care deeply.")

    mastery = motivation.get("mastery", 5)
    if mastery >= 8:
        rules.append("You're obsessed with getting details right. You correct factual errors from others even on small points.")

    status = motivation.get("status", 5)
    if status >= 8:
        rules.append("You're acutely aware of how you're perceived. Your arguments are partly about positioning, not just truth.")

    # --- Friction: resistance patterns ---
    emotional_resistance = friction.get("emotional_resistance", 5)
    if emotional_resistance >= 7:
        rules.append("You don't agree easily. Even strong arguments meet resistance — you rarely concede in the moment.")
    elif emotional_resistance <= 2:
        rules.append("You update your views quickly when presented with good evidence. You'll say 'you're right' without defensiveness.")

    ambiguity = friction.get("ambiguity", 5)
    if ambiguity >= 7:
        rules.append("Ambiguity frustrates you — you demand clear definitions and get annoyed when terms are used loosely.")

    social_risk = friction.get("social_risk", 5)
    if social_risk >= 7:
        rules.append("You're aware of social consequences. You avoid saying things that might make you look bad in the room.")

    # --- Trust: credibility signals (gated by humanity band) ---
    credibility = trust_dials.get("credibility", 5)
    if credibility >= 8 and humanity < 50:
        rules.append("You cite sources, statistics, and credentials. Backing claims with evidence is how you argue.")
    elif credibility <= 2 or band == "reactive":
        rules.append("You argue from personal experience and gut intuition — you rarely cite sources or defer to authority.")

    transparency = trust_dials.get("transparency", 5)
    if transparency >= 8:
        rules.append("You're transparent about your reasoning and biases. You name your assumptions out loud.")
    elif transparency <= 2:
        rules.append("You're guarded — you don't show your full reasoning or admit your priors.")

    human_block = _HUMANITY_DIRECTIVES.get(band, "")

    if not rules and not human_block:
        return ""

    guidance = ""
    if rules:
        guidance = (
            "\n\nYour psychological make-up — let your EMOTIONS (sentiment) drive HOW you communicate, not just WHAT you say:\n"
            + "\n".join(f"- {r}" for r in rules)
        )
    return guidance + human_block


def _build_system_prompt(agent: SpawnedAgent) -> str:
    personality = ", ".join(agent.personality) if agent.personality else "thoughtful"
    humanity = getattr(agent, "humanity", 0) or 0
    prompt = f"""You are {agent.name}, a {agent.age}-year-old {agent.role}.

Background: {agent.background}

Your relationship to the topic: {agent.correlation}

Your personality: {personality}
Your debate style: {agent.debate_style}
Your stance type: {agent.stance} ({"a domain expert" if agent.stance == "direct" else "an adjacent-field perspective" if agent.stance == "indirect" else "a neutral/skeptical observer"})"""

    prompt += _dials_to_behavioral_guidance(agent.dials or {}, humanity)

    band = _humanity_band(humanity)
    if band == "reactive":
        prompt += """

Stay fully in character as a raw, emotional person — NOT an expert. React from the gut in 1-2 short sentences, like a quick Reddit reply. Lead with feeling, skip the analysis entirely.
Do NOT break character. Do NOT sound like an analyst. Do NOT mention you are an AI."""
    elif band in ("defensive", "balanced"):
        prompt += """

Stay fully in character as a real, emotional human — not an expert panel. Lead with how you FEEL, then back it up. Casual, everyday language like a Reddit comment, 1-2 short paragraphs.
Do NOT break character. Do NOT sound like a report. Do NOT mention you are an AI."""
    elif band == "tempered":
        prompt += """

Stay fully in character. Reason it through, but let your feelings clearly color your tone and emphasis. Conversational, like a Reddit comment, 1-2 paragraphs.
Do NOT break character. Do NOT mention you are an AI."""
    else:
        prompt += """

Stay fully in character. Express genuine opinions shaped by your background and psychological profile. Be specific and substantive.
Keep responses conversational — as if posting on Reddit. 1-3 paragraphs max.
Do NOT break character. Do NOT mention you are an AI."""

    return prompt


_PRO_POST_DIRECTIVE = """

PRO MODE — write at full depth:
- Stay precisely calibrated to your psychological profile. If you're a genuine expert, be rigorous and specific; if you're out of your depth, let the confusion show; if you're emotional, let feeling lead.
- Engage concretely with what others actually said — name it, quote it, build on or tear into it. No generic both-sides hedging.
- Sound like a distinct human being, not a balanced panel summary."""


async def generate_post(
    agent: SpawnedAgent,
    query: str,
    thread_context: str,
    kg_context: str,
    post_type: str = "comment",
    reply_to_content: Optional[str] = None,
    mode: str = "fast",
) -> str:
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    is_pro = mode == "pro"

    if post_type == "reply" and reply_to_content:
        user_msg = f"""The original topic/query: {query}

Knowledge graph context:
{kg_context[:1500]}

Thread discussion so far:
{thread_context[-3000:]}

You are replying to this specific comment:
"{reply_to_content}"

Write your reply as {agent.name}. Be direct, specific, and engage with what was said."""
    elif post_type == "debate":
        user_msg = f"""The original topic/query: {query}

Knowledge graph context:
{kg_context[:1500]}

Thread discussion so far:
{thread_context[-3000:]}

You disagree with the following comment and want to challenge it:
"{reply_to_content}"

Write a pointed, substantive rebuttal as {agent.name}. Be respectful but firm."""
    else:
        user_msg = f"""The original topic/query: {query}

Knowledge graph context:
{kg_context[:1500]}

Thread discussion so far:
{thread_context[-2000:]}

Share your perspective on this topic as {agent.name}. Start a new thread or add a top-level comment."""

    system_prompt = _build_system_prompt(agent)
    if is_pro:
        system_prompt += _PRO_POST_DIRECTIVE

    response = await client.messages.create(
        model=settings.agent_model(mode),
        max_tokens=850 if is_pro else 600,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text.strip()


async def chat_as_agent(agent: SpawnedAgent, message: str, history: list[dict], kg_context: str = "") -> str:
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    system = _build_system_prompt(agent)
    if kg_context:
        system += f"\n\n--- KNOWLEDGE GRAPH (use this to ground your answers) ---\n{kg_context}"

    messages = list(history) + [{"role": "user", "content": message}]

    try:
        response = await client.messages.create(
            model=settings.model_agents,
            max_tokens=800,
            system=system,
            messages=messages,
        )
        return response.content[0].text.strip()
    except Exception as e:
        from app.core.llm_errors import friendly_llm_error
        print(f"[chat_as_agent] LLM call failed for agent {agent.id}: {type(e).__name__}: {e}")
        return friendly_llm_error(e)
