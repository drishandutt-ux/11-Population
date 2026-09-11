"""Instrument registry.

An instrument is a self-contained tool: it declares its own **inputs**, its own answer
**schema**, its own **aggregator** and its own **KPIs**. The probe runner, the statistics
library and the Lab shell know nothing about any particular instrument — exactly as the
debate knows nothing about the Lab. Tools differ; the spine stays generic.

Adding an instrument is one file here plus (optionally) one page component in the frontend.
Nothing else changes: `GET /lab/instruments` publishes the declaration, and the UI builds its
form and its results view from that.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class InputField:
    """One control on an instrument's own input panel.

    There is no shared "stimulus + price" form: an instrument that needs a stimulus declares
    one, and an instrument that needs attribute levels or a category list declares those
    instead."""

    key: str
    #: text · textarea · number · select · money — the UI maps these to controls.
    type: str
    label: str
    required: bool = False
    help: str = ""
    placeholder: str = ""
    default: Any = None
    #: Prefill from session state so the analyst edits rather than retypes. Currently
    #: "session_query"; anything unrecognised is ignored by the client.
    default_from: str = ""
    options: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "key": self.key, "type": self.type, "label": self.label, "required": self.required,
            "help": self.help, "placeholder": self.placeholder, "default": self.default,
            "default_from": self.default_from, "options": list(self.options),
        }


@dataclass(frozen=True)
class Kpi:
    """A headline number this instrument produces, named so the shell, the CSV and the report
    generator can all render it without knowing what the instrument measures."""

    key: str
    label: str
    #: share · mean · money · count — how to format the value.
    format: str = "share"
    help: str = ""

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "format": self.format, "help": self.help}


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
    #: This instrument's own input panel.
    inputs: tuple[InputField, ...] = ()
    #: The headline numbers it reports.
    kpis: tuple[Kpi, ...] = ()
    #: Identifies the instrument's own results page in the frontend registry; falls back to a
    #: generic renderer when no page is registered, so a new backend instrument is usable
    #: before its page is written.
    page: str = ""
    #: Answers are short; this caps the tool-use call.
    max_tokens: int = 500
    #: Bumped when the schema changes, so old answers are never silently mixed with new ones.
    version: int = 1

    def schema_id(self) -> str:
        return f"{self.key}.v{self.version}"

    def required_inputs(self) -> list[str]:
        return [i.key for i in self.inputs if i.required]


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
