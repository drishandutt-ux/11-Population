"""SimBench, the grouped split (arXiv 2510.17516) — scoring our twins on a public test (2026-10-27).

SimBenchGrouped holds 6,343 cases from five survey datasets (ESS, Afrobarometer, Latinobarómetro,
ISSP, OpinionQA). Each case is a demographic subgroup ("The year is 2016. You are from Poland.
You are female."), one question, its options, and the real answer distribution of that subgroup.
The test: produce the subgroup's distribution; the score per case is

    S = 100 × (1 − TVD(human, ours) / mean TVD(human, uniform) over the case's dataset)

— exactly `calculate_simbench_score.py` in the authors' repo (pitehu/SimBench_release): TVD is half
the summed absolute gap, the denominator is the dataset's mean distance between its human answers
and a uniform guess, and a model's score is the plain mean of S over cases. 100 is perfect, 0 is
guessing uniform. Published top (both splits averaged): Claude 3.7 Sonnet 40.8.

What we enter. For each subgroup a lineup of twins is written by the product's own persona writer
(the Studio's plan path, one segment = the subgroup), kept in a session of kind "benchmark". Each
case is put to that lineup through Forms as a single likelihood question (every twin gives its
chances per option); the lineup's distribution is the mean of those chances ("likelihood") and,
beside it, the share of realised picks ("draws"). Alongside, the *bare model* answers the same case
with the benchmark's own verbalised prompt (system = the group prompt, user = the question + the
percentage JSON instruction), on the same model version — the comparison a client can check.

The subset. The whole split needs ~2,300 lineups; the first reading runs on a stratified
1,000-case subset (`subset.json`, committed, ids only): strata are dataset × grouping variables,
each with its share of the split's cases, filled with whole subgroups so a lineup serves every
case of its subgroup. The data itself (CC BY-NC-SA) is fetched from Hugging Face at run time into
`cache/` and checked against the sha256 the subset was cut from.

Entry points: `build_subset` (CLI: python -m app.services.kits.simbench subset), `start`/`resume`/
`stop` (the admin API), `summarise`."""
from __future__ import annotations

import ast
import asyncio
import csv
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import traceback
import urllib.request
import uuid
from datetime import datetime
from typing import Any, Optional

BENCHMARK_ID = "simbench_grouped"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "kits", "benchmarks", BENCHMARK_ID)
CACHE_DIR = os.path.join(DATA_DIR, "cache")
SUBSET_PATH = os.path.join(DATA_DIR, "subset.json")
CSV_NAME = "SimBenchGrouped.csv"
CSV_URL = "https://huggingface.co/datasets/pitehu/SimBench/resolve/main/SimBenchGrouped.csv"
PAPER = "arXiv 2510.17516"
PUBLISHED = {"Claude 3.7 Sonnet (both splits averaged)": 40.8, "GPT-4.1": 34.55, "DeepSeek-R1": 34.52}

DEFAULT_CASES = 1000
DEFAULT_TWINS = 60
DEFAULT_SEED = 20261027
# The lineups a run builds at once. Each builds in batches of ten (spawn_concurrency bounds those)
# and then answers its cases at `PROBE_PARALLEL` twins at a time, so three groups ≈ 48 twin calls in flight.
DEFAULT_PARALLEL_GROUPS = 3
PROBE_PARALLEL = 16
BARE_ATTEMPTS = 5

csv.field_size_limit(10 ** 9)

_stop: dict[str, bool] = {}
_tasks: dict[str, asyncio.Task] = {}


# ── the data ──────────────────────────────────────────────────────────────────

def csv_path() -> str:
    return os.path.join(CACHE_DIR, CSV_NAME)


def fetch_csv(force: bool = False) -> str:
    """The grouped split, downloaded once into the (gitignored) cache."""
    path = csv_path()
    if os.path.exists(path) and not force:
        return path
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = path + ".part"
    urllib.request.urlretrieve(CSV_URL, tmp)
    os.replace(tmp, path)
    return path


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _literal(s: str, default: Any) -> Any:
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return default


def _keys(s: str) -> list[str]:
    """`grouping_keys` is written as a Python set repr ({'a', 'b'} or set()); the quoted names."""
    return sorted(re.findall(r"'([^']+)'", s or ""))


def render_group(template: str, variables: dict) -> str:
    text = str(template or "")
    for k, v in (variables or {}).items():
        text = text.replace("{" + str(k) + "}", str(v))
    return text.strip()


def group_id_for(dataset: str, group_text: str) -> str:
    return hashlib.sha1(f"{dataset}\n{group_text}".encode()).hexdigest()[:12]


def load_cases(path: Optional[str] = None) -> list[dict]:
    """Every case of the split, in file order (the row index is the case id)."""
    path = path or fetch_csv()
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for idx, r in enumerate(csv.DictReader(f)):
            variables = _literal(r.get("group_prompt_variable_map") or "{}", {}) or {}
            options = _literal(r.get("answer_options") or "{}", {}) or {}
            human = _literal(r.get("human_answer") or "{}", {}) or {}
            group_text = render_group(r.get("group_prompt_template") or "", variables)
            dataset = (r.get("dataset_name") or "").strip()
            out.append({
                "id": idx,
                "dataset": dataset,
                "group_id": group_id_for(dataset, group_text),
                "group_text": group_text,
                "group_vars": {str(k): str(v) for k, v in variables.items()},
                "grouping_keys": _keys(r.get("grouping_keys") or ""),
                "question": str(r.get("input_template") or ""),
                "options": {str(k): str(v) for k, v in options.items()},
                "human": {str(k): float(v) for k, v in human.items()},
                "group_size": int(float(r.get("group_size") or 0)),
                "wave": (r.get("wave") or "").strip(),
            })
    return out


# ── scoring, the authors' way ─────────────────────────────────────────────────

def normalise_dist(d: dict, labels: list[str]) -> Optional[list[float]]:
    """The distribution as a vector over `labels` summing to 1; None when there is nothing in it."""
    vals = [max(0.0, float(d.get(k) or 0.0)) for k in labels]
    tot = sum(vals)
    return [v / tot for v in vals] if tot > 0 else None


def tvd(p: list[float], q: list[float]) -> float:
    return 0.5 * sum(abs(a - b) for a, b in zip(p, q))


