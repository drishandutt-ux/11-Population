"""Survey — a form the analyst builds, every persona completes in one call.

The general form of "ask them anything": a title, an optional intro or material shown once,
then any number of questions of these types —

    single   one option of several            multi   any number of options
    scale    an integer between min and max   yesno   yes / no
    number   a free number                    text    a free answer (coded into themes after)
    grid     rows × columns, one column per row (the Likert matrix)

The answer schema is generated from the form (reasoning first, then one field per question),
so the reply is always typed. Aggregation is per question by type, with intervals; open text
is theme-coded per question. Templates are just saved forms — "Reaction" is the old Ask.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.services.evidence.llm import arr, enum, i, n, obj, s
from app.services.measurement import stats
from app.services.measurement.probe import split_keys
from app.services.measurement.instruments import InputField, Instrument, Kpi, register
from app.services.measurement.themes import apply_themes, theme_key_for

TYPES = ("single", "multi", "scale", "yesno", "number", "text", "grid")
MAX_QUESTIONS = 25
MAX_OPTIONS = 16

DIRECTIVE = """

YOU ARE FILLING IN A SURVEY, NOT WRITING A POST.
- Your answers are private. Nobody in the discussion sees them, so there is nothing to perform.
  Answer as yourself, from your own life, circumstances and what you actually think.
- Answer every question. Pick the option that is closest to you even when none is perfect; use
  the middle of a scale only when you genuinely sit in the middle.
- Where the form offers "Don't know" (or "None of the above"), use it when that is honestly
  where you are — you have not heard of it, never thought about it, or could not say — as real
  respondents often do. Do not manufacture an opinion you would not have.
- "Have you heard of / could you explain …" questions: answer as someone with your education,
  job and life really would. Outside medicine, most people have never heard of rare conditions
  or technical terms, and far fewer could explain them — only say you know what your life has
  actually shown you.
- Give YOUR answer, not the one that sounds kindest, most balanced or most sensible. If you are
  blunt, sceptical, uninterested or out of step with polite opinion, answer that way.
