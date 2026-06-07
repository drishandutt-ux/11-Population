"""Shared helper to turn raw Anthropic/LLM exceptions into friendly, user-facing
messages, so chat/report surfaces show something readable instead of a 500."""


def friendly_llm_error(e: Exception) -> str:
    name = type(e).__name__
    msg = str(e)
    low = msg.lower()

    if name == "AuthenticationError" or "401" in msg or "invalid x-api-key" in low or "authentication" in low:
        return (
            "⚠️ The AI model is unavailable — the server's ANTHROPIC_API_KEY is missing or invalid. "
            "Set a valid key in the backend environment and try again."
        )
    if name == "RateLimitError" or "429" in msg or "rate limit" in low:
        return "⚠️ The AI model is rate-limited right now. Please wait a moment and try again."
    if name in ("InternalServerError", "OverloadedError") or "overloaded" in low or "529" in msg:
        return "⚠️ The AI model is temporarily overloaded. Please try again in a few seconds."
    if name in ("APITimeoutError", "APIConnectionError") or "timeout" in low or "connection" in low:
        return "⚠️ Couldn't reach the AI model (network/timeout). Please try again."
    return f"⚠️ Couldn't generate a response right now ({name}). Please try again."