def uniform_tvd(human: dict) -> Optional[float]:
    labels = list(human.keys())
    if len(labels) < 2:
        return None
    p = normalise_dist(human, labels)
    if p is None:
        return None
    return tvd(p, [1.0 / len(labels)] * len(labels))


def dataset_norms(cases: list[dict]) -> dict[str, float]:
    """Per dataset, the mean TVD between its human answers and uniform — the score's denominator,
    computed over every case of the split as the authors' script does over every row it is given."""
    acc: dict[str, list[float]] = {}
    for c in cases:
        u = uniform_tvd(c["human"])
        if u is not None:
            acc.setdefault(c["dataset"], []).append(u)
    return {k: sum(v) / len(v) for k, v in acc.items() if v}


def score_case(human: dict, ours: Optional[dict], norm: Optional[float]) -> Optional[dict]:
    """{tvd, score} for one case, or None when there is no answer to score."""
    if not ours or not norm or norm <= 0:
        return None
    labels = list(human.keys())
    p, q = normalise_dist(human, labels), normalise_dist(ours, labels)
    if p is None or q is None:
        return None
    d = tvd(p, q)
    return {"tvd": round(d, 4), "score": round(100.0 * (1.0 - d / norm), 2)}


# ── the subset ────────────────────────────────────────────────────────────────

def _quotas(sizes: dict, n: int) -> dict:
    """Largest-remainder allocation of n cases across strata by their share of the split."""
    total = sum(sizes.values())
    raw = {k: n * v / total for k, v in sizes.items()}
    out = {k: int(math.floor(v)) for k, v in raw.items()}
    for k in sorted(sizes, key=lambda k: (-(raw[k] - out[k]), k))[: n - sum(out.values())]:
        out[k] += 1
    return out


def select_subset(cases: list[dict], n: int = DEFAULT_CASES, seed: int = DEFAULT_SEED) -> list[dict]:
    """A stratified subset filled with whole subgroups.

    Strata are dataset × grouping variables (ESS × country+gender, OpinionQA × RELIG …), each
    given its share of the split's cases. Inside a stratum, subgroups are taken whole in a seeded
    random order until the quota is met — a lineup then serves every case of its subgroup — and
    the last subgroup is trimmed to the quota so the subset is exactly n cases."""
    strata: dict[tuple, dict[str, list[dict]]] = {}
    for c in cases:
        key = (c["dataset"], tuple(c["grouping_keys"]))
        strata.setdefault(key, {}).setdefault(c["group_id"], []).append(c)
    quotas = _quotas({k: sum(len(g) for g in v.values()) for k, v in strata.items()}, n)
    chosen: list[dict] = []
    for key in sorted(strata):
        quota = quotas[key]
        if quota <= 0:
            continue
        rng = random.Random(f"{seed}:{key[0]}:{'+'.join(key[1])}")
        gids = sorted(strata[key])
        rng.shuffle(gids)
        taken: list[dict] = []
        for gid in gids:
            if len(taken) >= quota:
                break
            group = sorted(strata[key][gid], key=lambda c: c["id"])
            taken.extend(group[: quota - len(taken)])
        chosen.extend(taken)
    return sorted(chosen, key=lambda c: c["id"])


def stratum_key(case: dict) -> str:
    return f"{case['dataset']} × {'+'.join(case.get('grouping_keys') or []) or 'none'}"


def build_subset(n: int = DEFAULT_CASES, seed: int = DEFAULT_SEED, path: Optional[str] = None) -> dict:
    """Cut the subset from the full split and write `subset.json` (ids and strata only)."""
    src = fetch_csv()
    cases = load_cases(src)
    chosen = select_subset(cases, n, seed)
    norms = dataset_norms(cases)
    strata: dict[str, dict] = {}
    for c in chosen:
        k = stratum_key(c)
        s = strata.setdefault(k, {"dataset": c["dataset"], "grouping": c["grouping_keys"], "cases": 0, "groups": set()})
        s["cases"] += 1
        s["groups"].add(c["group_id"])
    full: dict[str, int] = {}
    for c in cases:
        k = stratum_key(c)
        full[k] = full.get(k, 0) + 1
    out = {
        "benchmark": BENCHMARK_ID,
        "paper": PAPER,
        "source": {"dataset": "pitehu/SimBench", "file": CSV_NAME, "url": CSV_URL, "sha256": sha256_of(src), "rows": len(cases)},
        "created": datetime.utcnow().strftime("%Y-%m-%d"),
        "seed": seed,
        "n": len(chosen),
        "groups": len({c["group_id"] for c in chosen}),
        "dataset_norms": {k: round(v, 6) for k, v in sorted(norms.items())},
        "strata": [{"key": k, "dataset": v["dataset"], "grouping": v["grouping"], "cases": v["cases"], "groups": len(v["groups"]), "of": full[k]}
                   for k, v in sorted(strata.items())],
        "cases": [{"id": c["id"], "dataset": c["dataset"], "group_id": c["group_id"], "stratum": stratum_key(c)} for c in chosen],
    }
    with open(path or SUBSET_PATH, "w") as f:
        json.dump(out, f, indent=1)
    return out


def load_subset(path: Optional[str] = None) -> Optional[dict]:
    p = path or SUBSET_PATH
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def subset_cases(subset: dict, cases: list[dict]) -> list[dict]:
    """The subset's cases, from the full split (checked by id and group)."""
    by_id = {c["id"]: c for c in cases}
    out = []
    for ref in subset.get("cases") or []:
        c = by_id.get(ref["id"])
        if c and c["group_id"] == ref["group_id"]:
            out.append(c)
    return out


def subset_overview() -> dict:
    """What the admin page shows before a run: size, strata, cost, and whether the data is in the cache."""
    sub = load_subset()
    if not sub:
        return {"ready": False, "reason": "No subset on file — run `python -m app.services.kits.simbench subset`."}
    cached = os.path.exists(csv_path())
    stale = cached and sha256_of(csv_path()) != sub["source"]["sha256"]
    return {"ready": True, "cached": cached, "stale": stale, "n": sub["n"], "groups": sub["groups"], "seed": sub["seed"], "created": sub["created"],
            "source": sub["source"], "strata": sub["strata"], "dataset_norms": sub["dataset_norms"], "published": PUBLISHED, "paper": PAPER}


