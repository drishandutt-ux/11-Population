"""A twin's exposure profile: the same facet map a knowledge unit carries, derived from what the
agent already is (place, role, segment, humanity band), plus an optional override stored on
the agent (`spawned_agents.exposure`) that an analyst or an experiment can set.

Every derived value records its basis, so the Scoping view can say *why* a twin sees what it
sees ("geography: Blackpool — from demographics.region").
"""
from __future__ import annotations

import re
from typing import Any

from .registry import REGISTER_LEVELS, is_public_channel, vocab



def nodes_by_class(onto: dict | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for n in (onto or {}).get("nodes", []):
        out.setdefault(n.get("cls", "other"), []).append(n["id"])
    return out


def match_nodes(text: str, names: list[str]) -> list[str]:
    """Ontology nodes named in `text`, by case-insensitive containment either way (a region
    string 'Blackpool, Lancashire' matches the node 'Blackpool'; the node 'Greater Manchester'
    matches the string 'Manchester' only if the node is contained, so no)."""
    t = (text or "").strip().lower()
    if not t:
        return []
    out = []
    for n in names:
        nl = n.lower().strip()
        if not nl:
            continue
        if len(nl) <= 3:
            # short names ("GP", "ICB") only on a word boundary, or "gp" would match "gpo"
            if re.search(rf"\b{re.escape(nl)}\b", t):
                out.append(n)
        elif nl in t or (len(t) >= 4 and t in nl):
            out.append(n)
    return out


def _band(humanity: int) -> str:
    from app.services.agents.agent_runner import _humanity_band
    return _humanity_band(int(humanity or 0))


def profile_for(agent: Any, onto: dict | None) -> dict:
    """{values: {dimension: …}, basis: {dimension: str}, band: str}"""
    classes = vocab(nodes_by_class(onto))   # the ontology's nodes plus the base roles and channels (2026-10-20)
    demo = getattr(agent, "demographics", None) or {}
    values: dict[str, Any] = {}
    basis: dict[str, str] = {}

    region = str(demo.get("region") or "")
    geo = match_nodes(region, classes.get("geography", []))
    values["geography"] = geo
    basis["geography"] = f"demographics.region = {region!r}" + ("" if geo else " (no ontology place matched — only unscoped units)") if region else "no region on the agent — geography not applied"

    # Standing (2026-10-20): who this person is to the topic decides role and register — not job
    # words and not the emotion dial. Places they have lived or worked extend their geography.
    from .standing import of as standing_of, register_for
    st = standing_of(agent)
    for place in st.get("known_places") or []:
        for g in match_nodes(place, classes.get("geography", [])):
            if g not in geo:
                geo.append(g)
    if len(geo) > len(match_nodes(region, classes.get("geography", []))):
        basis["geography"] += " + places lived or worked in (standing)"

    roles: list[str] = []
    prof = st.get("professional") or ""
    if prof:
        roles = match_nodes(f"{prof} {getattr(agent, 'role', '')}", classes.get("hcp_role", []))
        basis["role"] = (f"trained as {prof!r} → role(s) {', '.join(roles[:3])}" if roles
                         else f"trained as {prof!r} — no role in the vocabulary matches it")
    else:
        basis["role"] = "no professional standing in this topic"
    if st.get("lived") in ("yes", "past", "carer"):
        roles.append("patient")
        basis["role"] += f" · lived experience ({st['lived']}) → patient"
    roles.append("public")
    basis["role"] += " + public" + (f" [{st.get('basis')}]" if st.get("basis") else "")
    values["role"] = roles

    band = _band(getattr(agent, "humanity", 0))
    register = register_for(st)
    values["register"] = register
    basis["register"] = f"standing: working knowledge is {register} ({st.get('basis')}) — the emotion dial ({band}) sets tone, not expertise"

    channels_all = classes.get("channel", [])
    if register == "lay":
        channels = [c for c in channels_all if is_public_channel(c)]
        basis["channel"] = "lay register → public channels only" + ("" if channels else " (none of the ontology's channels look public)")
    else:
        channels = list(channels_all)
        basis["channel"] = f"{register} register → every channel"
    values["channel"] = channels

    seg = match_nodes(getattr(agent, "segment", "") or "", classes.get("attitude_segment", []))
    values["segment"] = seg
    basis["segment"] = (f"segment {getattr(agent, 'segment', '')!r}" + ("" if seg else " — no ontology segment matched")) if getattr(agent, "segment", None) else "no segment"

    values["condition"] = []
    basis["condition"] = "not applied (no condition on the agent)"
    values["stage"] = []
    basis["stage"] = "not applied"
    values["time"] = None
    basis["time"] = "no as_of date — time not applied"
    values["project"] = getattr(agent, "session_id", "")
    basis["project"] = "the session"
    values["arm"] = None
    basis["arm"] = "no experiment arm"

    override = getattr(agent, "exposure", None) or {}
    if isinstance(override, dict):
        for k, v in override.items():
            if k in values:
                values[k] = v
                basis[k] = "set on the agent (exposure override)"
    if values.get("register") not in REGISTER_LEVELS:
        values["register"] = "lay"
    return {"values": values, "basis": basis, "band": band, "standing": st}


def profile_hash(profile: dict) -> str:
    import hashlib
    import json
    return hashlib.sha1(json.dumps(profile.get("values", {}), sort_keys=True, default=str).encode()).hexdigest()[:16]


def looks_like_date(s: str) -> str:
    """Normalise a date-ish string to YYYY-MM-DD or YYYY; empty when nothing usable."""
    s = (s or "").strip()
    m = re.search(r"(20\d\d|19\d\d)-(\d\d)-(\d\d)", s)
    if m:
        return m.group(0)
    m = re.search(r"\b(20\d\d|19\d\d)\b", s)
    return m.group(1) if m else ""
