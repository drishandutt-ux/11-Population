"""Benchmarks: a real poll's published results, and the score of a simulated run against them.

A benchmark is built once from the pollster's crosstab workbook (`crosstab.parse_workbook`) and
a question map that ties each questionnaire item to the sheet holding its results. The same
map writes the Forms questionnaire, using the workbook's own option labels, so the agents
answer exactly the options the real respondents saw and every share lines up by name.

Scoring compares like with like:
  - the simulated shares are computed the way the pollster computed theirs (single choice:
    share of the base; multi choice: share ticking each option; grid: per row), on the same
    base (routed questions only count the respondents routed to them), weighted by each
    agent's weight;
  - the pollster's roll-up rows (Net, Trust, Agree…) are left out, so nothing counts twice;
  - every cut the benchmark has and the population carries is scored: total, segment,
    generation, gender, region, 2019 vote.
Two baselines say whether a score is any good: "uniform" (every option equally likely) and,
for a segment cut, "national" (every segment answers like the country). A simulation that
cannot beat the national baseline on segments has not captured how the segments differ."""
from __future__ import annotations

import json
import math
import os
from typing import Any, Iterable, Optional

from app.services.kits import crosstab

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "kits", "benchmarks")

# Generation bands as the workbook defines them (ages in years).
GENERATIONS = [("Gen Z (18-24)", 18, 24), ("Millennials (25-40)", 25, 40), ("Gen X (41-55)", 41, 55),
               ("Baby Boomers (56-74)", 56, 74), ("Silent Gen (75+)", 75, 120)]


# ── building a benchmark ──────────────────────────────────────────────────────

def build(xlsx_path: str, qmap: list[dict], meta: dict) -> tuple[dict, dict]:
    """(benchmark, form) from the workbook and the question map."""
    parsed = crosstab.parse_workbook(xlsx_path)
    sheets = {s["sheet"]: s for s in parsed["sheets"]}
    questions, form_qs = [], []
    for q in qmap:
        if meta.get("likelihood") and q.get("type") != "text":
            q = {**q, "likelihood": True}
        if q.get("type") == "text":
            sh = sheets.get(q.get("sheet") or "")
            questions.append({**_public(q), "verbatims": (sh or {}).get("verbatims") or []})
            form_qs.append(_form_q(q, options=[], rows=[], columns=[]))
            continue
        sh = sheets[q["sheet"]]
        tables = sh["tables"]
        if q["type"] == "grid":
            cols = [r["label"] for r in tables[0]["rows"] if not r["derived"]]
            rows = [t["item"] or t["label"] for t in tables]
            questions.append({**_public(q), "rows": rows, "options": cols, "tables": tables})
            form_qs.append(_form_q(q, options=[], rows=rows, columns=cols))
        else:
            t = tables[0]
            opts = [r["label"] for r in t["rows"] if not r["derived"]]
            entry = {**_public(q), "options": opts, "tables": [t]}
            if q.get("verbatim_sheet") and q["verbatim_sheet"] in sheets:
                entry["verbatims"] = sheets[q["verbatim_sheet"]]["verbatims"]
            questions.append(entry)
            form_qs.append(_form_q(q, options=opts, rows=[], columns=[]))
    first = next(s for s in parsed["sheets"] if s["tables"])["tables"][0]
    cols = [{"key": c["key"], "group": c["group"], "label": c["label"],
             "weighted_n": (first.get("weighted_n") or {}).get(c["key"]), "unweighted_n": (first.get("unweighted_n") or {}).get(c["key"])}
            for c in first["columns"]]
    for q in questions:
        for t in q.get("tables") or []:
            _compact_table(t)
        for v in q.get("verbatims") or []:
            v["columns"] = [c for c in v.get("columns") or [] if c.split(":", 1)[0] in ("Segment", "Age by generation", "Gender")]
            v["share"] = round(v["share"], 5) if isinstance(v.get("share"), float) else v.get("share")
    # Methodology lines only: contact details (a named person's email) stay out of the product.
    method = {k: v for k, v in parsed["method"].items() if "enquir" not in k.lower() and "@" not in v}
    bench = {**meta, "method": method, "columns": cols, "questions": questions}
    form = {"title": meta.get("form_title") or meta.get("title") or "Survey", "intro": meta.get("form_intro") or "", "questions": form_qs}
    return bench, form


