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
    #: For free-text inputs: ready-made phrasings the UI offers as one-click chips.
    suggestions: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "key": self.key, "type": self.type, "label": self.label, "required": self.required,
            "help": self.help, "placeholder": self.placeholder, "default": self.default,
            "default_from": self.default_from, "options": list(self.options),
            "suggestions": list(self.suggestions),
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
class Metric:
    """One number an A/B test can compare between variants, read from a single answer.

    An instrument that declares metrics can be run as an experiment: the experiments layer
    asks each agent the same instrument once per variant and reports the paired difference
    on every metric declared here. `value` maps one answer to a float (or None to exclude
    the agent from that metric) — a share metric returns 1.0/0.0."""

    key: str
    label: str
    #: share · mean · money — how to format the level and the lift.
    format: str
    value: Callable[[dict], Optional[float]]
    #: The metric the verdict is written about. Exactly one per instrument.
    primary: bool = False
    help: str = ""

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "format": self.format, "primary": self.primary, "help": self.help}


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
    #: What an A/B test compares. Empty means the tool cannot be run as an experiment.
    metrics: tuple[Metric, ...] = ()
    #: The categorical answer field whose change between variants counts as a "flip"
    #: (e.g. would_buy). Empty means the experiments layer reports lift without flips.
    decision_key: str = ""
    #: The categorical answer field that explains a decision (e.g. key_driver), used to code
    #: the reasons of the agents who flipped.
    driver_key: str = ""
    #: Answers are short; this caps the tool-use call.
    max_tokens: int = 500
    #: Bumped when the schema changes, so old answers are never silently mixed with new ones.
    version: int = 1
    #: Which spec key holds what the agent is shown. Purchase intent calls it the offer
    #: (`stimulus`); a generic ask calls it the material.
    stimulus_key: str = "stimulus"
    #: If set, the ask itself comes from the spec under this key (the analyst writes the
    #: question) instead of the fixed `question` above.
    question_from: str = ""
    #: Runs once after every answer is in and before aggregation: (probe_ids, model) -> None.
    #: Used for population-level coding (free-text reasons into shared themes). It may rewrite
    #: stored answers, so it runs before `aggregate`. An experiment runs it ONCE across all
    #: arms so the themes are shared, and skips the per-arm call.
    postprocess: Optional[Callable[..., Any]] = None
    #: Internal instruments (the choice design's) are not offered in the picker.
    hidden: bool = False

    def schema_id(self) -> str:
        return f"{self.key}.v{self.version}"

    def schema_for(self, spec: dict) -> dict:
        """The answer schema for this run. Static for most tools; the choice instrument fills
        its enum from the variants in the spec."""
        return self.answer_schema

    def question_for(self, spec: dict) -> str:
        if self.question_from:
            q = str(spec.get(self.question_from) or "").strip()
            if q:
                return q
        return self.question

    def required_inputs(self) -> list[str]:
        return [i.key for i in self.inputs if i.required]

    def supports_experiments(self) -> bool:
        return bool(self.metrics)

    def primary_metric(self) -> Optional["Metric"]:
        for m in self.metrics:
            if m.primary:
                return m
        return self.metrics[0] if self.metrics else None


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
    from app.services.measurement.instruments import ask, choice, purchase_intent  # noqa: F401
    # Only after a clean import: a module that raises must keep raising, not leave the
    # registry half-built and every later lookup silently returning None.
    _loaded = True