def plan_counts(cases: int = DEFAULT_CASES, groups_limit: int = 0) -> dict:
    """How many cases and subgroups a run of this size covers, read from the subset alone (no data needed)."""
    sub = load_subset() or {"cases": []}
    chosen = first_refs(sub["cases"], int(cases), int(groups_limit or 0), seed=int(sub.get("seed") or DEFAULT_SEED))
    return {"cases": len(chosen), "groups": len({c["group_id"] for c in chosen}),
            "datasets": sorted({c["dataset"] for c in chosen})}


def estimate(cases: int, groups: int, twins: int, mode: str) -> dict:
    """A rough bill before the run: persona writing per lineup plus one Forms call per twin per case."""
    from app.api.v1.measurement import estimate_cost_usd
    from app.core.config import get_settings
    model = get_settings().agent_model(mode)
    probes = estimate_cost_usd(model, cases * twins)
    # A batch of ten personas ≈ 6k tokens in, 9k out; price it as 25 probe calls' worth on the same model.
    lineups = estimate_cost_usd(model, groups * math.ceil(twins / 10) * 25)
    return {"model": model, "twin_calls": cases * twins, "persona_batches": groups * math.ceil(twins / 10),
            "probes_usd": round(probes, 2), "lineups_usd": round(lineups, 2), "total_usd": round(probes + lineups, 2)}


# ── a subgroup as a Studio segment ────────────────────────────────────────────

COUNTRY_KEYS = ("country", "cntry")
AGE_KEYS = ("age_group", "AGE")
GENDER_KEYS = ("gender", "gndr", "SEX")
KEY_LABELS = {
    "age_group": "Age", "AGE": "Age", "gender": "Gender", "gndr": "Gender", "SEX": "Gender",
    "religion": "Religion", "RELIG": "Religion", "religiosity": "Religiosity", "rlgdgr": "How religious (0 not at all – 10 very)",
    "RELIGATTEND": "Attends religious services", "education": "Education", "EDUCATION": "Education", "eisced": "Education",
    "highest_education": "Education", "employment": "In paid work", "employment_status": "Employment", "work_status": "Work status",
    "mnactic": "Main activity", "INCOME": "Household income", "household_income": "Household income (how it covers needs)",
    "subjective_income": "Gone without enough food in the past year", "topbot": "Where they place themselves on the social ladder (1 bottom – 10 top)",
    "MARITAL": "Marital status", "marital_status": "Marital status", "maritalb": "Marital status",
    "domicil": "Lives in", "urban_rural": "Lives in", "city_size": "Their town", "CREGION": "US region", "RACE": "Race / ethnicity",
    "POLIDEOLOGY": "Political ideology", "POLPARTY": "Party", "lrscale": "Left–right self-placement (0 left – 10 right)",
    "political_group": "Left–right self-placement (0 left – 10 right)", "discuss_politics": "Discusses politics",
}
SHORT_LABELS = {**{k: v.split(" (")[0] for k, v in KEY_LABELS.items()}, "country": "Country", "cntry": "Country", "none": "No trait (whole sample)"}


def grouping_label(grouping: str) -> str:
    """'age_group+cntry' → 'Age + Country' — the trait split as the page shows it."""
    return " + ".join(SHORT_LABELS.get(k, k) for k in (grouping or "none").split("+"))


