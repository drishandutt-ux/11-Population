"""Anthropic list prices, used to put a dollar figure on every recorded LLM call.

USD per million tokens, first-party API rates (cached 2026-10-06). Cache writes are the 5-minute
rate (1.25x input); cache reads are per model. Web search is billed per request on top of
tokens. Unknown models fall back to Sonnet-tier pricing and are flagged `priced: false`, so a
new model id shows up as an estimate instead of silently costing $0.
"""
from __future__ import annotations

import re

#: model family → (input, output, cache_write_5m, cache_read)  — USD per 1M tokens
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5-1":  (10.00, 50.00, 12.50, 0.25),
    "claude-fable-5":    (10.00, 50.00, 12.50, 1.00),
    "claude-mythos-5-1": (10.00, 50.00, 12.50, 0.25),
    "claude-opus-5-5":   (4.00, 20.00, 5.00, 0.20),
    "claude-opus-5":     (5.00, 25.00, 6.25, 0.50),
    "claude-opus-4-8":   (5.00, 25.00, 6.25, 0.50),
    "claude-opus-4-7":   (5.00, 25.00, 6.25, 0.50),
    "claude-opus-4-6":   (5.00, 25.00, 6.25, 0.50),
    "claude-opus-4-5":   (5.00, 25.00, 6.25, 0.50),
    "claude-opus-4-1":   (15.00, 75.00, 18.75, 1.50),
    "claude-opus-4":     (15.00, 75.00, 18.75, 1.50),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    "claude-sonnet-5":   (2.00, 10.00, 2.50, 0.20),
    "claude-sonnet-4-6": (3.00, 15.00, 3.75, 0.30),
    "claude-sonnet-4-5": (3.00, 15.00, 3.75, 0.30),
    "claude-sonnet-4":   (3.00, 15.00, 3.75, 0.30),
    "claude-haiku-5-5":  (0.10, 0.50, 0.125, 0.01),
    "claude-haiku-4-5":  (1.00, 5.00, 1.25, 0.10),
    "claude-3-5-haiku":  (0.80, 4.00, 1.00, 0.08),
}
FALLBACK = PRICES["claude-sonnet-4-6"]
WEB_SEARCH_PER_REQUEST = 10.00 / 1000

_DATE_SUFFIX = re.compile(r"-\d{8}$")


def family(model: str | None) -> str | None:
    """`claude-haiku-4-5-20251001` → `claude-haiku-4-5`; longest known prefix wins."""
    m = _DATE_SUFFIX.sub("", (model or "").strip().lower())
    if m.startswith("anthropic."):
        m = m[len("anthropic."):]
    best = None
    for key in PRICES:
        if (m == key or m.startswith(key + "-")) and (best is None or len(key) > len(best)):
            best = key
    return best


def cost_usd(model: str | None, *, input_tokens: int = 0, output_tokens: int = 0,
             cache_creation_tokens: int = 0, cache_read_tokens: int = 0,
             web_search_requests: int = 0) -> tuple[float, bool]:
    """(cost in USD, whether the model was in the price table)."""
    fam = family(model)
    p_in, p_out, p_cw, p_cr = PRICES.get(fam, FALLBACK) if fam else FALLBACK
    usd = (
        input_tokens * p_in + output_tokens * p_out
        + cache_creation_tokens * p_cw + cache_read_tokens * p_cr
    ) / 1_000_000 + web_search_requests * WEB_SEARCH_PER_REQUEST
    return round(usd, 6), fam is not None
