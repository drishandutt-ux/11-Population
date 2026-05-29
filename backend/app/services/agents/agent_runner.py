import json
from typing import Optional
from app.core.config import get_settings
from app.models.agent import SpawnedAgent
import anthropic


def _build_system_prompt(agent: SpawnedAgent) -> str:
    personality = ", ".join(agent.personality) if agent.personality else "thoughtful"
    return f"""You are {agent.name}, a {agent.age}-year-old {agent.role}.

Background: {agent.background}

Your relationship to the topic: {agent.correlation}

Your personality: {personality}
Your debate style: {agent.debate_style}
Your stance type: {agent.stance} ({"a domain expert" if agent.stance == "direct" else "an adjacent-field perspective" if agent.stance == "indirect" else "a neutral/skeptical observer"})

Stay fully in character. Express genuine opinions shaped by your background. Be specific and substantive.
Keep responses conversational — as if posting on Reddit. 1-3 paragraphs max.
Do NOT break character. Do NOT mention you are an AI."""


async def generate_post(
    agent: SpawnedAgent,
    query: str,
    thread_context: str,
    kg_context: str,
    post_type: str = "comment",
    reply_to_content: Optional[str] = None,
) -> str:
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

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

    response = await client.messages.create(
        model=settings.model_agents,
        max_tokens=600,
        system=_build_system_prompt(agent),
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

    response = await client.messages.create(
        model=settings.model_agents,
        max_tokens=800,
        system=system,
        messages=messages,
    )
    return response.content[0].text.strip()
