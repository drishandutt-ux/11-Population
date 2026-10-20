"""A twin's standing toward the topic: who it is in relation to the question, set when the
persona is written and editable afterwards — not guessed from job words at retrieval time.

Until this (2026-10-20), "patient" was inferred from words like driver or mum, expertise was
read off the emotion dial, and nothing told a twin what it was NOT. The Oxford consultant
spoke about Blackpool's GP surgeries as fact; a Blackpool freelancer with two items of real
knowledge invented a chemist on Church Street; a healthcare assistant was a "patient".

Standing has four parts, each with a basis (written by the persona writer, inferred from the
record, or set by an analyst):

  lived          yes | no | carer | past — has this person lived with / used / been the subject
                 of the topic themselves (with a phrase saying what exactly)
  professional   none, or the trained role whose training bears on the topic (with a phrase on
                 what that training actually covers)
  expertise      lay | professional | technical — how specialist their working knowledge of
                 THIS topic is; this, not the emotion dial, caps the register of what they see
  places         home, and the places they have actually lived or worked

Pure helpers below (`normalise`, `infer`, `of`, `register_for`, `block`, `footprint`) do no
I/O; `check_post` is the one model call — a fast judge that flags where a post stepped
outside its author's standing, so the breach is visible on the post.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .registry import REGISTER_LEVELS

LIVED = ("yes", "no", "carer", "past")
EXPERTISE = tuple(REGISTER_LEVELS)
BASES = ("written", "inferred", "set")

#: Roles whose training is research-grade on a health or policy topic → technical register.
_TECHNICAL_HINTS = ("consultant", "professor", "researcher", "research fellow", "epidemiolog", "scientist", "statistician", "academic",
                    "lecturer", "phd", "biochem", "pharmacolog", "surgeon", "economist", "clinical lead", "medical director", "registrar")
#: Roles with clinical or system training → professional register.
_PROFESSIONAL_HINTS = ("gp", "doctor", "dr ", "physician", "nurse", "pharmacist", "clinician", "physio", "dietitian", "dietician", "midwife",
                       "paramedic", "healthcare assistant", "health care assistant", "nursing", "practice manager", "commissioner", "nhs manager",
                       "public health", "health visitor", "occupational therap", "psycholog", "therapist", "optometrist", "dentist", "care manager",
                       "social worker", "medical", "clinical")
_CONDITION = r"(obesity|overweight|diabetes|type ?[12]|weight|chronic|pain|asthma|copd|depression|anxiety|arthritis|fibromyalgia|hypertension|cancer|heart|dementia|ms|multiple sclerosis|a condition|the condition|this condition|it|this)"
#: Signs the record is about the person's OWN body or life with the topic — never "lives with his wife",
#: never a clinician's "patients who have diabetes" (the bare word "patient" used to count, so a practice
#: manager "overseeing patient flow" was a patient).
_SELF_PATTERNS = [
    r"\b(her|his|their|my) own (weight|condition|diagnosis|health|illness|experience of)\b",
    r"\b(herself|himself|themselves|myself)\b.{0,40}\b(weight|condition|diagnos|treatment)",
    r"\b(lives?|living|lived) with " + _CONDITION + r"\b",
    r"\b(was|been|recently|newly|since being) diagnosed\b", r"\bdiagnosed (with|in|at|eighteen|two|three|last)\b",
    r"\bon (metformin|insulin|statins|a waiting list|the jab|the injection)s?\b",
    r"\b(uses?|used|tried|trying|takes?|taking|was prescribed|been prescribed) (it|the drug|the pill|the jab|the medication|wegovy|mounjaro|ozempic|a glp)\b",
    r"\bservice user\b", r"\bsurviv(or|ed)\b", r"\bin recovery\b", r"\bwas treated for\b", r"\bbeen through (it|this)\b",
]
#: Broader signs, trusted only for a record with no clinical training (a clinician's record talks about conditions all day).
_LAY_LIVED_PATTERNS = [
    r"\bstruggl\w* with (her|his|their|my) (weight|health)\b",
    r"\b(has|had|have) (type ?2|type ?1|diabetes|obesity|asthma|copd|cancer|depression|arthritis|fibromyalgia|hypertension|a heart attack)\b",
]
_PAST_MARKERS = r"\b(used to|formerly|years ago|in the past|recovered|no longer|back in|before)\b"
_CARER_PATTERNS = [r"\bcarer\b", r"\bcares? for (her|his|their|my) (mum|mother|dad|father|husband|wife|partner|son|daughter|parent)", r"\blooks? after (her|his|their|my) (mum|mother|dad|father|husband|wife|partner|son|daughter|parent)",
                   r"\bcaregiver\b", r"\b(her|his|their|my) (mum|mother|dad|father|husband|wife|partner|son|daughter) (has|had|lives with|was diagnosed)"]


def _text(v: Any, limit: int) -> str:
    return " ".join(str(v or "").split())[:limit]


def _places(v: Any, limit: int = 8) -> list[str]:
    if isinstance(v, str):
        v = [p for p in re.split(r"[;,\n]| and ", v)]
    out: list[str] = []
    for p in (v or []):
        t = _text(p, 60)
        if t and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out[:limit]


def normalise(d: Any, *, home: str = "", basis: str = "written") -> Optional[dict]:
    """A model-written or analyst-set standing → the stored shape, or None when unusable.
    `home` (the twin's region) is always among the known places."""
    if not isinstance(d, dict):
        return None
    lived = str(d.get("lived") or "").strip().lower()
    if lived in ("true", "y"):
        lived = "yes"
    if lived in ("false", "n", "none"):
        lived = "no"
    if lived not in LIVED:
        lived = "no"
    prof = _text(d.get("professional"), 120)
    if prof.lower() in ("none", "no", "n/a", "-", "null"):
        prof = ""
    expertise = str(d.get("expertise") or "").strip().lower()
    if expertise not in EXPERTISE:
        expertise = "lay" if not prof else "professional"
    home_t = _text(d.get("home") or home, 120)
    known = _places(d.get("known_places"))
    if home_t:   # home always first
        known = [home_t] + [k for k in known if k.lower() != home_t.lower()]
    out = {
        "lived": lived,
        "lived_detail": _text(d.get("lived_detail"), 200) if lived != "no" else "",
        "professional": prof,
        "professional_field": _text(d.get("professional_field"), 200) if prof else "",
        "expertise": expertise,
        "home": home_t,
        "known_places": known,
        "basis": basis if basis in BASES else "written",
    }
    if isinstance(d.get("elsewhere"), list):
        out["elsewhere"] = _places(d.get("elsewhere"), 12)
    return out


def _head(role: str) -> str:
    return re.split(r"[,(/|·—–]| and | at | for | with ", str(role or ""), maxsplit=1)[0].strip()


def infer(agent: Any) -> dict:
    """A deterministic standing for a twin whose record carries none (written before
    2026-10-20, or a persona writer that skipped the key): from the role, background and
    relationship to the topic. Basis `inferred` — the prompt then speaks less firmly."""
    role = str(getattr(agent, "role", "") or "")
    text = " ".join([role, str(getattr(agent, "correlation", "") or ""), str(getattr(agent, "background", "") or "")[:600]]).lower()
    rl = role.lower()
    prof = ""
    expertise = "lay"
    if any(h in rl for h in _TECHNICAL_HINTS):
        prof, expertise = _head(role), "technical"
    elif any(h in rl for h in _PROFESSIONAL_HINTS) or re.search(r"\bOT\b", role):
        prof, expertise = _head(role), "professional"
    lived = "no"
    patterns = _SELF_PATTERNS + ([] if prof else _LAY_LIVED_PATTERNS)
    hit = next((m for m in (re.search(p, text) for p in patterns) if m), None)
    if any(re.search(p, text) for p in _CARER_PATTERNS):
        lived = "carer"   # "looks after her mum, who has type 2" is the mum's condition, not hers
    elif re.search(r"\bpatient\b", rl) and not re.search(r"patient (group|advocate|liaison|safety|experience|flow|access)", rl):
        lived = "yes"
    elif hit and not re.search(r"\bpatient", rl):
        # "past" only when a past marker sits next to the sign, not anywhere in the record
        lived = "past" if re.search(_PAST_MARKERS, text[max(0, hit.start() - 60):hit.end() + 30]) else "yes"
    demo = getattr(agent, "demographics", None) or {}
    home = str(demo.get("region") or "") if isinstance(demo, dict) else ""
    return normalise({"lived": lived, "professional": prof, "expertise": expertise, "home": home}, home=home, basis="inferred") or {}


def of(agent: Any) -> dict:
    """The twin's standing: what is stored on it, else inferred from its record."""
    st = getattr(agent, "standing", None)
    if isinstance(st, dict) and st.get("lived") in LIVED:
        clean = normalise(st, home=st.get("home") or "", basis=st.get("basis") or "written") or {}
        if "elsewhere" in st and "elsewhere" not in clean:
            clean["elsewhere"] = _places(st.get("elsewhere"), 12)
        return clean
    return infer(agent)


def register_for(standing: dict) -> str:
    e = str((standing or {}).get("expertise") or "lay")
    return e if e in EXPERTISE else "lay"


def spoke_from(standing: dict) -> str:
    """The one word a post's chip leads with: lived · carer · professional · public."""
    lived = (standing or {}).get("lived")
    if lived in ("yes", "past"):
        return "lived"
    if lived == "carer":
        return "carer"
    if (standing or {}).get("professional"):
        return "professional"
    return "public"


def summary(standing: dict) -> str:
    """One short line for a card: 'lives with it · GP · Oxford'."""
    st = standing or {}
    bits = []
    bits.append({"yes": "lives with it", "past": "lived with it before", "carer": "cares for someone with it", "no": "no lived experience"}.get(st.get("lived"), "no lived experience"))
    bits.append(st["professional"] if st.get("professional") else "no training in it")
    if st.get("home"):
        bits.append(st["home"].split(",")[0].strip())
    return " · ".join(bits)


_EXPERTISE_LINES = {
    "lay": "Your working knowledge of this topic is a layperson's: everyday words, what you have read, heard and seen; you have no feel for the technical detail and you do not fake one.",
    "professional": "Your working knowledge of this topic is a professional's: you know how it works in practice in your own field, the rules and routines you deal with, and you say so in plain professional terms — but trial methods, statistics and other specialities are beyond you.",
    "technical": "Your working knowledge of this topic is technical: methods, figures and mechanisms are your home ground and you can be precise about them.",
}


def block(agent: Any, standing: Optional[dict] = None) -> str:
    """The persona prompt's WHO YOU ARE TO THIS TOPIC — AND WHO YOU ARE NOT block, written from
    the standing fields. Deterministic: the same standing always produces the same rules."""
    st = standing or of(agent)
    firm = st.get("basis") != "inferred"
    lines: list[str] = []

    lived, detail = st.get("lived"), st.get("lived_detail") or ""
    with_detail = f" — {detail}" if detail else ""
    if lived == "yes":
        lines.append(f"- Lived experience: you live with this yourself{with_detail}. You speak about it from the inside — your body, your appointments, "
                     "what you were told, what it cost you, how it felt. That is your authority, and it is a real one; it does not make you a clinician.")
    elif lived == "past":
        lines.append(f"- Lived experience: you went through this yourself in the past{with_detail}. You speak from memory of it; what is current may have changed since, and you know that.")
    elif lived == "carer":
        lines.append(f"- Lived experience: you have lived alongside it as a carer{with_detail}. You know the appointments, the costs and the day-to-day from inside the house, "
                     "not inside the body. You never claim the body's experience — the symptoms, the side effects, the feeling of it — as your own.")
    else:
        if firm:
            lines.append("- Lived experience: NONE. You have not lived with this yourself. You never describe the feeling of it, the side effects, the appointments or the costs as your own; "
                         "if you talk about them it is what people you know" + (", or your patients," if st.get("professional") else "") + " have told you — and you say so.")
        else:
            lines.append("- Lived experience: nothing in your record says you have lived with this yourself. Unless your background above says otherwise, speak as someone who has not: "
                         "never describe the feeling of it, the side effects or the appointments as your own.")

    prof, field = st.get("professional") or "", st.get("professional_field") or ""
    if prof:
        lines.append(f"- Training: you are trained as {prof}" + (f" — {field}" if field else "") + ". That is the ground you speak on with authority. "
                     "Outside it — another speciality, another trade — you are a layperson like anyone else and you say so.")
    else:
        lines.append("- Training: NONE in this. You cannot explain how it works in the body, doses, guidelines, what clinicians or officials do and why, or the system's rules from the inside — "
                     "and you never try to. What you can say is what you have read or heard, what you were told, and what you have seen; say which it is."
                     if firm else
                     "- Training: your record shows no professional training in this. Do not explain mechanisms, doses, guidelines or how the system works from the inside; "
                     "stick to what you have read, heard, been told or seen, and say which it is.")

    lines.append("- " + _EXPERTISE_LINES.get(register_for(st), _EXPERTISE_LINES["lay"]))

    home = st.get("home") or ""
    known = [p for p in (st.get("known_places") or []) if p]
    elsewhere = [p for p in (st.get("elsewhere") or []) if p]
    if home or known:
        others = [p for p in known if p.lower() != home.lower()]
        place = f"- Place: you live in {home}." if home else "- Place:"
        if others:
            place += f" You have also lived or worked in {', '.join(others[:5])}."
        place += " Those are the places you know first-hand — the streets, the surgeries, the prices, the waiting times, the way people there talk."
        if elsewhere:
            place += f" Any other place — {', '.join(elsewhere[:6])} — you know only second-hand:"
        else:
            place += " Any other place you know only second-hand:"
        place += (" from the news, from people, from what has been said here. Speak about it as second-hand (\"from what I've read…\", \"I hear…\"), keep it general, "
                  "and be ready to be wrong. Never state a specific about a place you have not lived in — a street, a surgery, a price, a waiting time — as if you had seen it.")
        lines.append(place)

    return "\n\nWHO YOU ARE TO THIS TOPIC — AND WHO YOU ARE NOT (these decide what you can speak to; never step outside them):\n" + "\n".join(lines)


# ── the footprint a post carries ──────────────────────────────────────────────

def footprint(agent: Any, retrieval: Optional[dict], *, scoped: bool, snapshot_id: Optional[str] = None, standing: Optional[dict] = None) -> dict:
    """What a post was spoken from: the author's standing, how many items of knowledge it was
    given, how many were kept back and on which dimension. `retrieval` is `engine.retrieve`'s
    result (None when the session is not scoped)."""
    st = standing or of(agent)
    out: dict = {
        "spoke_from": spoke_from(st),
        "standing": {"lived": st.get("lived"), "professional": st.get("professional") or "", "expertise": st.get("expertise"), "home": st.get("home") or "", "basis": st.get("basis")},
        "scoped": bool(scoped and retrieval is not None),
        "used": 0, "withheld": 0, "withheld_by": {}, "routes": [], "snapshot_id": snapshot_id,
    }
    if retrieval:
        visible = retrieval.get("visible") or []
        out["used"] = len(visible)
        hidden = retrieval.get("hidden") or []
        out["withheld"] = len(hidden)
        by: dict[str, int] = {}
        for h in hidden:
            dims = sorted({str(f[0]) for f in (h.get("failed") or []) if f})
            for d in dims:
                by[d] = by.get(d, 0) + 1
        out["withheld_by"] = dict(sorted(by.items(), key=lambda kv: -kv[1]))
        out["routes"] = sorted({str(r.get("route") or "") for r in visible if r.get("route")})[:6]
    return out


# ── the scope check ───────────────────────────────────────────────────────────

BREACH_KINDS = ("clinical_claim", "lived_claim", "place_as_fact", "beyond_training")
BREACH_LABELS = {
    "clinical_claim": "clinical claim without training",
    "lived_claim": "lived experience claimed",
    "place_as_fact": "another place stated as fact",
    "beyond_training": "beyond their field",
}

_CHECK_SYSTEM = """You check whether a post written in character stayed inside its author's standing. You are given who the author
is to the topic (lived experience, training, places they know first-hand) and the post. Flag ONLY clear breaches:

- clinical_claim: the author has NO relevant training yet explains mechanism, dosing, guidelines, clinical practice or
  system rules from the inside as if they knew them (repeating something they read or were told, and saying so, is fine).
- lived_claim: the author has NOT lived with the topic (lived = no, or carer) yet describes the experience — symptoms, side
  effects, appointments, costs, the feeling of it — as their own.
- place_as_fact: the author states a SPECIFIC about a place they have not lived or worked in — a named street, surgery,
  shop, price, waiting time, local practice — as fact rather than as something read or heard. General knowledge about a
  well-known place (it is deprived, it is a university town) is NOT a breach.
- beyond_training: the author is trained in one field and speaks with authority in another speciality.

A post that stays general, hedges ("from what I've read"), or speaks about its own place, trade and life is fine. Quote
the offending words exactly (short). When there is no clear breach, return an empty list. Be strict about clear cases
and lenient about everything else — a wrongly flagged post costs more than a missed one."""


def check_schema():
    from app.services.evidence.llm import arr, enum, obj, s
    return obj({
        "breaches": arr(obj({
            "kind": enum(list(BREACH_KINDS)),
            "quote": s("the offending words, verbatim, at most 160 characters"),
            "why": s("one short clause: what the author could not know or be"),
        })),
    })


def check_prompt(standing: dict, post: str, query: str) -> str:
    st = standing or {}
    lived = {"yes": f"YES — {st.get('lived_detail') or 'lives with it'}", "past": f"IN THE PAST — {st.get('lived_detail') or ''}",
             "carer": f"AS A CARER — {st.get('lived_detail') or ''}", "no": "NO"}.get(st.get("lived"), "NO")
    prof = (st.get("professional") or "none") + (f" — {st['professional_field']}" if st.get("professional_field") else "")
    known = ", ".join(st.get("known_places") or ([st["home"]] if st.get("home") else [])) or "unstated"
    return (f"TOPIC: {query}\n\nAUTHOR'S STANDING\n- lived experience: {lived}\n- training: {prof}\n- working knowledge: {st.get('expertise') or 'lay'}\n"
            f"- places known first-hand: {known}\n\nTHE POST\n{post[:2400]}")


def parse_check(res: Any) -> dict:
    """The judge's output → {ok, breaches: [{kind, label, quote, why}]} with unknown kinds dropped."""
    out = []
    for b in (res or {}).get("breaches") or []:
        if not isinstance(b, dict) or b.get("kind") not in BREACH_KINDS:
            continue
        q = _text(b.get("quote"), 160)
        if not q:
            continue
        out.append({"kind": b["kind"], "label": BREACH_LABELS[b["kind"]], "quote": q, "why": _text(b.get("why"), 160)})
    return {"ok": not out, "breaches": out[:4]}


async def check_post(agent: Any, post: str, query: str, *, standing: Optional[dict] = None, session_id: Optional[str] = None, model: Optional[str] = None) -> Optional[dict]:
    """One fast structured call: where did this post step outside its author's standing? None
    when the check could not run (never fails a turn)."""
    if not (post or "").strip():
        return None
    st = standing or of(agent)
    try:
        from app.core.config import get_settings
        from app.services.evidence.llm import analyze
        res = await analyze(check_schema(), _CHECK_SYSTEM, check_prompt(st, post, query), session_id=session_id, label="scope_check",
                            model=model or get_settings().model_fast, max_tokens=500)
        out = parse_check(res)
        out["model"] = model or get_settings().model_fast
        return out
    except Exception as e:  # noqa: BLE001 — a failed check leaves the post unflagged, not missing
        print(f"[scoping.standing] check failed: {type(e).__name__}: {e}")
        return None


#: The JSON the persona writers ask for, and the rules that go with it.
SCHEMA_TEXT = ('"standing": {"lived": "yes" | "no" | "carer" | "past", "lived_detail": "if not no: one phrase on what exactly (e.g. \'type 2 diabetes for nine years, on metformin\')", '
               '"professional": "none" | "the trained role whose training bears on THIS topic (e.g. \'GP\', \'community pharmacist\', \'transport planner\')", '
               '"professional_field": "if trained: one phrase on what that training actually covers", "expertise": "lay" | "professional" | "technical", '
               '"known_places": ["every place this person has actually lived or worked, their home first"]}')

INSTRUCTIONS = """STANDING — who each persona is to THIS topic (decides what they can speak to; be honest, not flattering):
- "lived": "yes" only if this person has themselves lived with / used / been the subject of the topic (a patient, a user, someone it happened to); "carer" if they live alongside someone who has; "past" if they did once; otherwise "no". A GP who treats it has NOT lived it. Most people have not.
- "professional": the trained role ONLY if its training bears on this topic. A lawyer, a teacher or a software engineer is "none" on a drug question — a professional, but not in this. "expertise" follows: "technical" for research-grade knowledge (consultants, academics, analysts of this exact subject), "professional" for working clinical / policy / trade knowledge of it, "lay" for everyone else — including clever, educated people whose training is elsewhere.
- "known_places": where they have actually lived or worked. Everything else they know second-hand, and their posts will be held to that."""
