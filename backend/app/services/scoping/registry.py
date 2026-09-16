"""The dimension registry: every way knowledge can be scoped, described once.

A dimension is a facet key that both a knowledge unit and a twin's exposure profile can carry.
The engine reads the registry to know how to compare the two (`semantics`) and what to do when
a unit says nothing on that dimension (`default`). Adding a new way to scope — language, market,
payer — is one more entry here and one more facet key from the tagger; nothing in the engine
knows about geography specifically.

semantics
  hierarchical  the unit reaches the twin if any unit value is the twin's value or one of its
                ancestors along the ontology's `within` edges (North West reaches Blackpool)
  overlap       the unit and the twin share at least one value
  ordinal       the unit's level is at or below the twin's cap (register)
  temporal      the unit's date is on or before the twin's as_of date
  exact         the values are equal
  hard          exact, and a policy rule may not re-admit a failure (project, licence)

default (when the unit carries no value on the dimension)
  public        visible to everyone
  unknown       visible, but flagged, so a rule can deny "unknown" explicitly
  deny          hidden unless a rule allows it
  none          visible to everyone; only a unit that *has* a value is restricted (arm)
"""
from __future__ import annotations

REGISTER_LEVELS = ["lay", "professional", "technical"]

DIMENSIONS: list[dict] = [
    {"key": "geography", "label": "Geography", "ontology_class": "geography", "semantics": "hierarchical", "default": "public",
     "description": "Every place the unit is about. A twin sees units about its own place and the areas that contain it."},
    {"key": "role", "label": "Role", "ontology_class": "hcp_role", "semantics": "overlap", "default": "public",
     "description": "Who the unit is written for or about: HCP roles from the ontology, plus `patient` and `public`."},
    {"key": "channel", "label": "Channel", "ontology_class": "channel", "semantics": "overlap", "default": "public",
     "description": "How a person would plausibly encounter this: local press, NHS app, rep visit, pharmacy counter … A twin consumes a set of channels."},
    {"key": "condition", "label": "Condition", "ontology_class": "condition", "semantics": "overlap", "default": "public",
     "description": "Conditions the unit is about. A twin with a condition profile sees units about those conditions."},
    {"key": "stage", "label": "Journey stage", "ontology_class": "journey_stage", "semantics": "overlap", "default": "public",
     "description": "Journey stages or barriers the unit is about."},
    {"key": "segment", "label": "Attitude segment", "ontology_class": "attitude_segment", "semantics": "overlap", "default": "public",
     "description": "Cohorts the unit is about or addressed to."},
    {"key": "register", "label": "Register", "semantics": "ordinal", "values": REGISTER_LEVELS, "default": "lay",
     "description": "How specialist the unit is: lay (anyone could read it), professional (clinical or policy), technical (methods, statistics). A twin has a cap."},
    {"key": "time", "label": "Time", "semantics": "temporal", "default": "unknown",
     "description": "The unit's date. A twin with an as_of date cannot see anything later — the back-test and known-answer tests in §06 need this."},
    {"key": "provenance", "label": "Provenance", "semantics": "exact", "default": "public", "values": [
        "official_statistic", "peer_reviewed", "grey_literature", "commissioned_research", "client_data", "social_signal", "model_inference"],
     "description": "The brief's seven provenance classes (L1-05). Twins do not carry a value; rules use it to deny, boost or route."},
    {"key": "project", "label": "Project", "semantics": "hard", "default": "deny",
     "description": "Client / project isolation (L1-07). Units belong to the session's project; a twin in another project can never see them."},
    {"key": "licence", "label": "Licence", "semantics": "hard", "default": "unknown",
     "description": "Permitted use of the source (L1-07). Nothing sets it yet; a rule can deny `unknown` once sources carry it."},
    {"key": "arm", "label": "Experiment arm", "semantics": "exact", "default": "none",
     "description": "A unit tagged with an arm is a stimulus only that arm's twins see (L7-06 message testing)."},
]

DIMENSION_KEYS = [d["key"] for d in DIMENSIONS]
BY_KEY = {d["key"]: d for d in DIMENSIONS}

# Channels a member of the public plausibly uses, by name hint. Used to derive a lay twin's
# channel set from the ontology's channel nodes; a professional or technical twin gets them all.
PUBLIC_CHANNEL_HINTS = [
    "press", "news", "paper", "gazette", "radio", "tv", "television", "social", "facebook", "reddit", "twitter", "x ", "tiktok",
    "instagram", "youtube", "whatsapp", "word of mouth", "friends", "family", "community", "pharmacy", "counter", "app", "nhs app",
    "website", "leaflet", "poster", "gp letter", "letter", "text message", "sms", "forum", "patient group", "charity", "school",
]
PROFESSIONAL_CHANNEL_HINTS = ["rep", "journal", "guideline", "nice", "conference", "mdt", "cpd", "formulary", "bulletin", "webinar", "training", "peer"]


def is_public_channel(name: str) -> bool:
    n = (name or "").lower()
    if any(h in n for h in PROFESSIONAL_CHANNEL_HINTS) and not any(h in n for h in ("press", "social", "app")):
        return False
    return any(h in n for h in PUBLIC_CHANNEL_HINTS)


# The default session policy written when a session is first tagged. Rules are evaluated in
# order after the registry's base match; see engine.evaluate for the effects.
DEFAULT_SESSION_RULES: list[dict] = [
    {"dimension": "channel", "when": "own", "effect": "boost", "weight": 0.6,
     "note": "Prefer what reached the twin through a channel it actually uses."},
    {"dimension": "provenance", "when": ["social_signal"], "effect": "route", "route": "from people talking about it online",
     "note": "Social evidence always reads as hearsay, whatever channel it was tagged with."},
    {"dimension": "provenance", "when": ["model_inference"], "effect": "boost", "weight": -0.3,
     "note": "The debate's own posts and synthetic papers rank below real sources."},
]

RULE_EFFECTS = ["deny", "require", "allow", "boost", "route"]


def validate_rules(rules: list) -> list[dict]:
    """Shape-check a policy: known dimension, known effect, a usable `when`. Raises ValueError."""
    if not isinstance(rules, list):
        raise ValueError("rules must be a list")
    out = []
    for k, r in enumerate(rules):
        if not isinstance(r, dict):
            raise ValueError(f"rule {k}: not an object")
        dim = r.get("dimension")
        if dim not in BY_KEY:
            raise ValueError(f"rule {k}: unknown dimension {dim!r}")
        eff = r.get("effect")
        if eff not in RULE_EFFECTS:
            raise ValueError(f"rule {k}: unknown effect {eff!r}")
        when = r.get("when", "any")
        if not (when in ("own", "unscoped", "any") or isinstance(when, list)):
            raise ValueError(f"rule {k}: `when` must be own | unscoped | any | [values]")
        if eff == "boost":
            try:
                float(r.get("weight", 0))
            except (TypeError, ValueError):
                raise ValueError(f"rule {k}: boost needs a numeric weight")
        if eff == "route" and not isinstance(r.get("route", ""), str):
            raise ValueError(f"rule {k}: route needs a text")
        out.append({k2: v for k2, v in r.items()})
    return out