def _age_range(v: str) -> Optional[tuple[int, int]]:
    m = re.match(r"^\s*(\d{2})\s*[-–]\s*(\d{2})\s*$", v or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^\s*(\d{2})\s*\+\s*$", v or "")
    if m:
        return int(m.group(1)), 88
    return None


def _year_of(group_text: str) -> str:
    m = re.search(r"(?:year is|timeframe is) ([0-9]{4}(?:-[0-9]{4})?)", group_text or "")
    return m.group(1) if m else ""


def _country_of(vars_: dict, group_text: str) -> str:
    for k in COUNTRY_KEYS:
        if vars_.get(k):
            return str(vars_[k])
    m = re.search(r"You are from (?:the )?([A-Z][^.]+?)\.", group_text or "")
    return m.group(1).strip() if m else ""


def group_profile(case: dict) -> dict:
    """What the subgroup is, read from its prompt: country, year, age, gender and the other traits."""
    v = case.get("group_vars") or {}
    text = case.get("group_text") or ""
    age = next((_age_range(v[k]) for k in AGE_KEYS if v.get(k)), None)
    gender = next((str(v[k]).lower() for k in GENDER_KEYS if v.get(k)), "")
    traits = [(KEY_LABELS.get(k, k), str(val)) for k, val in v.items() if k not in COUNTRY_KEYS + AGE_KEYS + GENDER_KEYS]
    return {"country": _country_of(v, text), "year": _year_of(text), "age": age, "gender": gender, "traits": traits,
            "dataset": case.get("dataset") or "", "text": text}


def group_title(case: dict) -> str:
    p = group_profile(case)
    bits = [p["dataset"], p["year"], p["country"]]
    if p["gender"]:
        bits.append({"female": "women", "male": "men"}.get(p["gender"], p["gender"]))
    if p["age"]:
        bits.append(f"aged {p['age'][0]}–{p['age'][1]}" if p["age"][1] < 88 else f"aged {p['age'][0]}+")
    bits += [f"{SHORT_LABELS.get(k, k).lower()}: {val}" for k, val in [(k2, v2) for k2, v2 in (case.get('group_vars') or {}).items() if k2 not in COUNTRY_KEYS + AGE_KEYS + GENDER_KEYS]]
    return " · ".join(b for b in bits if b)[:150]


def session_query(case: dict) -> str:
    p = group_profile(case)
    who = p["text"].replace("You are", "people who are").replace("The year is", "in")
    return (f"A national social survey ({p['dataset']}{', ' + p['year'] if p['year'] else ''}) of everyday life, society, politics and values in "
            f"{p['country'] or 'their country'}, as seen by {who}")


def segment_for(case: dict, count: int) -> dict:
    """The one-segment plan the persona writer builds the lineup from. The subgroup's fixed facts
    (country, age band, gender) are the segment's demographics; every other trait is stated in the
    description so the writer gives each person that trait; nothing about the topic is assumed."""
    p = group_profile(case)
    desc = [p["text"]]
    if p["traits"]:
        desc.append("Every person in this segment: " + "; ".join(f"{k} — {v}" for k, v in p["traits"]) + ".")
    desc.append(f"They are ordinary members of the public of {p['country'] or 'this country'}"
                + (f" as it was in {p['year']}" if p["year"] else "") + ", drawn as a representative slice of that subgroup: varied jobs, towns, incomes "
                "(within the stated traits), households and outlooks — the mix a national survey would reach, not people chosen for an opinion.")
    age = p["age"] or (18, 85)
    female = {"female": 100, "male": 0}.get(p["gender"], 51)
    return {
        "id": "subgroup", "name": group_title(case), "share_pct": 100, "stance": "neutral", "count": int(count),
        "description": " ".join(desc),
        "demographics": {"age_min": age[0], "age_max": age[1], "gender_female_pct": female, "regions": [p["country"]] if p["country"] else [],
                         "income_band": "mixed", "education": "mixed", "occupations": []},
        "sentiment": {"mood": "mixed", "temperature": 4, "top_emotions": []},
        "arguments": [], "evidence": [],
        "rationale": f"A demographic subgroup of the {p['dataset']} sample, as the benchmark defines it.",
        "humanity_hint": "tempered", "frame_values": {}, "decision": "accepted", "reason": None,
    }


def persona_constraints(case: dict) -> dict:
    p = group_profile(case)
    return {"demographics": {"regions": [p["country"]] if p["country"] else [],
                             "notes": f"Everyone matches this exactly: {p['text']}" + (f" The year is {p['year']}: lives, prices and events as they stood then." if p["year"] else "")},
            "dynamic_dials": []}


# ── the question, as Forms asks it ────────────────────────────────────────────

def question_stem(question: str) -> str:
    """The question without the benchmark's own option list (Forms lists the options itself)."""
    return re.split(r"\n\s*Options:\s*\n", question, maxsplit=1)[0].strip()


def form_options(case: dict) -> list[str]:
    """Option texts in label order, made distinct where the source repeats a text."""
    seen: dict[str, int] = {}
    out = []
    for label in case["human"].keys():
        text = (case["options"].get(label) or label).strip()[:120] or label
        n = seen.get(text, 0)
        seen[text] = n + 1
        out.append(text if n == 0 else f"{text} ({n + 1})")
    return out


def probe_spec(case: dict, run_id: str) -> dict:
    p = group_profile(case)
    when = f"This survey was carried out in {p['year']}. Answer as you would have answered then, as the person you are." if p["year"] else ""
    return {
        "title": f"{p['dataset']} survey" + (f", {p['year']}" if p["year"] else ""),
        "context_before": when,
        "questions": [{"key": "q", "type": "single", "text": question_stem(case["question"]), "options": form_options(case), "likelihood": True}],
        # A fresh respondent each time: no knowledge graph (there is none), no posts, no earlier answers.
        "context": {"kg": False, "own_posts": False, "prior_answers": False},
        "simbench": {"run_id": run_id, "case_id": case["id"], "group_id": case["group_id"], "labels": list(case["human"].keys())},
    }


def twins_distributions(case: dict, answers: list[dict]) -> dict:
    """From the lineup's answers: the mean of the twins' chances ("likelihood") and the share of
    their realised picks ("draws"), both over the benchmark's labels; refusals are counted, not scored."""
    from app.services.measurement.probe import answered
    labels = list(case["human"].keys())
    texts = form_options(case)
    idx = {t: k for k, t in enumerate(texts)}
    like = [0.0] * len(labels)
    draws = [0.0] * len(labels)
    n_like = n_draw = refused = 0
    for a in answers:
        if not answered({"answer": a}):
            refused += 1
            continue
        dist = (a.get("_dist") or {}).get("q")
        if isinstance(dist, dict):
            vec = [max(0.0, float(dist.get(f"o{k + 1}") or 0.0)) for k in range(len(labels))]
            tot = sum(vec)
            if tot > 0:
                for k, v in enumerate(vec):
                    like[k] += v / tot
                n_like += 1
        pick = a.get("q")
        if isinstance(pick, str) and pick in idx:
            draws[idx[pick]] += 1
            n_draw += 1
    out: dict[str, Any] = {"answers": len(answers), "refused": refused, "likelihood": None, "draws": None}
    if n_like:
        out["likelihood"] = {lab: round(v / n_like, 4) for lab, v in zip(labels, like)}
    if n_draw:
        out["draws"] = {lab: round(v / n_draw, 4) for lab, v in zip(labels, draws)}
    return out


# ── the bare model, the benchmark's own way ───────────────────────────────────

def bare_prompts(case: dict) -> tuple[str, str]:
    """The verbalised prompt from the authors' generate_answers.py, verbatim."""
    system = "You are a group of individuals with these shared characteristics:\n" + case["group_text"]
    keys = list(case["human"].keys())
    json_format_str = "{" + ", ".join(f'"{key}": X' for key in keys) + "}"
    user = ("**Question**: " + case["question"] + "\n"
            + "\nEstimate what percentage of your group would choose each option. "
            + "Follow these rules:\n"
            + "1. Use whole numbers from 0 to 100\n"
            + "2. Ensure the percentages sum to exactly 100\n"
            + "3. Only include the numbers (no % symbols)\n"
            + f"4. Use this exact valid JSON format: {json_format_str} and do NOT include anything else.\n"
            + "5. Only output your final answer and nothing else. No explanations or intermediate steps are needed.\n"
            + "Replace X with your estimated percentages for each option.\n"
            + "**Answer**:")
    return system, user


def parse_bare(response: str, expected_keys: list[str]) -> dict[str, float]:
    """The authors' parse_and_normalize_json_response, keyed by label. Raises ValueError as theirs does."""
    match = re.search(r"\{[\s\S]*?\}", response or "")
    if not match:
        raise ValueError("No JSON found")
    json_str = match.group(0)
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError:
        json_str = re.sub(r"%", "", json_str)
        json_str = re.sub(r",\s*([}\]])", r"\1", json_str)
        json_str = re.sub(r'([{,]\s*)([^"\s]+)\s*:', r'\1"\2":', json_str)
        json_str = re.sub(r':\s*([^",}\]\s]+)([,}\]])', r':"\1"\2', json_str)
        json_str = re.sub(r':"(-?\d+\.?\d*)"', r":\1", json_str)
        json_str = re.sub(r'([^"])"([,}])', r"\1\2", json_str)
        json_str = json_str.strip()
        if not json_str.startswith("{"):
            json_str = "{" + json_str
        if not json_str.endswith("}"):
            json_str = json_str + "}"
        parsed = json.loads(json_str)
    if not isinstance(parsed, dict) or not all(k in parsed for k in expected_keys):
        raise ValueError(f"Missing expected keys in response: {expected_keys}")
    vals = {k: float(parsed[k]) for k in expected_keys}
    total = sum(vals.values())
    if total <= 0:
        raise ValueError("Sum of probabilities is zero, cannot normalize.")
    return {k: v / total for k, v in vals.items()}


async def bare_model(case: dict, *, session_id: Optional[str], mode: str) -> dict:
    """The model alone on the case: up to five attempts, temperature 0 then 1 after a parse failure,
    250 output tokens — the authors' settings. Returns {dist, attempts, raw} (dist None on failure)."""
    import anthropic
    from app.core.config import get_settings
    from app.core.monitoring import tracked_messages_create
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    system, user = bare_prompts(case)
    keys = list(case["human"].keys())
    temperature = 0.0
    raw = ""
    for attempt in range(1, BARE_ATTEMPTS + 1):
        try:
            resp = await tracked_messages_create(client, session_id=session_id, label="simbench:bare", model=settings.agent_model(mode),
                                                 max_tokens=250, temperature=temperature, system=system,
                                                 messages=[{"role": "user", "content": user}])
            raw = "".join(getattr(b, "text", "") for b in resp.content)
            return {"dist": {k: round(v, 4) for k, v in parse_bare(raw, keys).items()}, "attempts": attempt, "raw": raw[:300]}
        except ValueError:
            temperature = 1.0
        except Exception as e:  # noqa: BLE001 — an API error: wait and try again
            print(f"[simbench] bare model call failed ({case['id']}, attempt {attempt}): {type(e).__name__}: {e}")
            await asyncio.sleep(min(30, 2 ** attempt))
    return {"dist": None, "attempts": BARE_ATTEMPTS, "raw": raw[:300]}


# ── the run ───────────────────────────────────────────────────────────────────

async def _load_run(run_id: str):
    from app.core import database as dbm
    from app.models.benchmark import BenchmarkRun
    async with dbm.AsyncSessionLocal() as db:
        return await db.get(BenchmarkRun, run_id)


_locks: dict[int, asyncio.Lock] = {}


def _state_lock() -> asyncio.Lock:
    """One lock per event loop: state writes are read-modify-write of one JSON column."""
    loop = asyncio.get_running_loop()
    lock = _locks.get(id(loop))
    if lock is None:
        lock = _locks[id(loop)] = asyncio.Lock()
    return lock


async def _update(run_id: str, *, group: Optional[tuple[str, dict]] = None, case: Optional[tuple[str, dict]] = None, **fields) -> None:
    """Merge one group's or one case's state into the row (under a lock, in its own transaction)."""
    from app.core import database as dbm
    from app.models.benchmark import BenchmarkRun
    from sqlalchemy.orm.attributes import flag_modified
    async with _state_lock():
        async with dbm.AsyncSessionLocal() as db:
            run = await db.get(BenchmarkRun, run_id)
            if not run:
                return
            state = dict(run.state or {})
            if group:
                groups = dict(state.get("groups") or {})
                groups[group[0]] = {**(groups.get(group[0]) or {}), **group[1]}
                state["groups"] = groups
            if case:
                cases = dict(state.get("cases") or {})
                cases[case[0]] = {**(cases.get(case[0]) or {}), **case[1]}
                state["cases"] = cases
            run.state = state
            flag_modified(run, "state")
            run.progress = _progress(run.config or {}, state)
            flag_modified(run, "progress")
            for k, v in fields.items():
                setattr(run, k, v)
            run.updated_at = datetime.utcnow()
            await db.commit()


def _progress(config: dict, state: dict) -> dict:
    cases = state.get("cases") or {}
    groups = state.get("groups") or {}
    done = sum(1 for c in cases.values() if c.get("status") == "complete")
    failed = sum(1 for c in cases.values() if c.get("status") == "failed")
    return {"cases_total": int(config.get("case_count") or 0), "cases_done": done, "cases_failed": failed,
            "groups_total": int(config.get("group_count") or 0), "groups_built": sum(1 for g in groups.values() if g.get("status") == "ready"),
            "groups_failed": sum(1 for g in groups.values() if g.get("status") == "failed")}


def _stopped(run_id: str) -> bool:
    return bool(_stop.get(run_id))


async def start(user_id: Optional[str], *, cases: int = DEFAULT_CASES, twins: int = DEFAULT_TWINS, mode: str = "fast",
                seed: Optional[int] = None, parallel_groups: int = DEFAULT_PARALLEL_GROUPS, bare: bool = True,
                groups_limit: int = 0) -> Any:
    """Create a run over the committed subset (its first `cases` cases, whole subgroups first) and
    start it in the background. `groups_limit` caps the subgroups for a smoke run."""
    from app.core import database as dbm
    from app.models.benchmark import BenchmarkRun
    sub = load_subset()
    if not sub:
        raise ValueError("No subset on file — build it first (python -m app.services.kits.simbench subset).")
    src = await asyncio.to_thread(fetch_csv)
    if await asyncio.to_thread(sha256_of, src) != sub["source"]["sha256"]:
        raise ValueError("The SimBench file on Hugging Face has changed since the subset was cut (sha256 differs) — re-cut the subset before running.")
    all_cases = subset_cases(sub, await asyncio.to_thread(load_cases, src))
    if len(all_cases) != sub["n"]:
        raise ValueError(f"The cached data does not match the subset ({len(all_cases)} of {sub['n']} cases found) — refetch it.")
    by_id = {c["id"]: c for c in all_cases}
    chosen = [by_id[r["id"]] for r in first_refs(sub["cases"], cases, groups_limit, seed=int(sub.get("seed") or DEFAULT_SEED))]
    group_ids = []
    for c in chosen:
        if c["group_id"] not in group_ids:
            group_ids.append(c["group_id"])
    config = {"benchmark": BENCHMARK_ID, "subset_seed": sub["seed"], "subset_n": sub["n"], "source_sha256": sub["source"]["sha256"],
              "case_count": len(chosen), "group_count": len(group_ids), "twins": max(10, min(200, int(twins))), "mode": "pro" if mode == "pro" else "fast",
              "seed": int(seed) if seed is not None else random.randint(1, 2 ** 31 - 1), "parallel_groups": max(1, min(8, int(parallel_groups))),
              "bare": bool(bare), "case_ids": [c["id"] for c in chosen], "dataset_norms": sub["dataset_norms"],
              "estimate": estimate(len(chosen), len(group_ids), max(10, min(200, int(twins))), "pro" if mode == "pro" else "fast")}
    run = BenchmarkRun(id=str(uuid.uuid4()), user_id=user_id, benchmark=BENCHMARK_ID, status="queued", config=config,
                       state={"groups": {}, "cases": {}}, progress=_progress(config, {}))
    async with dbm.AsyncSessionLocal() as db:
        db.add(run)
        await db.commit()
    _launch(run.id)
    return run


def first_refs(refs: list[dict], n: int, groups_limit: int = 0, *, seed: int = DEFAULT_SEED) -> list[dict]:
    """The first n cases of the subset as a proportional slice: whole subgroups, taken from the
    survey furthest behind its share of the subset and, inside it, the stratum furthest behind
    (ties broken by a seeded draw) — so a 100-case pilot covers every survey in proportion instead
    of the first survey in the file."""
    groups: dict[str, list[dict]] = {}
    for r in refs:
        groups.setdefault(r["group_id"], []).append(r)
    tree: dict[str, dict[str, list[str]]] = {}
    size: dict[tuple, int] = {}
    for gid, rs in groups.items():
        ds = rs[0].get("dataset") or ""
        st = rs[0].get("stratum") or ds
        tree.setdefault(ds, {}).setdefault(st, []).append(gid)
        size[(ds,)] = size.get((ds,), 0) + len(rs)
        size[(ds, st)] = size.get((ds, st), 0) + len(rs)
    tie = random.Random(f"{seed}:order")
    rank = {}
    for ds in sorted(tree):
        rank[(ds,)] = tie.random()
        for st in sorted(tree[ds]):
            rank[(ds, st)] = tie.random()
            random.Random(f"{seed}:order:{st}").shuffle(tree[ds][st])
    taken = {k: 0 for k in size}
    out: list[dict] = []
    used = 0

    def behind(k: tuple) -> tuple:
        return (taken[k] / size[k], rank[k])

    while len(out) < n:
        open_ds = [ds for ds in tree if any(tree[ds].values())]
        if not open_ds or (groups_limit and used >= groups_limit):
            break
        ds = min(open_ds, key=lambda d: behind((d,)))
        st = min((x for x in tree[ds] if tree[ds][x]), key=lambda x: behind((ds, x)))
        gid = tree[ds][st].pop(0)
        out.extend(groups[gid][: n - len(out)])
        taken[(ds,)] += len(groups[gid])
        taken[(ds, st)] += len(groups[gid])
        used += 1
    return out


def _launch(run_id: str) -> None:
    _stop[run_id] = False
    _tasks[run_id] = asyncio.create_task(_run(run_id))


async def resume(run_id: str) -> bool:
    run = await _load_run(run_id)
    if not run or run.status in ("running", "stopping", "complete"):
        return False
    await _update(run_id, status="queued", error=None)
    _launch(run_id)
    return True


async def stop(run_id: str) -> bool:
    run = await _load_run(run_id)
    if not run or run.status not in ("queued", "running"):
        return False
    _stop[run_id] = True
    await _update(run_id, status="stopping")
    return True


async def _run(run_id: str) -> None:
    try:
        run = await _load_run(run_id)
        if not run:
            return
        config, state = dict(run.config or {}), dict(run.state or {})
        await _update(run_id, status="running")
        cases_all = {c["id"]: c for c in await asyncio.to_thread(load_cases)}
        chosen = [cases_all[i] for i in config["case_ids"] if i in cases_all]
        by_group: dict[str, list[dict]] = {}
        for c in chosen:
            by_group.setdefault(c["group_id"], []).append(c)
        sem = asyncio.Semaphore(int(config.get("parallel_groups") or DEFAULT_PARALLEL_GROUPS))

        async def one_group(gid: str, group: list[dict]) -> None:
            async with sem:
                if _stopped(run_id):
                    return
                try:
                    session_id = await _ensure_lineup(run_id, run.user_id, config, state, gid, group[0])
                except asyncio.CancelledError:
                    if _stopped(run_id):
                        return
                    raise
                except Exception as e:  # noqa: BLE001
                    traceback.print_exc()
                    await _update(run_id, group=(gid, {"status": "failed", "error": f"{type(e).__name__}: {str(e)[:200]}"}))
                    for c in group:
                        await _update(run_id, case=(str(c["id"]), {"status": "failed", "error": "lineup failed"}))
                    return
                for c in group:
                    if _stopped(run_id):
                        return
                    await _ensure_case(run_id, config, state, session_id, c)

        await asyncio.gather(*(one_group(gid, grp) for gid, grp in by_group.items()))
        run = await _load_run(run_id)
        summary = summarise(run.config or {}, run.state or {})
        final = "stopped" if _stopped(run_id) else "complete"
        await _update(run_id, status=final, summary=summary, completed_at=datetime.utcnow() if final == "complete" else None)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        await _update(run_id, status="failed", error=f"{type(e).__name__}: {str(e)[:400]}")
    finally:
        _tasks.pop(run_id, None)
        _stop.pop(run_id, None)


async def _ensure_lineup(run_id: str, user_id: Optional[str], config: dict, state: dict, gid: str, case: dict) -> str:
    """The subgroup's session with its twins — reused when an earlier attempt built it."""
    from sqlalchemy import func, select
    from app.core import database as dbm
    from app.core import model_policy
    from app.models.agent import SpawnedAgent
    from app.models.session import AnalysisSession, SessionStatus
    existing = ((state.get("groups") or {}).get(gid) or {})
    mode = config.get("mode") or "fast"
    session_id = existing.get("session_id")
    if session_id:
        async with dbm.AsyncSessionLocal() as db:
            n = (await db.execute(select(func.count(SpawnedAgent.id)).where(SpawnedAgent.session_id == session_id))).scalar_one()
            # Only a lineup that finished writing is reused; one cut short by Stop or a restart is rewritten
            # in the same session, so a resumed run never measures a half-written lineup.
            if existing.get("status") == "ready" and n >= max(10, int(config["twins"]) // 2):
                await _update(run_id, group=(gid, {"status": "ready", "agents": int(n)}))
                return session_id
            for a in (await db.execute(select(SpawnedAgent).where(SpawnedAgent.session_id == session_id))).scalars().all():
                await db.delete(a)
            await db.commit()
    else:
        session_id = str(uuid.uuid4())
        async with dbm.AsyncSessionLocal() as db:
            db.add(AnalysisSession(id=session_id, user_id=user_id, title=f"SimBench · {group_title(case)}"[:255], query=session_query(case),
                                   status=SessionStatus.READY, model_tier=model_policy.normalise(mode), kind="benchmark"))
            await db.commit()
    model_policy.remember(session_id, mode)
    await _update(run_id, group=(gid, {"session_id": session_id, "status": "building", "title": group_title(case), "group_text": case["group_text"]}))
    started = time.monotonic()
    n = await build_lineup(session_id, case, int(config["twins"]), mode, should_stop=lambda: _stopped(run_id))
    if _stopped(run_id):
        await _update(run_id, group=(gid, {"status": "stopped", "agents": n}))
        raise asyncio.CancelledError("stopped while writing the lineup")
    if n == 0:
        raise RuntimeError("the persona writer returned no twins")
    await _update(run_id, group=(gid, {"status": "ready", "agents": n, "build_sec": round(time.monotonic() - started, 1)}))
    return session_id


async def build_lineup(session_id: str, case: dict, twins: int, mode: str, should_stop=None) -> int:
    """Write the subgroup's twins with the Studio's own persona writer and store them on the session.
    The build's side jobs (validation battery, scoping annotation, frame weights) are not run: the
    benchmark measures the twins as written, and those would multiply the bill."""
    from sqlalchemy import select
    from app.core import database as dbm
    from app.models.agent import SpawnedAgent
    from app.models.session import AnalysisSession
    from app.services.agents.agent_factory import generate_agents_from_plan
    seg = segment_for(case, twins)
    # `should_stop`: Stop abandons the writer's in-flight calls at once (2026-10-28 — without it the
    # three lineups being written kept calling the model for minutes after Stop).
    profiles = await generate_agents_from_plan(session_id, session_query(case), [seg], persona_constraints(case), mode=mode, should_stop=should_stop)
    async with dbm.AsyncSessionLocal() as db:
        db.add_all([
            SpawnedAgent(
                id=p.id, session_id=session_id, name=p.name, age=p.age, role=p.role, background=p.background, stance=p.stance,
                correlation=p.correlation, personality=p.personality, debate_style=p.debate_style, energy=p.energy,
                avatar_color=p.avatar_color, dials=p.dials or {}, humanity=p.humanity or 0, segment=p.segment or seg["name"],
                demographics=p.demographics or None, weight=1.0, character=getattr(p, "character", None) or None,
                standing=getattr(p, "standing", None) or None,
                knowledge={"written_from": "shared", "written_units": 0, "written_snapshot": None},
            )
            for p in profiles
        ])
        sess = (await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))).scalar_one_or_none()
        if sess:
            sess.agent_count = len(profiles)
        await db.commit()
    return len(profiles)