- Open questions: answer in your own words, specifically — one or two sentences, in character.
- Keep the whole form consistent: your reasoning first, then answers that follow from it."""


# ── the form ──────────────────────────────────────────────────────────────────

def _slug(text: str, fallback: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return (t[:24] or fallback)


def normalise(questions: Any) -> list[dict]:
    """Questions as the builder sends them, cleaned: stable keys, trimmed text and options."""
    out = []
    for idx, q in enumerate(list(questions or [])[:MAX_QUESTIONS]):
        if not isinstance(q, dict):
            continue
        qtype = str(q.get("type") or "single")
        key = str(q.get("key") or "").strip() or f"q{idx + 1}"
        opts = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()][:MAX_OPTIONS]
        rows = [str(o).strip() for o in (q.get("rows") or []) if str(o).strip()][:MAX_OPTIONS]
        cols = [str(o).strip() for o in (q.get("columns") or []) if str(o).strip()][:MAX_OPTIONS]
        out.append({
            "key": key,
            "type": qtype if qtype in TYPES else "single",
            "text": str(q.get("text") or "").strip(),
            "options": opts,
            "rows": rows,
            "columns": cols,
            "min": int(q.get("min") if q.get("min") is not None else 1),
            "max": int(q.get("max") if q.get("max") is not None else 5),
            "min_label": str(q.get("min_label") or "").strip(),
            "max_label": str(q.get("max_label") or "").strip(),
            "primary": bool(q.get("primary")),
            # "Select up to three": a cap on a multi question (0 = no cap).
            "max_choices": max(0, int(q.get("max_choices") or 0)) if qtype == "multi" else 0,
            # Options that stand alone ("Don't know", "None of the above"): never ticked with others.
            "exclusive": [str(o).strip() for o in (q.get("exclusive") or []) if str(o).strip() in opts],
            # Routing: asked only of those who gave `equals` to question `key` (e.g. "why not?"
            # only to those who said yes). Everyone else is out of this question's base.
            "show_if": _show_if(q.get("show_if")),
            # Answer as likelihoods (see distribution_mode): per question, so it survives the
            # Forms editor, which copies questions but not form-level settings.
            "likelihood": bool(q.get("likelihood")),
        })
    return out


def _show_if(v: Any) -> Optional[dict]:
    if not isinstance(v, dict) or not str(v.get("key") or "").strip():
        return None
    eq = v.get("equals")
    vals = [str(x).strip() for x in (eq if isinstance(eq, list) else [eq]) if str(x or "").strip()]
    return {"key": str(v["key"]).strip(), "equals": vals} if vals else None


def asked(q: dict, answer: dict) -> bool:
    """Whether this respondent was routed to question `q` (always, unless it has a show_if)."""
    cond = q.get("show_if")
    if not cond:
        return True
    given = (answer or {}).get(cond["key"])
    given = given if isinstance(given, list) else [given]
    return any(str(g) in cond["equals"] for g in given if g is not None)


def validate(spec: dict) -> list[str]:
    qs = normalise(spec.get("questions"))
    errors = []
    if not qs:
        return ["Add at least one question."]
    seen = set()
    for k, q in enumerate(qs, 1):
        if not q["text"]:
            errors.append(f"Question {k} has no text.")
        if q["key"] in seen:
            errors.append(f"Question {k}: key '{q['key']}' is used twice.")
        seen.add(q["key"])
        if q["type"] in ("single", "multi") and len(q["options"]) < 2:
            errors.append(f"Question {k} needs at least two options.")
        if q["type"] == "grid" and (len(q["rows"]) < 1 or len(q["columns"]) < 2):
            errors.append(f"Question {k} (grid) needs at least one row and two columns.")
        if q["type"] == "scale" and q["max"] <= q["min"]:
            errors.append(f"Question {k}: the scale's max must be above its min.")
    return errors


def row_key(q: dict, row: str, idx: int) -> str:
    return _slug(row, f"r{idx + 1}")


def opt_key(idx: int) -> str:
    return f"o{idx + 1}"


def _likely(spec: dict, q: dict) -> bool:
    return q["type"] in ("single", "multi", "yesno", "grid") and (q.get("likelihood") or str(spec.get("answer_mode") or "") == "distribution")


def distribution_mode(spec: dict) -> bool:
    """Answer as likelihoods (2026-10-08): instead of one pick per question the twin gives the
    chance it would pick each option, and the answer it gives is drawn from that. A twin asked for
    a single pick gives its most likely option every time — 97% "hunger and poverty" where real
    people split 20/17/15… — so a population of them is far more unanimous than the public."""
    return str(spec.get("answer_mode") or "") == "distribution" or any(q["likelihood"] for q in normalise(spec.get("questions")))


def _dobj(props: dict, description: str) -> dict:
    return {**obj(props), "description": description}


def _dist_schema(q: dict) -> dict:
    t, text = q["type"], q["text"]
    if t == "multi":
        cap = q["max_choices"]
        return _dobj({opt_key(k): i(f"{o} — chance (0-100) that you would tick this one") for k, o in enumerate(q["options"])},
                   f"{text} — for EACH option, the chance you would tick it (independent chances, not summing to 100)"
                   + (f"; you can tick at most {cap}" if cap else "") + (f"; {' / '.join(q['exclusive'])} only on its own" if q["exclusive"] else ""))
    if t == "grid":
        return obj({row_key(q, r, k): _dobj({opt_key(j): i(f"{c} — chance (0-100)") for j, c in enumerate(q["columns"])}, f"{text} — {r}: chances summing to 100")
                    for k, r in enumerate(q["rows"])})
    opts = q["options"] if t == "single" else ["yes", "no"]
    return _dobj({opt_key(k): i(f"{o} — chance (0-100)") for k, o in enumerate(opts)}, f"{text} — chances summing to 100")


def schema_for(spec: dict) -> dict:
    props: dict[str, Any] = {"reasoning": s("2-3 sentences, in character: how you approached this form and what shaped your answers")}
    for q in normalise(spec.get("questions")):
        if _likely(spec, q):
            props[q["key"]] = _dist_schema(q)
            continue
        t = q["type"]
        text = q["text"]
        if t == "single":
            props[q["key"]] = enum(q["options"] or ["yes", "no"], text)
        elif t == "multi":
            cap = q["max_choices"] or len(q["options"]) or 2
            props[q["key"]] = arr(enum(q["options"] or ["yes", "no"]), f"{text} ({'choose up to ' + str(cap) + ' DIFFERENT options' if q['max_choices'] else 'choose all that apply'}"
                                  + "; list each option at most once, and only as many as are really true of you"
                                  + (f"; {' / '.join(q['exclusive'])} only on its own" if q["exclusive"] else "")
                                  + ("; leave empty if this question was not for you" if q["show_if"] else "") + ")", max_items=cap)
            # A capped list was filled with the same option three times (prod, 2026-10-08): the picks must differ.
            props[q["key"]]["uniqueItems"] = True
        elif t == "scale":
            lo, hi = q["min"], q["max"]
            ends = f" ({lo} = {q['min_label']}, {hi} = {q['max_label']})" if q["min_label"] or q["max_label"] else ""
            props[q["key"]] = i(f"{text} — an integer from {lo} to {hi}{ends}")
        elif t == "yesno":
            props[q["key"]] = enum(["yes", "no"], text)
        elif t == "number":
            props[q["key"]] = n(f"{text} — a number")
        elif t == "text":
            props[q["key"]] = s(f"{text} — in your own words, 1-2 sentences")
        elif t == "grid":
            props[q["key"]] = obj({
                row_key(q, r, k): enum(q["columns"], f"{text} — {r}") for k, r in enumerate(q["rows"])
            })
    return obj(props)


def question_for(spec: dict) -> str:
    """The questionnaire, rendered for the agent so it reads the whole form before answering."""
    lines = []
    title = str(spec.get("title") or "").strip()
    if title:
        lines.append(f"SURVEY: {title}")
    if str(spec.get("context_before") or "").strip():
        lines.append(str(spec["context_before"]).strip())
    for k, q in enumerate(normalise(spec.get("questions")), 1):
        t = q["type"]
        line = f"{k}. {q['text']}"
        if q["show_if"] and not spec.get("_followup_stage"):
            src = next((n for n, x in enumerate(normalise(spec.get("questions")), 1) if x["key"] == q["show_if"]["key"]), None)
            line += f" (ONLY if you answered {' or '.join(chr(34) + e + chr(34) for e in q['show_if']['equals'])} to question {src or q['show_if']['key']}; otherwise leave it empty)"
        if t in ("single", "multi"):
            how = "choose one" if t == "single" else (f"choose up to {q['max_choices']} different options" if q["max_choices"] else "choose all that apply")
            line += f" [{how}: " + " / ".join(q["options"]) + "]"
            if t == "multi" and q["exclusive"]:
                line += f" ({' / '.join(q['exclusive'])}: only on its own)"
        elif t == "scale":
            line += f" [{q['min']}–{q['max']}" + (f", {q['min']} = {q['min_label']}" if q["min_label"] else "") + (f", {q['max']} = {q['max_label']}" if q["max_label"] else "") + "]"
        elif t == "yesno":
            line += " [yes / no]"
        elif t == "number":
            line += " [a number]"
        elif t == "text":
            line += " [in your own words]"
        elif t == "grid":
            line += " [for each of: " + "; ".join(q["rows"]) + " — answer " + " / ".join(q["columns"]) + "]"
        lines.append(line)
    if distribution_mode(spec):
        lines.append(DISTRIBUTION_RULE)
    lines.append("Complete every question as yourself.")
    return "\n".join(lines)


DISTRIBUTION_RULE = """HOW TO ANSWER: for every multiple-choice question and every row of a grid, do not just name one answer — give the CHANCE (0-100) that you would pick each option if you filled this in on an ordinary day, as yourself. Real people are rarely certain: spread your chances where you would genuinely waver (between "somewhat" and "strongly", between two priorities, between an answer and "Don't know"), and put almost all of it on one option only where you would never answer otherwise. "Don't know" gets the chance you would really tick it — for things you have never heard of or never thought about, that chance is high. Chances for one question or row add up to 100; for "tick all that apply / up to N" give each option its own chance of being ticked."""


def _draw(weights: dict[str, float], rng) -> Optional[str]:
    items = [(k, max(0.0, float(v or 0))) for k, v in weights.items()]
    tot = sum(v for _, v in items)
    if tot <= 0:
        return None
    x = rng.random() * tot
    for k, v in items:
        x -= v
        if x <= 0:
            return k
    return items[-1][0]


def realise(answer: dict, spec: dict, rng) -> dict:
    """Turn a likelihood answer into the concrete answer the form would have recorded: one draw
    per question and grid row (seeded), multi choices ticked by their own chances and capped.
    The likelihoods are kept under `_dist` so the spread each twin gave stays inspectable."""
    if not distribution_mode(spec):
        return answer
    out = dict(answer)
    dists: dict[str, Any] = {}
    for q in normalise(spec.get("questions")):
        raw = answer.get(q["key"])
        if not _likely(spec, q) or not isinstance(raw, dict):
            continue
        dists[q["key"]] = raw
        if q["type"] == "grid":
            g = {}
            for k, r in enumerate(q["rows"]):
                rk = row_key(q, r, k)
                cell = raw.get(rk) if isinstance(raw.get(rk), dict) else {}
                pick = _draw({c: cell.get(opt_key(j), 0) for j, c in enumerate(q["columns"])}, rng)
                if pick is not None:
                    g[rk] = pick
            out[q["key"]] = g
        elif q["type"] == "multi":
            p = {o: max(0.0, min(100.0, float(raw.get(opt_key(k)) or 0))) / 100 for k, o in enumerate(q["options"])}
            excl = [o for o in q["exclusive"] if o in p]
            chosen: list[str] = []
            for o in excl:                       # a stand-alone answer is drawn first, and stands alone
                if rng.random() < p[o]:
                    chosen = [o]
                    break
            if not chosen:
                ticked = [o for o, pr in p.items() if o not in excl and rng.random() < pr]
                cap = q["max_choices"] or len(ticked)
                while len(ticked) > cap:         # over the cap: keep a weighted draw of them
                    drop = _draw({o: 1 - p[o] + 1e-6 for o in ticked}, rng)
                    ticked.remove(drop)
                if not ticked and not q["show_if"]:
                    ticked = [max((o for o in p if o not in excl), key=lambda o: p[o])]   # a respondent ticks something
                chosen = ticked
            out[q["key"]] = chosen
        else:
            opts = q["options"] if q["type"] == "single" else ["yes", "no"]
            pick = _draw({o: raw.get(opt_key(k), 0) for k, o in enumerate(opts)}, rng)
            if pick is not None:
                out[q["key"]] = pick
    out["_dist"] = dists
    return out


def stages(spec: dict) -> list[tuple[dict, Optional[dict]]]:
    """Routing asked the way a real form asks it: the routed questions are held back and put
    to the twin in a second call only when its first answers route it there — so "why didn't you
    take it?" cannot pull "have you ever not taken medication?" towards yes (it did: 100% v 25%).
    Returns [(stage spec, condition)], condition None for the first stage."""
    qs = list(spec.get("questions") or [])
    norm = normalise(qs)
    routed = {q["key"] for q in norm if q["show_if"]}
    if not routed:
        return [(spec, None)]
    first = {**spec, "questions": [q for q, n in zip(qs, norm) if n["key"] not in routed]}
    out: list[tuple[dict, Optional[dict]]] = [(first, None)]
    for q, nq in zip(qs, norm):
        if nq["key"] in routed:
            out.append(({**spec, "questions": [q], "_followup_stage": True}, nq))
    return out


def followup_context(spec: dict, cond_q: dict, answer: dict) -> str:
    """The line a follow-up opens with: what the twin just answered to the question routing it."""
    src = next((q for q in normalise(spec.get("questions")) if q["key"] == cond_q["show_if"]["key"]), None)
    if not src:
        return ""
    return f"FOLLOW-UP: earlier in this survey you were asked \"{src['text']}\" and you answered \"{answer.get(src['key'])}\". One more question follows from that."


# ── aggregation ───────────────────────────────────────────────────────────────

def _hist(values: list[float], lo: Optional[int], hi: Optional[int]) -> list[dict]:
    """Integer scale: one bucket per point, in order. Free numbers: up to 8 equal-width bins."""
    if not values:
        return []
    if lo is not None and hi is not None and hi - lo <= 12:
        counts = {v: 0 for v in range(lo, hi + 1)}
        for v in values:
            b = int(round(v))
            if b in counts:
                counts[b] += 1
        return [{"value": str(b), "count": c, **stats.wilson(c, len(values))} for b, c in counts.items()]
    vmin, vmax = min(values), max(values)
    if vmin == vmax:
        return [{"value": f"{vmin:g}", "count": len(values), **stats.wilson(len(values), len(values))}]
    bins = 8
    width = (vmax - vmin) / bins
    counts = [0] * bins
    for v in values:
        b = min(bins - 1, int((v - vmin) / width))
        counts[b] += 1
    return [{"value": f"{vmin + k * width:g}–{vmin + (k + 1) * width:g}", "count": c, **stats.wilson(c, len(values))}
            for k, c in enumerate(counts)]


def _aggregate_question(q: dict, rows: list[dict], seed: int) -> dict:
    t, key = q["type"], q["key"]
    rows = [r for r in rows if asked(q, r.get("answer") or {})]
    answers = [r["answer"].get(key) for r in rows]
    out: dict[str, Any] = {"key": key, "type": t, "text": q["text"], "n": len(rows), "primary": q["primary"]}

    if t in ("single", "yesno"):
        options = q["options"] if t == "single" else ["yes", "no"]
        dist = stats.distribution([str(a) for a in answers if a is not None])
        by = {d["value"]: d for d in dist}
        out["distribution"] = [by.get(o, {"value": o, "count": 0, **stats.wilson(0, len(rows))}) for o in options] + \
                              [d for d in dist if d["value"] not in options]
        top = max(out["distribution"], key=lambda d: d["count"]) if out["distribution"] else None
        # Yes/no leads with "yes" whatever the majority; a choice question leads with its winner.
        lead = out["distribution"][0] if t == "yesno" and out["distribution"] else top
        out["headline"] = {**lead, "label": lead["value"]} if lead else None
        out["sentence"] = f"{stats.pct(lead['share'])} said \"{lead['value']}\" ({lead['count']} of {len(rows)})." if lead else ""
    elif t == "multi":
        n_rows = len(rows)
        answers = [list(dict.fromkeys(a)) if isinstance(a, list) else a for a in answers]   # a repeated pick counts once
        out["distribution"] = []
        for o in q["options"]:
            c = sum(1 for a in answers if isinstance(a, list) and o in a)
            out["distribution"].append({"value": o, "count": c, **stats.wilson(c, n_rows)})
        out["distribution"].sort(key=lambda d: -d["count"])
        out["mean_selected"] = round(sum(len(a) for a in answers if isinstance(a, list)) / max(1, n_rows), 2)
        top = out["distribution"][0] if out["distribution"] else None
        out["headline"] = {**top, "label": top["value"]} if top else None
        out["sentence"] = f"\"{top['value']}\" was picked most, by {stats.pct(top['share'])}; people picked {out['mean_selected']} options on average." if top else ""
    elif t in ("scale", "number"):
        vals = []
        for a in answers:
            try:
                vals.append(float(a))
            except (TypeError, ValueError):
                pass
        m = stats.mean_ci(vals, seed=seed)
        out["mean"] = m
        lo, hi = (q["min"], q["max"]) if t == "scale" else (None, None)
        out["distribution"] = _hist(vals, lo, hi)
        if t == "scale":
            top2 = sum(1 for v in vals if v >= hi - 1)
            bottom2 = sum(1 for v in vals if v <= lo + 1)
            out["top_two_box"] = stats.wilson(top2, len(vals))
            out["bottom_two_box"] = stats.wilson(bottom2, len(vals))
            out["sentence"] = (f"Mean {m['mean']:g} of {hi} (95% CI {m['low']:g}–{m['high']:g}); "
                               f"{stats.pct(out['top_two_box']['share'])} in the top two, {stats.pct(out['bottom_two_box']['share'])} in the bottom two.")
        else:
            out["sentence"] = f"Mean {m['mean']:g} (95% CI {m['low']:g}–{m['high']:g}), median {m['median']:g}."
    elif t == "text":
        tk = theme_key_for(key)
        themed = [r["answer"].get(tk) for r in rows if r["answer"].get(tk)]
        out["themes"] = stats.distribution(themed) if themed else []
        out["themes_coded"] = bool(themed)
        out["responses"] = [{
            "agent_id": r["agent_id"], "name": r["agent"].get("name", ""), "role": r["agent"].get("role", ""),
            "text": str(r["answer"].get(key) or ""), "theme": r["answer"].get(tk, ""),
        } for r in rows if str(r["answer"].get(key) or "").strip()]
        top = out["themes"][0] if out["themes"] else None
        out["sentence"] = f"{len(out['responses'])} answered; the most common theme is \"{top['value']}\" ({stats.pct(top['share'])})." if top else f"{len(out['responses'])} answered in their own words."
    elif t == "grid":
        out["columns"] = q["columns"]
        out["rows"] = []
        for k, r_label in enumerate(q["rows"]):
            rk = row_key(q, r_label, k)
            picks = [str((a or {}).get(rk)) for a in answers if isinstance(a, dict) and (a or {}).get(rk) is not None]
            dist = stats.distribution(picks)
            by = {d["value"]: d for d in dist}
            out["rows"].append({
                "key": rk, "label": r_label,
                "distribution": [by.get(c, {"value": c, "count": 0, **stats.wilson(0, len(picks))}) for c in q["columns"]],
                "n": len(picks),
            })
        # Top-box per row = share choosing the first column (the builder puts the strongest
        # agreement first); the sentence names the row with the most of it.
        best = max(out["rows"], key=lambda r: r["distribution"][0]["share"] if r["distribution"] else 0) if out["rows"] else None
        out["sentence"] = f"\"{best['label']}\" draws the most \"{q['columns'][0]}\" ({stats.pct(best['distribution'][0]['share'])})." if best and q["columns"] else ""
    return out


def aggregate(rows: list[dict], spec: dict) -> dict:
    if not rows:
        return {"n": 0, "sentence": "No responses yet."}
    seed = int(spec.get("seed") or 0)
    qs = normalise(spec.get("questions"))
    questions = [_aggregate_question(q, rows, seed) for q in qs]

    primary = next((q for q in questions if q["primary"]), questions[0] if questions else None)
    headline = None
    segments: dict = {}
    if primary:
        pq = next(q for q in qs if q["key"] == primary["key"])
        if primary["type"] in ("single", "yesno", "multi") and primary.get("headline"):
            want = primary["headline"]["value"]
            headline = {"metric": primary["key"], "label": f"{primary['text']} — {want}", **{k: primary["headline"][k] for k in ("share", "low", "high", "n", "successes")}}
            def _share(rs, key=pq["key"], want=want, multi=(primary["type"] == "multi")):
                vals = [r["answer"].get(key) for r in rs]
                return stats.share_of(vals, (lambda v: isinstance(v, list) and want in v) if multi else (lambda v: str(v) == want))
            segments = {k: stats.segment(rows, k, _share) for k in split_keys(rows)}
            segments = {k: v for k, v in segments.items() if v}
        elif primary["type"] in ("scale", "number") and primary.get("mean"):
            headline = {"metric": primary["key"], "label": primary["text"], "mean": primary["mean"]}

    sentence = f"{len(rows)} responses. " + (primary["sentence"] if primary else "")
    return {
        "n": len(rows),
        "title": str(spec.get("title") or "").strip(),
        "sentence": sentence.strip(),
        "headline": headline,
        "primary": primary["key"] if primary else None,
        "questions": questions,
        "segments": segments,
    }


async def postprocess(probe_ids: list[str], model: str) -> None:
    """Theme-code every open-text question, all probes together."""
    from app.core.database import AsyncSessionLocal
    from app.models.measurement import Probe
    async with AsyncSessionLocal() as db:
        p = await db.get(Probe, probe_ids[0]) if probe_ids else None
        spec = dict(p.spec or {}) if p else {}
    fields = [q["key"] for q in normalise(spec.get("questions")) if q["type"] == "text"]
    if fields:
        await apply_themes(probe_ids, model=model, fields=fields)


# ── templates ─────────────────────────────────────────────────────────────────

TEMPLATES = [
    {
        "key": "reaction", "label": "Reaction",
        "description": "Does it work for them, how strongly, how it feels, and why. (The former Ask tool.)",
        "title": "Your reaction",
        "questions": [
            {"key": "verdict", "type": "single", "text": "Does this work for you? Would you go along with it?", "options": ["yes", "no", "mixed"], "primary": True},
            {"key": "strength", "type": "scale", "text": "How strongly do you hold that view?", "min": 0, "max": 10, "min_label": "barely", "max_label": "certain"},
            {"key": "feeling", "type": "scale", "text": "How does it make you feel?", "min": 1, "max": 7, "min_label": "hostile", "max_label": "delighted"},
            {"key": "why", "type": "text", "text": "What is the one thing that decided it for you?"},
        ],
    },
    {
        "key": "email", "label": "Email test",
        "description": "Open it, read it, act on it — and what put them off.",
        "title": "About this email",
        "questions": [
            {"key": "open", "type": "yesno", "text": "Seeing only the subject line in your inbox, would you open this?", "primary": True},
            {"key": "read", "type": "single", "text": "Having opened it, how far would you read?", "options": ["all of it", "the first few lines", "I'd skim", "I'd close it"]},
            {"key": "act", "type": "yesno", "text": "Would you do what it asks?"},
            {"key": "tone", "type": "grid", "text": "How does it come across?", "rows": ["Clear", "Believable", "Relevant to me", "Pushy"], "columns": ["strongly agree", "agree", "neutral", "disagree", "strongly disagree"]},
            {"key": "why", "type": "text", "text": "What would make you more likely to act on it?"},
        ],
    },
    {
        "key": "concept", "label": "Concept test",
        "description": "Appeal, uniqueness, believability, need, intent.",
        "title": "About this idea",
        "questions": [
            {"key": "appeal", "type": "scale", "text": "How appealing is this to you?", "min": 1, "max": 5, "min_label": "not at all", "max_label": "extremely", "primary": True},
            {"key": "unique", "type": "scale", "text": "How different is it from what you can already get?", "min": 1, "max": 5, "min_label": "nothing new", "max_label": "very different"},
            {"key": "believe", "type": "scale", "text": "How believable is it?", "min": 1, "max": 5, "min_label": "not at all", "max_label": "completely"},
            {"key": "need", "type": "single", "text": "Does it solve a problem you actually have?", "options": ["yes, a real one", "a minor one", "not really", "no"]},
            {"key": "intent", "type": "single", "text": "Would you try it?", "options": ["definitely", "probably", "not sure", "probably not", "definitely not"]},
            {"key": "improve", "type": "text", "text": "What would you change about it?"},
        ],
    },
    {
        "key": "nps", "label": "NPS + why",
        "description": "The recommend question, and the reason behind the number.",
        "title": "Recommend?",
        "questions": [
            {"key": "nps", "type": "scale", "text": "How likely are you to recommend this to a friend or colleague?", "min": 0, "max": 10, "min_label": "not at all", "max_label": "extremely", "primary": True},
            {"key": "why", "type": "text", "text": "What is the main reason for your score?"},
        ],
    },
    {
        "key": "consequences", "label": "Consequences",
        "description": "What would happen, for whom, and how they would respond.",
        "title": "If this went ahead",
        "questions": [
            {"key": "effect", "type": "single", "text": "Overall, what would this mean for you?", "options": ["clearly better off", "slightly better off", "no real change", "slightly worse off", "clearly worse off"], "primary": True},
            {"key": "who", "type": "multi", "text": "Who around you would feel it most?", "options": ["me", "my household", "my neighbours", "my workplace", "people on low incomes", "older people", "young families", "nobody much"]},
            {"key": "respond", "type": "text", "text": "What would you actually do differently if it happened?"},
            {"key": "worry", "type": "text", "text": "What is your biggest worry about it, if any?"},
        ],
    },
]


INPUTS = (
    InputField(key="title", type="text", label="Survey title", placeholder="Your reaction to the new plan"),
    InputField(
        key="intro", type="textarea", label="What they see first (optional)",
        help="Material shown before the questions — the email, the proposal, the poster copy.",
        placeholder="Paste the material, or leave blank to survey them about the session topic.",
        default_from="session_query",
    ),
    InputField(key="questions", type="questions", label="Questions", required=True,
               help="Single or multiple choice, scales, yes/no, numbers, open text and grids."),
)


class SurveyInstrument(Instrument):
    def schema_for(self, spec: dict) -> dict:  # type: ignore[override]
        return schema_for(spec)

    def question_for(self, spec: dict) -> str:  # type: ignore[override]
        return question_for(spec)

    def validate(self, spec: dict) -> list[str]:  # type: ignore[override]
        return validate(spec)

    def stages(self, spec: dict):
        return stages(spec)

    def realise(self, answer: dict, spec: dict, rng) -> dict:
        return realise(answer, spec, rng)

    def followup_context(self, spec: dict, cond_q: dict, answer: dict) -> str:
        return followup_context(spec, cond_q, answer)


INSTRUMENT = register(SurveyInstrument(
    key="survey",
    label="Forms",
    description="A questionnaire every persona fills in. Upload one you have, have it written from what the session knows, or brainstorm it in chat. Results per question, and every individual response.",
    answer_schema=schema_for({"questions": [{"key": "q1", "type": "yesno", "text": "Example"}]}),
    question="Complete every question as yourself.",
    directive=DIRECTIVE,
    aggregate=aggregate,
    inputs=INPUTS,
    kpis=(Kpi("n", "Responses", "count", "How many personas completed the form."),),
    page="survey",
    form="survey",
    max_tokens=7000,
    version=1,
    stimulus_key="intro",
    postprocess=postprocess,
))
