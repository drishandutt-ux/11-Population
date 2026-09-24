"""Citations: every claim in a report traces back to the twin who made it (brief L3-03).

The report model is never asked to type a persona's name. It is handed short handles for the
roster (`A1` … `An`) and for the transcript (`P1` … `Pn`) and told to cite `[[A7]]`, or
`[[A7#P12]]` when it is attributing a specific statement. After the call the handles are
rewritten to stable ids:

    [[twin:<agent id>]]                     — this twin
    [[twin:<agent id>|post:<post id>]]      — this twin, saying this

That is what kills the name drift seen in the Blackpool report: the name the reader sees is
read from the agent row at render time, so the model cannot misremember a surname. Any name
it types anyway is repaired into a citation by `repair_names` — a full-name-shaped mention
whose first name belongs to exactly one twin becomes that twin's token, wrong surname and all.

Pure functions; no I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

#: A resolved citation in a stored answer. Group 1 = agent id, group 2 = post id (optional).
TOKEN_RE = re.compile(r"\[\[twin:([0-9a-fA-F-]{36})(?:\|post:([0-9a-fA-F-]{36}))?\]\]")

#: What the model is asked to write: [[A7]], [[A7#P12]], [[A7 | P12]] — all accepted.
_HANDLE_RE = re.compile(r"\[\[\s*(A\d+)\s*(?:[#|,·\s]\s*(P\d+))?\s*\]\]", re.IGNORECASE)

_CAP = r"[A-Z][A-Za-zÀ-ÿ'’\-]+"
_FULL_NAME_RE = re.compile(rf"\b({_CAP})\s+({_CAP})\b")
#: Capitalised words that follow a first name without being a surname.
_NOT_A_SURNAME = {"the", "a", "an", "and", "but", "however", "his", "her", "their", "they",
                  "we", "i", "it", "this", "that", "who", "when", "while", "gp", "nhs", "uk"}


@dataclass
class Handles:
    """The handle ↔ id maps for one report call."""
    agent_by_handle: dict[str, str] = field(default_factory=dict)   # "a7"  → agent id
    post_by_handle: dict[str, str] = field(default_factory=dict)    # "p12" → post id
    handle_of_agent: dict[str, str] = field(default_factory=dict)   # agent id → "A7"
    handle_of_post: dict[str, str] = field(default_factory=dict)    # post id  → "P12"


def build_handles(agents: Iterable[Any], posts: Iterable[Any]) -> Handles:
    """Number the roster and the transcript. Handles are short so the model spends no
    tokens on UUIDs and cannot mistype one into a different person."""
    h = Handles()
    for i, a in enumerate(agents, 1):
        handle = f"A{i}"
        h.agent_by_handle[handle.lower()] = a.id
        h.handle_of_agent[a.id] = handle
    for i, p in enumerate(posts, 1):
        handle = f"P{i}"
        h.post_by_handle[handle.lower()] = p.id
        h.handle_of_post[p.id] = handle
    return h


def _origin(agent: Any) -> str:
    """Who this twin is, as a provenance phrase: which mould, which segment, or model-written."""
    ch = getattr(agent, "character", None) or {}
    arch = (ch or {}).get("archetype") or {}
    seg = getattr(agent, "segment", None)
    if arch.get("name"):
        return f"cast from the '{arch['name']}' archetype" + (f", segment {seg}" if seg else "")
    if ch:
        return "hand-authored twin"
    if seg:
        return f"written for segment {seg}"
    return "written for this session"


def roster_block(agents: list[Any], handles: Handles) -> str:
    """The roster the model cites from: handle, identity, where they sit, where they came from."""
    lines = []
    for a in agents:
        demo = getattr(a, "demographics", None) or {}
        place = demo.get("region") or ""
        bits = [f"{a.role}", f"age {a.age}"]
        if place:
            bits.append(place)
        stance = getattr(a.stance, "value", a.stance)
        lines.append(
            f"[{handles.handle_of_agent.get(a.id, '?')}] {a.name} — {', '.join(bits)} | "
            f"stance={stance} | {_origin(a)} | {(a.background or '')[:240]}"
        )
    return "\n".join(lines)


def transcript_block(posts: list[Any], agents_map: dict[str, Any], handles: Handles) -> str:
    """The verbatim transcript with a handle on every line, so a citation can point at one
    statement rather than at a person in general."""
    lines = []
    for post in posts:
        if getattr(post.type, "value", post.type) == "like":
            continue
        agent = agents_map.get(post.agent_id)
        ah = handles.handle_of_agent.get(post.agent_id, "?")
        ph = handles.handle_of_post.get(post.id, "?")
        who = f"{ah} {agent.name} | {agent.role}" if agent else f"{ah} Unknown"
        prefix = "  > " if post.parent_id else ""
        lines.append(f"{prefix}[{ph} · {who}]: {post.content}")
    return "\n\n".join(lines)


def resolve(text: str, handles: Handles) -> str:
    """Rewrite the model's handles into stable-id citations. A handle that names nobody is
    dropped rather than shown — a dangling citation is worse than none."""
    def sub(m: re.Match) -> str:
        agent_id = handles.agent_by_handle.get((m.group(1) or "").lower())
        if not agent_id:
            return ""
        post_id = handles.post_by_handle.get((m.group(2) or "").lower()) if m.group(2) else None
        return f"[[twin:{agent_id}|post:{post_id}]]" if post_id else f"[[twin:{agent_id}]]"

    out = _HANDLE_RE.sub(sub, text)
    return re.sub(r"[ \t]{2,}", " ", out)


def repair_names(text: str, agents: list[Any]) -> str:
    """Turn any name the model typed into a citation.

    Exact full names become that twin's token. A full-name-shaped mention whose *first* name
    belongs to exactly one twin becomes that twin's token too — which is how a drifted surname
    ("Sarah Whitfield" for Sarah Whitmore) is corrected rather than printed."""
    full_map: dict[str, str] = {}
    first_map: dict[str, list[str]] = {}
    for a in agents:
        name = (a.name or "").strip()
        if not name:
            continue
        full_map.setdefault(name.lower(), a.id)
        first = name.split()[0].lower()
        first_map.setdefault(first, []).append(a.id)

    def repair_span(span: str) -> str:
        def sub(m: re.Match) -> str:
            first, second = m.group(1), m.group(2)
            # "Sarah Whitmore's list" — the possessive belongs to the sentence, not the name.
            poss = ""
            if second.lower().endswith(("'s", "’s")):
                second, poss = second[:-2], second[-2:]
            exact = full_map.get(f"{first} {second}".lower())
            if exact:
                return f"[[twin:{exact}]]{poss}"
            owners = first_map.get(first.lower(), [])
            if len(owners) == 1 and second.lower() not in _NOT_A_SURNAME:
                return f"[[twin:{owners[0]}]]{poss}"
            return m.group(0)
        return _FULL_NAME_RE.sub(sub, span)

    # Walk the text around the citations already present so tokens are never rewritten.
    out, pos = [], 0
    for m in TOKEN_RE.finditer(text):
        out.append(repair_span(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(repair_span(text[pos:]))
    return "".join(out)


def cited_ids(text: str) -> list[str]:
    """The twins a finished answer actually cites, in order of first appearance."""
    seen: list[str] = []
    for m in TOKEN_RE.finditer(text):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


CITATION_RULES = (
    "CITATIONS — how to refer to a person:\n"
    "- NEVER type a persona's name. Cite the handle instead: [[A7]] renders as that twin's "
    "real name, read from the population record.\n"
    "- When you attribute a specific statement, quote or position, cite the line it came from: "
    "[[A7#P12]]. Use the post handle shown at the start of each transcript line.\n"
    "- Write around the citation as if it were the name: \"[[A7]] argued that …\", "
    "\"two pharmacists ([[A3]], [[A9]]) disagreed\".\n"
    "- Never write \"some agents\" or \"several participants\" — cite them.\n"
    "- Never invent a handle. Only handles listed in the roster exist."
)