async def _ensure_case(run_id: str, config: dict, state: dict, session_id: str, case: dict) -> None:
    """Score one case: the lineup's answers (a finished probe is reused, anything else re-run) and,
    unless switched off, the bare model's. Every outcome is written to the run's state."""
    cid = str(case["id"])
    prior = (state.get("cases") or {}).get(cid) or {}
    if prior.get("status") == "complete":
        return
    norm = (config.get("dataset_norms") or {}).get(case["dataset"])
    entry: dict[str, Any] = {"dataset": case["dataset"], "group_id": case["group_id"], "grouping": "+".join(case["grouping_keys"]) or "none",
                             "session_id": session_id, "status": "running",
                             "started_at": datetime.utcnow().isoformat() + "Z"}
    await _update(run_id, case=(cid, entry))
    try:
        answers = None
        if prior.get("probe_id"):
            answers = await _probe_answers(prior["probe_id"], finished_only=True)
            if answers is not None:
                entry["probe_id"] = prior["probe_id"]
        if answers is None:
            probe_id = await _run_probe(session_id, case, run_id, config)
            entry["probe_id"] = probe_id
            answers = await _probe_answers(probe_id) or []
        dists = twins_distributions(case, answers)
        entry.update({"answers": dists["answers"], "refused": dists["refused"], "twins_likelihood": dists["likelihood"], "twins_draws": dists["draws"]})
        scores = {"likelihood": score_case(case["human"], dists["likelihood"], norm), "draws": score_case(case["human"], dists["draws"], norm)}
        if config.get("bare", True):
            if prior.get("bare") and prior.get("bare_score"):
                entry["bare"], scores["bare"] = prior["bare"], prior["bare_score"]
            else:
                b = await bare_model(case, session_id=session_id, mode=config.get("mode") or "fast")
                entry["bare"] = b["dist"]
                entry["bare_attempts"] = b["attempts"]
                scores["bare"] = score_case(case["human"], b["dist"], norm)
        entry["scores"] = {k: v for k, v in scores.items() if v is not None}
        entry["bare_score"] = scores.get("bare")
        entry["status"] = "complete" if entry["scores"].get("likelihood") or entry["scores"].get("draws") else "failed"
        if entry["status"] == "failed":
            entry["error"] = "no scorable answers from the lineup"
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        entry.update({"status": "failed", "error": f"{type(e).__name__}: {str(e)[:200]}"})
    entry["finished_at"] = datetime.utcnow().isoformat() + "Z"
    await _update(run_id, case=(cid, entry))