def _compact_table(t: dict) -> None:
    """Shares to 4 decimals and bases to whole numbers; the column list lives once, on the benchmark."""
    t.pop("columns", None)
    for r in t.get("rows") or []:
        r["values"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r["values"].items()}
    for b in ("weighted_n", "unweighted_n"):
        if isinstance(t.get(b), dict):
            t[b] = {k: (round(v) if isinstance(v, float) else v) for k, v in t[b].items()}


def _public(q: dict) -> dict:
    return {k: q[k] for k in ("key", "number", "type", "text", "sheet", "max_choices", "exclusive", "show_if", "note") if k in q}


def _form_q(q: dict, *, options: list[str], rows: list[str], columns: list[str]) -> dict:
    out: dict[str, Any] = {"key": q["key"], "type": q["type"], "text": q["text"]}
    if options:
        out["options"] = options
    if rows:
        out["rows"], out["columns"] = rows, columns
    for k in ("max_choices", "exclusive", "show_if", "likelihood"):
        if q.get(k):
            out[k] = q[k]
    return out


def load(benchmark_id: str) -> Optional[dict]:
    path = os.path.join(DATA_DIR, benchmark_id, "benchmark.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def load_form(benchmark_id: str) -> Optional[dict]:
    path = os.path.join(DATA_DIR, benchmark_id, "form.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def list_benchmarks() -> list[dict]:
    out = []
    if not os.path.isdir(DATA_DIR):
        return out
    for name in sorted(os.listdir(DATA_DIR)):
        b = load(name)
        if b:
            out.append({"id": name, "title": b.get("title"), "fieldwork": (b.get("method") or {}).get("Fieldwork dates"),
                        "sample": (b.get("method") or {}).get("Sample size"), "segmentation": b.get("segmentation"),
                        "kit": b.get("kit"), "questions": len(b.get("questions") or [])})
    return out


# ── the respondents' cuts ─────────────────────────────────────────────────────

def generation_for(age: Any) -> Optional[str]:
    try:
        a = int(age)
    except (TypeError, ValueError):
        return None
    for label, lo, hi in GENERATIONS:
        if lo <= a <= hi:
            return label
    return None


def cuts_for(resp: dict) -> dict[str, str]:
    """{benchmark column key: True-ish} for one respondent: which banner columns they fall in."""
    demo = resp.get("demographics") or {}
    frame = demo.get("frame") or {}
    keys = {"All": "All"}
    if resp.get("segment"):
        keys["Segment"] = f"Segment: {resp['segment']}"
    g = generation_for(resp.get("age"))
    if g:
        keys["Age by generation"] = f"Age by generation: {g}"
    gender = str(demo.get("gender") or "").strip().lower()
    if gender in ("male", "female", "man", "woman"):
        keys["Gender"] = "Gender: " + ("Male" if gender in ("male", "man") else "Female")
    region = frame.get("region") or demo.get("poll_region")
    if region:
        keys["Region"] = f"Region: {region}"
    vote = frame.get("ge2019") or demo.get("ge2019")
    if vote in ("Conservative", "Labour", "Liberal Democrat"):
        keys["GE 2019"] = f"GE 2019: {vote}"
    return keys


# ── simulated shares, computed the pollster's way ─────────────────────────────

def _asked(q: dict, answer: dict) -> bool:
    cond = q.get("show_if")
    if not cond:
        return True
    given = answer.get(cond["key"])
    given = given if isinstance(given, list) else [given]
    eq = cond["equals"] if isinstance(cond["equals"], list) else [cond["equals"]]
    return any(str(x) in [str(e) for e in eq] for x in given if x is not None)


def _row_slug(row: str, idx: int) -> str:
    from app.services.measurement.instruments.survey import _slug
    return _slug(row, f"r{idx + 1}")


def _ok(i: int) -> str:
    return f"o{i + 1}"


def _likelihoods(q: dict, ans: dict) -> Optional[Any]:
    """This respondent's stated chances for question q, normalised the way the form means them:
    a single question or grid row → a distribution over its options; a multi question → each
    option's chance of being ticked, the stand-alone options taken first and the rest scaled so
    the expected ticks respect the cap. None when the twin answered with a plain pick."""
    raw = ((ans or {}).get("_dist") or {}).get(q["key"])
    if not isinstance(raw, dict):
        return None

    def dist(d: dict, opts: list[str]) -> Optional[dict]:
        vals = [max(0.0, float((d or {}).get(_ok(k)) or 0)) for k in range(len(opts))]
        tot = sum(vals)
        return {o: v / tot for o, v in zip(opts, vals)} if tot > 0 else None

    if q["type"] == "grid":
        from app.services.measurement.instruments.survey import _slug
        return {row: dist(raw.get(_slug(row, f"r{k + 1}")) or {}, q["options"]) for k, row in enumerate(q["rows"])}
    if q["type"] == "multi":
        p = {o: max(0.0, min(1.0, float(raw.get(_ok(k)) or 0) / 100)) for k, o in enumerate(q["options"])}
        excl = [o for o in (q.get("exclusive") or []) if o in p]
        p_ex = min(1.0, sum(p[o] for o in excl))
        rest = {o: v for o, v in p.items() if o not in excl}
        cap = q.get("max_choices") or 0
        tot = sum(rest.values())
        scale = (1 - p_ex) * (min(1.0, cap / tot) if cap and tot > cap else 1.0)
        out = {o: v * scale for o, v in rest.items()}
        out.update({o: p[o] for o in excl})
        return out
    return dist(raw, q["options"])


def simulated(q: dict, responses: list[dict], column: str, *, estimator: str = "draws") -> dict:
    """{'n': weighted base, 'count': respondents, 'shares': {...}} or, for a grid, per row.

    estimator "likelihood": where a twin gave chances (likelihood answers) its share of each
    option is its chance, not its one draw — the same twin asked a thousand times. Far less
    noise per segment at the same number of twins; twins that gave a plain pick count as 0/1."""
    group = column.split(":", 1)[0] if ":" in column else "All"
    pool = [r for r in responses if cuts_for(r).get(group) == column and _asked(q, r.get("answer") or {})]
    wsum = sum(float(r.get("weight") or 1.0) for r in pool)
    if estimator == "likelihood" and any(_likelihoods(q, r.get("answer") or {}) is not None for r in pool):
        return _expected(q, pool, wsum)

    def share(pred) -> Optional[float]:
        if wsum <= 0:
            return None
        return sum(float(r.get("weight") or 1.0) for r in pool if pred(r.get("answer") or {})) / wsum

    if q["type"] == "grid":
        rows = {}
        for k, row in enumerate(q["rows"]):
            rk = _row_slug(row, k)
            answered = [r for r in pool if isinstance((r.get("answer") or {}).get(q["key"]), dict) and r["answer"][q["key"]].get(rk) is not None]
            w = sum(float(r.get("weight") or 1.0) for r in answered)
            rows[row] = {o: (sum(float(r.get("weight") or 1.0) for r in answered if str(r["answer"][q["key"]].get(rk)) == o) / w if w else None)
                         for o in q["options"]}
        return {"n": round(wsum, 2), "count": len(pool), "rows": rows}
    if q["type"] == "multi":
        shares = {o: share(lambda a, o=o: isinstance(a.get(q["key"]), list) and o in a[q["key"]]) for o in q["options"]}
    else:
        shares = {o: share(lambda a, o=o: str(a.get(q["key"])) == o) for o in q["options"]}
    return {"n": round(wsum, 2), "count": len(pool), "shares": shares}


def _expected(q: dict, pool: list[dict], wsum: float) -> dict:
    """Weighted mean of the twins' stated chances (or of their picks where no chances were given)."""
    from app.services.measurement.instruments.survey import _slug
    if q["type"] == "grid":
        rows = {}
        for k, row in enumerate(q["rows"]):
            acc = {o: 0.0 for o in q["options"]}
            w_tot = 0.0
            for r in pool:
                w = float(r.get("weight") or 1.0)
                lk = _likelihoods(q, r.get("answer") or {})
                d = (lk or {}).get(row) if lk else None
                if d is None:
                    pick = ((r.get("answer") or {}).get(q["key"]) or {}).get(_slug(row, f"r{k + 1}")) if isinstance((r.get("answer") or {}).get(q["key"]), dict) else None
                    if pick is None:
                        continue
                    d = {o: 1.0 if o == str(pick) else 0.0 for o in q["options"]}
                for o in acc:
                    acc[o] += w * d.get(o, 0.0)
                w_tot += w
            rows[row] = {o: (v / w_tot if w_tot else None) for o, v in acc.items()}
        return {"n": round(wsum, 2), "count": len(pool), "rows": rows}
    acc = {o: 0.0 for o in q["options"]}
    for r in pool:
        w = float(r.get("weight") or 1.0)
        d = _likelihoods(q, r.get("answer") or {})
        if d is None:
            a = (r.get("answer") or {}).get(q["key"])
            d = {o: 1.0 if (o in a if isinstance(a, list) else str(a) == o) else 0.0 for o in q["options"]}
        for o in acc:
            acc[o] += w * d.get(o, 0.0)
    return {"n": round(wsum, 2), "count": len(pool), "shares": {o: (v / wsum if wsum else None) for o, v in acc.items()}}


def real(q: dict, column: str) -> dict:
    if q["type"] == "grid":
        return {"rows": {(t["item"] or t["label"]): crosstab.table_shares(t, column) for t in q["tables"]},
                "n": (q["tables"][0].get("weighted_n") or {}).get(column)}
    t = q["tables"][0]
    return {"shares": crosstab.table_shares(t, column), "n": (t.get("weighted_n") or {}).get(column)}


# ── comparison ────────────────────────────────────────────────────────────────

def _compare(sim: dict[str, Optional[float]], obs: dict[str, Optional[float]], kind: str) -> Optional[dict]:
    opts = [o for o in obs if obs.get(o) is not None and sim.get(o) is not None]
    if not opts:
        return None
    errs = [(sim[o] - obs[o]) * 100 for o in opts]
    mae = sum(abs(e) for e in errs) / len(errs)
    out = {"mae_pts": round(mae, 1), "max_err_pts": round(max(abs(e) for e in errs), 1),
           "options": [{"option": o, "real_pct": round(obs[o] * 100, 1), "sim_pct": round(sim[o] * 100, 1), "diff_pts": round((sim[o] - obs[o]) * 100, 1)} for o in opts]}
    if kind != "multi":
        # Same winner? (single choice and grid rows: the option most people picked)
        out["top_match"] = max(opts, key=lambda o: obs[o]) == max(opts, key=lambda o: sim[o])
        # Total variation distance: half the summed absolute gaps, 0 = identical distributions.
        out["tvd_pts"] = round(sum(abs(e) for e in errs) / 2, 1)
    out["rank_corr"] = _spearman([obs[o] for o in opts], [sim[o] for o in opts])
    return out


def _uniform_mae(obs: dict[str, Optional[float]], kind: str, max_choices: int = 0) -> Optional[float]:
    opts = [o for o in obs if obs.get(o) is not None]
    if not opts:
        return None
    if kind == "multi":
        guess = min(1.0, (max_choices or 1) / len(opts))
    else:
        guess = 1.0 / len(opts)
    return round(sum(abs(guess - obs[o]) for o in opts) / len(opts) * 100, 1)


def _spearman(a: list[float], b: list[float]) -> Optional[float]:
    if len(a) < 3:
        return None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda k: v[k])
        r = [0.0] * len(v)
        k = 0
        while k < len(order):
            j = k
            while j + 1 < len(order) and v[order[j + 1]] == v[order[k]]:
                j += 1
            for m in range(k, j + 1):
                r[order[m]] = (k + j) / 2
            k = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va, vb = math.sqrt(sum((x - ma) ** 2 for x in ra)), math.sqrt(sum((y - mb) ** 2 for y in rb))
    return round(cov / (va * vb), 2) if va and vb else None


def _units(q: dict, column: str, responses: list[dict], estimator: str = "draws") -> list[dict]:
    """One scored unit per question (or per grid row) for one banner column."""
    sim, obs = simulated(q, responses, column, estimator=estimator), real(q, column)
    if q["type"] == "grid":
        out = []
        for row in q["rows"]:
            c = _compare(sim["rows"].get(row) or {}, obs["rows"].get(row) or {}, "grid")
            if c:
                out.append({"question": q["key"], "row": row, **c, "uniform_mae_pts": _uniform_mae(obs["rows"].get(row) or {}, "grid")})
        return [dict(u, sim_n=sim["count"], real_n=obs["n"]) for u in out]
    c = _compare(sim["shares"], obs["shares"], q["type"])
    if not c:
        return []
    return [{"question": q["key"], **c, "uniform_mae_pts": _uniform_mae(obs["shares"], q["type"], q.get("max_choices") or 0),
             "sim_n": sim["count"], "real_n": obs["n"]}]


def score(bench: dict, responses: list[dict], *, min_n: int = 5, estimator: str = "auto") -> dict:
    """The whole scorecard. `responses`: [{answer, segment, age, demographics, weight}].
    estimator: "draws" (each twin's recorded answer), "likelihood" (each twin's stated chances),
    or "auto" — likelihood whenever the run recorded chances."""
    if estimator == "auto":
        estimator = "likelihood" if any((r.get("answer") or {}).get("_dist") for r in responses) else "draws"
    scored_qs = [q for q in bench["questions"] if q["type"] != "text"]
    columns = [c["key"] for c in bench["columns"]]
    present = {cuts_for(r).get(c.split(":", 1)[0] if ":" in c else "All") for r in responses for c in columns}
    by_column: dict[str, dict] = {}
    for col in columns:
        if col not in present:
            continue
        units = [u for q in scored_qs for u in _units(q, col, responses, estimator)]
        units = [u for u in units if (u.get("sim_n") or 0) >= min_n]
        if not units:
            continue
        by_column[col] = _summarise(units)
        by_column[col]["respondents"] = max(u.get("sim_n") or 0 for u in units)
        by_column[col]["units"] = units
    # National baseline for each segment: predict the segment with the national total.
    seg_cols = [c for c in by_column if c.startswith("Segment:")]
    for col in seg_cols:
        base = []
        for q in scored_qs:
            obs_seg, obs_all = real(q, col), real(q, "All")
            if q["type"] == "grid":
                for row in q["rows"]:
                    c = _compare(obs_all["rows"].get(row) or {}, obs_seg["rows"].get(row) or {}, "grid")
                    if c:
                        base.append(c["mae_pts"])
            else:
                c = _compare(obs_all["shares"], obs_seg["shares"], q["type"])
                if c:
                    base.append(c["mae_pts"])
        by_column[col]["national_baseline_mae_pts"] = round(sum(base) / len(base), 1) if base else None
    per_question = []
    total = by_column.get("All", {}).get("units") or []
    for q in scored_qs:
        us = [u for u in total if u["question"] == q["key"]]
        if us:
            per_question.append({"question": q["key"], "number": q.get("number"), "text": q["text"], "type": q["type"], **_summarise(us)})
    segment_gradient = _segment_gradients(bench, responses, seg_cols, estimator)
    return {
        "benchmark": bench.get("id"), "title": bench.get("title"), "estimator": estimator,
        "respondents": len(responses),
        "headline": {k: v for k, v in by_column.get("All", {}).items() if k != "units"},
        "per_question": per_question,
        "by_column": {k: {kk: vv for kk, vv in v.items() if kk != "units"} for k, v in by_column.items()},
        "segment_gradients": segment_gradient,
        "units": by_column.get("All", {}).get("units") or [],
        "segment_units": {k: v["units"] for k, v in by_column.items() if k.startswith("Segment:")},
    }


def _summarise(units: list[dict]) -> dict:
    maes = [u["mae_pts"] for u in units]
    uni = [u["uniform_mae_pts"] for u in units if u.get("uniform_mae_pts") is not None]
    tops = [u["top_match"] for u in units if "top_match" in u]
    rc = [u["rank_corr"] for u in units if u.get("rank_corr") is not None]
    return {
        "items": len(units),
        "mae_pts": round(sum(maes) / len(maes), 1),
        "median_mae_pts": round(sorted(maes)[len(maes) // 2], 1),
        "uniform_baseline_mae_pts": round(sum(uni) / len(uni), 1) if uni else None,
        "top_choice_agreement": round(sum(1 for t in tops if t) / len(tops), 2) if tops else None,
        "mean_rank_corr": round(sum(rc) / len(rc), 2) if rc else None,
        "within_5_pts": round(sum(1 for m in maes if m <= 5) / len(maes), 2),
    }


def _segment_gradients(bench: dict, responses: list[dict], seg_cols: list[str], estimator: str = "draws") -> list[dict]:
    """Does the simulation order the segments the way the poll does? For each option, the
    correlation across segments between real and simulated shares — the left/right and
    young/old gradients the deck draws its headlines from."""
    if len(seg_cols) < 3:
        return []
    out = []
    for q in bench["questions"]:
        if q["type"] in ("text", "grid"):
            continue
        for o in q["options"]:
            obs = [real(q, c)["shares"].get(o) for c in seg_cols]
            sim = [simulated(q, responses, c, estimator=estimator)["shares"].get(o) for c in seg_cols]
            if any(v is None for v in obs + sim):
                continue
            spread = (max(obs) - min(obs)) * 100
            if spread < 8:      # only where the poll found a real difference between segments
                continue
            out.append({"question": q["key"], "option": o, "real_spread_pts": round(spread, 1),
                        "corr": _pearson(obs, sim), "real": {c.split(': ', 1)[1]: round(v * 100, 1) for c, v in zip(seg_cols, obs)},
                        "sim": {c.split(': ', 1)[1]: round(v * 100, 1) for c, v in zip(seg_cols, sim)}})
    return sorted(out, key=lambda x: -x["real_spread_pts"])


def _pearson(a: list[float], b: list[float]) -> Optional[float]:
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va, vb = math.sqrt(sum((x - ma) ** 2 for x in a)), math.sqrt(sum((y - mb) ** 2 for y in b))
    return round(cov / (va * vb), 2) if va and vb else None


# ── reading a run back in ─────────────────────────────────────────────────────

def responses_from_csv(rows: Iterable[dict], form: dict) -> list[dict]:
    """The probe export (export.csv) → scorer responses. Multi and grid cells are JSON."""
    keys = [q["key"] for q in form.get("questions") or []]
    out = []
    for r in rows:
        ans = {}
        for k in keys:
            v = r.get(k)
            if v in (None, ""):
                continue
            if isinstance(v, str) and v[:1] in "[{":
                try:
                    v = json.loads(v)
                except ValueError:
                    import ast
                    try:
                        v = ast.literal_eval(v)
                    except (ValueError, SyntaxError):
                        pass
            ans[k] = v
        demo = {"gender": r.get("gender") or "", "frame": {k: r[k] for k in ("region", "ge2019") if r.get(k)}}
        try:
            weight = float(r.get("weight") or 1.0)
        except ValueError:
            weight = 1.0
        out.append({"answer": ans, "segment": r.get("segment") or "", "age": r.get("age"), "demographics": demo, "weight": weight})
    return out


def match(spec: dict) -> Optional[str]:
    """The benchmark a Forms run reproduces: the one whose questionnaire keys the run's form carries."""
    keys = {str(q.get("key")) for q in (spec or {}).get("questions") or [] if isinstance(q, dict)}
    if spec and spec.get("benchmark_id") and load(spec["benchmark_id"]):
        return spec["benchmark_id"]
    for b in list_benchmarks():
        form = load_form(b["id"]) or {}
        want = {q["key"] for q in form.get("questions") or []}
        if want and len(want & keys) >= 0.8 * len(want):
            return b["id"]
    return None
