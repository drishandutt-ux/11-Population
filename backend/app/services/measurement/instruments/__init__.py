"""Instrument registry.

An instrument is a probe template: an answer schema, a question, a behavioural directive
that keeps the persona honest while answering it, and a pure-Python aggregator. The probe
runner knows nothing about any particular instrument — adding a new one is one file plus
one line in `_REGISTER`, and it shows up in the API and the UI automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Instrument:
    key: str
    label: str
    description: str
    #: JSON Schema for the tool-use call. Put a short `reasoning` field FIRST: a model that
    #: states a reason before a number spreads out instead of clustering on the midpoint.
    answer_schema: dict
    #: The ask, shown to the agent after the stimulus.
    question: str
    #: Instrument-specific rules appended to the agent's system prompt.
    directive: str
    #: (rows, spec) -> aggregates. `rows` are dicts of {agent_id, agent, answer, segments}.
    aggregate: Callable[[list[dict], dict], dict]
    #: What the client is looking at, so the UI can pick a renderer.
    chart: str = "distribution"
    #: Placeholder shown in the stimulus editor.
    stimulus_hint: str = ""
    #: Answers are short; this caps the tool-use call.
    max_tokens: int = 500
    #: Bumped when the schema changes, so old answers are never silently mixed with new ones.
    version: int = 1
    #: Spec keys this instrument reads, for the API to validate and the UI to render.
    spec_fields: tuple[str, ...] = ()

    def schema_id(self) -> str:
        return f"{self.key}.v{self.version}"


_REGISTRY: dict[str, Instrument] = {}


def register(instrument: Instrument) -> Instrument:
    _REGISTRY[instrument.key] = instrument
    return instrument


def get(key: str) -> Optional[Instrument]:
    _load()
    return _REGISTRY.get(key)


def all_instruments() -> list[Instrument]:
    _load()
    return sorted(_REGISTRY.values(), key=lambda i: i.key)


_loaded = False


def _load() -> None:
    """Import the instrument modules once, on first use (avoids an import cycle with the runner)."""
    global _loaded
    if _loaded:
        return
    from app.services.measurement.instruments import purchase_intent  # noqa: F401
    # Only after a clean import: a module that raises must keep raising, not leave the
    # registry half-built and every later lookup silently returning None.
    _loaded = True