async def _run_probe(session_id: str, case: dict, run_id: str, config: dict) -> str:
    """One Forms run of the case on the lineup, awaited to completion (not a background task)."""
    from app.core import database as dbm
    from app.core.config import get_settings
    from app.models.measurement import Probe
    from app.services.measurement import probe as probe_svc
    from app.services.measurement import instruments
    inst = instruments.get("survey")
    spec = probe_spec(case, run_id)
    seed = (int(config.get("seed") or 1) * 1_000_003 + int(case["id"])) % (2 ** 31 - 1)
    spec["seed"] = seed
    p = Probe(session_id=session_id, instrument=inst.key, schema_id=inst.schema_id(), spec=spec, seed=seed,
              model=get_settings().agent_model(config.get("mode") or "fast"), prompt_hash=probe_svc.prompt_hash(inst, spec), status="queued")
    async with dbm.AsyncSessionLocal() as db:
        db.add(p)
        await db.commit()
        probe_id = p.id
    await probe_svc.run_probe(probe_id, concurrency=PROBE_PARALLEL)
    return probe_id


async def _probe_answers(probe_id: str, finished_only: bool = False) -> Optional[list[dict]]:
    """The answers of one probe; None when `finished_only` and the probe did not finish."""
    from sqlalchemy import select
    from app.core import database as dbm
    from app.models.measurement import Probe, ProbeAnswer
    async with dbm.AsyncSessionLocal() as db:
        p = await db.get(Probe, probe_id)
        if not p:
            return None
        if finished_only and p.status not in ("complete", "stopped"):
            return None
        rows = (await db.execute(select(ProbeAnswer.answer).where(ProbeAnswer.probe_id == probe_id))).scalars().all()
    return [r or {} for r in rows]


