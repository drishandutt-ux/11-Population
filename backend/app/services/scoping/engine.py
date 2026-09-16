"""The retrieval engine: pure functions from (units, ontology, profile, rules, query) to what a
twin sees, with a score, a route and the reason anything was hidden. No I/O, no model.

Evaluation per unit:
  1. base match on every dimension the twin carries a value for, using the registry semantics;
     a unit silent on a dimension falls to the dimension's default;
  2. policy rules in order — deny / require drop the unit, allow re-admits a base failure
     (never on a `hard` dimension), boost adjusts the score, route sets how the twin knows it;
  3. score = query-term overlap + trust + boosts; ties broken by recency of insertion.
"""
from __future__ import annotations

import re
from typing import Any

from .registry import BY_KEY, DIMENSIONS, REGISTER_LEVELS

_STOP = set("the a an and or of to in on for with is are was were be by at as it its this that from into about over under than then will would could should not no".split())


def query_terms(query: str) -> list[str]:
    out = []
    for t in re.split(r"[^\w]+", (query or "").lower()):
        if len(t) >= 4 and t not in _STOP and t not in out:
            out.append(t)
    return out


def ancestors_map(onto: dict | None) -> dict[str, set[str]]:
    """node → every node it sits within, transitively, from the ontology's `within` edges."""
    parents: dict[str, set[str]] = {}
    for e in (onto or {}).get("edges", []):
        if e.get("predicate") == "within":
            parents.setdefault(e["head"], set()).add(e["tail"])
    out: dict[str, set[str]] = {}

    def climb(n: str, seen: set[str]) -> set[str]:
        if n in out:
            return out[n]
        acc: set[str] = set()
        for p in parents.get(n, ()):
            if p in seen:
                continue
            acc.add(p)
            acc |= climb(p, seen | {p})
        out[n] = acc
        return acc

    for n in list(parents):
        climb(n, {n})
    return out


def _as_list(v: Any) -> list:
    if v is None or v == "":
        return []
    return list(v) if isinstance(v, (list, tuple, set)) else [v]


def base_match(dim: dict, unit_val: Any, twin_val: Any, anc: dict[str, set[str]]) -> tuple[bool, str]:
    """(visible, reason). The twin carrying no value means the dimension is not applied."""
    sem = dim["semantics"]
    twin_list = _as_list(twin_val) if sem in ("hierarchical", "overlap") else twin_val
    if (sem in ("hierarchical", "overlap") and not twin_list) or (sem not in ("hierarchical", "overlap") and twin_val in (None, "", [])):
        return True, "not applied"
    unit_list = _as_list(unit_val)
    if not unit_list:
        d = dim["default"]
        if d in ("public", "none"):
            return True, "unscoped"
        if d == "unknown":
            return True, "unknown"
        return False, "unscoped on a deny-by-default dimension"
    if sem == "hierarchical":
        reach = set()
        for t in twin_list:
            reach.add(t)
            reach |= anc.get(t, set())
        ok = any(u in reach for u in unit_list)
        return ok, "reaches" if ok else f"about {', '.join(unit_list[:3])}, not the twin's place"
    if sem == "overlap":
        shared = [u for u in unit_list if u in set(twin_list)]
        return (True, f"shares {shared[0]}") if shared else (False, f"needs {', '.join(unit_list[:3])}")
    if sem == "ordinal":
        levels = dim.get("values", REGISTER_LEVELS)
        try:
            ok = levels.index(str(unit_list[0])) <= levels.index(str(twin_val))
        except ValueError:
            ok = True
        return ok, "within cap" if ok else f"{unit_list[0]} is above the twin's {twin_val} cap"
    if sem == "temporal":
        ok = str(unit_list[0]) <= str(twin_val)
        return ok, "in time" if ok else f"dated {unit_list[0]}, after the twin's as_of {twin_val}"
    ok = str(unit_list[0]) == str(twin_val)
    return ok, "equal" if ok else f"{unit_list[0]} ≠ {twin_val}"


def _when_matches(rule: dict, unit_val: Any, twin_val: Any) -> bool:
    when = rule.get("when", "any")
    unit_list = [str(x) for x in _as_list(unit_val)]
    if when == "any":
        return True
    if when == "unscoped":
        return not unit_list
    if when == "own":
        twin_list = {str(x) for x in _as_list(twin_val)}
        return bool(twin_list and set(unit_list) & twin_list)
    if isinstance(when, list):
        return bool(set(unit_list) & {str(x) for x in when})
    return False