# ── the reading ───────────────────────────────────────────────────────────────

def _mean(xs: list[float]) -> Optional[float]:
    return round(sum(xs) / len(xs), 2) if xs else None


def _sem(xs: list[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return round(math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1) / len(xs)), 2)


def summarise(config: dict, state: dict, cases: Optional[dict[int, dict]] = None) -> dict:
    """Mean score per estimator (twins by likelihood, twins by draws, the bare model), overall and by
    dataset and by the traits that define the subgroup — the authors' mean of per-case scores. The
    traits come from each scored case's state; `cases` (id → case) fills them for older rows."""
    done = {int(k): v for k, v in (state.get("cases") or {}).items() if v.get("status") == "complete"}
    ests = ["likelihood", "draws"] + (["bare"] if config.get("bare", True) else [])

    def block(items: list[tuple[int, dict]]) -> dict:
        out: dict[str, Any] = {"cases": len(items)}
        for e in ests:
            xs = [v["scores"][e]["score"] for _, v in items if (v.get("scores") or {}).get(e)]
            out[e] = {"mean": _mean(xs), "sem": _sem(xs), "n": len(xs)}
        paired = [(v["scores"]["likelihood"]["score"], v["scores"]["bare"]["score"]) for _, v in items
                  if (v.get("scores") or {}).get("likelihood") and (v.get("scores") or {}).get("bare")]
        if paired:
            diffs = [a - b for a, b in paired]
            out["twins_minus_bare"] = {"mean": _mean(diffs), "sem": _sem(diffs), "n": len(diffs),
                                       "twins_ahead_share": round(sum(1 for d in diffs if d > 0) / len(diffs), 2)}
        return out

    items = sorted(done.items())
    by_dataset = {}
    for ds in sorted({v["dataset"] for _, v in items}):
        by_dataset[ds] = block([(k, v) for k, v in items if v["dataset"] == ds])
    keyed: dict[str, list] = {}
    for k, v in items:
        c = (cases or {}).get(k)
        g = v.get("grouping") or (("+".join(c["grouping_keys"]) or "none") if c else None)
        if g:
            keyed.setdefault(g, []).append((k, v))
    by_grouping = {grouping_label(g): block(v) for g, v in sorted(keyed.items(), key=lambda kv: grouping_label(kv[0]))}
    failed = sum(1 for v in (state.get("cases") or {}).values() if v.get("status") == "failed")
    refused = sum(int(v.get("refused") or 0) for _, v in items)
    answers = sum(int(v.get("answers") or 0) for _, v in items)
    return {"overall": block(items), "by_dataset": by_dataset, "by_grouping": by_grouping, "failed_cases": failed,
            "refusal_share": round(refused / answers, 4) if answers else None, "model": (config.get("estimate") or {}).get("model"),
            "twins": config.get("twins"), "published": PUBLISHED, "paper": PAPER, "computed_at": datetime.utcnow().isoformat() + "Z"}


async def run_payload(run, *, with_cases: bool = False) -> dict:
    """The row for the admin page: config, progress, summary (recomputed live while running), cost so far."""
    from sqlalchemy import func, select
    from app.core import database as dbm
    from app.models.usage import LlmUsage
    state = run.state or {}
    session_ids = [g.get("session_id") for g in (state.get("groups") or {}).values() if g.get("session_id")]
    cost = 0.0
    if session_ids:
        async with dbm.AsyncSessionLocal() as db:
            cost = float((await db.execute(select(func.coalesce(func.sum(LlmUsage.cost_usd), 0.0)).where(LlmUsage.session_id.in_(session_ids)))).scalar_one() or 0.0)
    summary = run.summary if run.status == "complete" and run.summary else summarise(run.config or {}, state)
    out = {"id": run.id, "benchmark": run.benchmark, "status": run.status, "config": {k: v for k, v in (run.config or {}).items() if k not in ("case_ids", "dataset_norms")},
           "progress": run.progress or {}, "summary": summary, "cost_usd": round(cost, 2), "error": run.error,
           "created_at": run.created_at.isoformat() if run.created_at else None, "updated_at": run.updated_at.isoformat() if run.updated_at else None,
           "completed_at": run.completed_at.isoformat() if run.completed_at else None,
           "groups": sorted(({"id": k, **{kk: vv for kk, vv in v.items() if kk != "group_text"}} for k, v in (state.get("groups") or {}).items()), key=lambda g: g.get("title") or "")}
    if with_cases:
        out["cases"] = [{"id": int(k), **v} for k, v in sorted((state.get("cases") or {}).items(), key=lambda kv: int(kv[0]))]
    return out


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli(argv: list[str]) -> int:
    if not argv or argv[0] not in ("subset", "overview"):
        print("usage: python -m app.services.kits.simbench subset [n] [seed] | overview")
        return 2
    if argv[0] == "subset":
        n = int(argv[1]) if len(argv) > 1 else DEFAULT_CASES
        seed = int(argv[2]) if len(argv) > 2 else DEFAULT_SEED
        out = build_subset(n, seed)
        print(f"wrote {SUBSET_PATH}: {out['n']} cases in {out['groups']} subgroups from {out['source']['rows']} (sha256 {out['source']['sha256'][:12]}…)")
        for s in out["strata"]:
            print(f"  {s['key']:<48} {s['cases']:>4} cases / {s['groups']:>3} groups  (of {s['of']})")
        return 0
    print(json.dumps(subset_overview(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