_PROVENANCE_ROUTE = {
    "official_statistic": "from official statistics you looked up",
    "peer_reviewed": "from a research paper you read",
    "grey_literature": "from something you read",
    "commissioned_research": "from survey findings you were shown",
    "client_data": "from documents you were given",
    "social_signal": "from people talking about it online",
    "model_inference": "from the discussion so far",
}


def route_for(unit: dict, profile_values: dict) -> str:
    chans = [c for c in _as_list(unit.get("facets", {}).get("channel")) if c in set(_as_list(profile_values.get("channel")))]
    prov = _PROVENANCE_ROUTE.get(unit.get("provenance_class", ""), "from something you came across")
    if chans:
        return f"via {chans[0]}"
    return prov


_TRUST = {"high": 0.6, "medium": 0.3, "low": 0.0}


def score(unit: dict, terms: list[str]) -> float:
    text = (unit.get("text") or "").lower()
    hits = sum(1 for t in terms if t in text)
    return hits * 1.0 + _TRUST.get(unit.get("trust_tier", "medium"), 0.3)


def evaluate(unit: dict, profile_values: dict, rules: list[dict], anc: dict[str, set[str]]) -> dict:
    """{visible, failed: [(dimension, reason)], boost, route, applied: [rule notes]}"""
    facets = unit.get("facets", {}) or {}
    unit_view = dict(facets)
    unit_view["provenance"] = unit.get("provenance_class")
    failed: list[tuple[str, str]] = []
    checks: dict[str, tuple[bool, str]] = {}
    for dim in DIMENSIONS:
        k = dim["key"]
        ok, why = base_match(dim, unit_view.get(k), profile_values.get(k), anc)
        checks[k] = (ok, why)
        if not ok:
            failed.append((k, why))

    boost = 0.0
    route = None
    applied: list[str] = []
    denied = False
    for r in rules:
        k = r.get("dimension")
        if k not in BY_KEY:
            continue
        hit = _when_matches(r, unit_view.get(k), profile_values.get(k))
        eff = r.get("effect")
        if eff == "deny" and hit:
            denied = True
            failed.append((k, f"denied by rule: {r.get('note') or r.get('when')}"))
            applied.append(f"deny:{k}")
        elif eff == "require" and not hit:
            denied = True
            failed.append((k, f"required by rule: {r.get('note') or r.get('when')}"))
            applied.append(f"require:{k}")
        elif eff == "allow" and hit:
            override = r.get("override") or [k]
            kept = []
            for fk, why in failed:
                if fk in override and BY_KEY[fk]["semantics"] != "hard" and not why.startswith(("denied by", "required by")):
                    applied.append(f"allow:{fk}")
                    continue
                kept.append((fk, why))
            failed = kept
        elif eff == "boost" and hit:
            boost += float(r.get("weight", 0))
            applied.append(f"boost:{k}")
        elif eff == "route" and hit:
            route = str(r.get("route", "")).replace("{value}", ", ".join(str(x) for x in _as_list(unit_view.get(k))[:2]))
            applied.append(f"route:{k}")
    visible = not failed and not denied
    return {"visible": visible, "failed": failed, "boost": boost, "route": route, "applied": applied, "checks": checks}


def retrieve(units: list[dict], onto: dict | None, profile: dict, rules: list[dict], query: str, limit: int = 14) -> dict:
    """{visible: [{unit, score, route, applied}], hidden: [{unit, failed}], profile_values}"""
    anc = ancestors_map(onto)
    terms = query_terms(query)
    pv = profile.get("values", {})
    visible, hidden = [], []
    for order, u in enumerate(units):
        ev = evaluate(u, pv, rules, anc)
        if ev["visible"]:
            visible.append({"unit": u, "score": score(u, terms) + ev["boost"], "route": ev["route"] or route_for(u, pv), "applied": ev["applied"], "order": order})
        else:
            hidden.append({"unit": u, "failed": ev["failed"]})
    visible.sort(key=lambda r: (-r["score"], -r["order"]))
    return {"visible": visible[:limit], "visible_total": len(visible), "hidden": hidden, "profile_values": pv}


def knowledge_block(visible: list[dict], max_chars: int = 3600) -> str:
    lines = ["Where you know each thing from is in brackets."]
    used = len(lines[0])
    for r in visible:
        text = " ".join((r["unit"].get("text") or "").split())
        line = f"- ({r['route']}) {text[:420]}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)
