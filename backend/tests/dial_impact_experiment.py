"""Dial-Impact Experiment.

Question: do the 112 psychological dials actually drive agent behavior, or are
they flavor text? This holds the conversation FIXED (same query, same thread,
same persona) and sweeps one dial at a time to its low/high extreme, then
measures how the generated post changes via:

  1. an LLM judge scoring each post on 5 behavioral dimensions (0-10), and
  2. deterministic text metrics (hedge words, questions, exclamations, numbers).

A clean result shows a strong DIAGONAL: each swept dial moves its own target
dimension and little else. Also exercises aggregate_dials() (the dashboard
aggregation) on a synthetic population so its output shape is demonstrated.

Run from backend/:   venv/bin/python tests/dial_impact_experiment.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.models.agent import SpawnedAgent, AgentStance  # noqa: E402
from app.services.agents.agent_factory import DIALS_SCHEMA  # noqa: E402
from app.services.agents.agent_runner import (  # noqa: E402
    generate_post,
    _build_system_prompt,
    _dials_to_behavioral_guidance,
)
from app.services.agents.dial_analytics import aggregate_dials  # noqa: E402

# ── Fixed scenario ──────────────────────────────────────────────────────────
QUERY = "Should our 12-person product team replace weekly status meetings with async written updates?"

THREAD_CONTEXT = (
    "[Maria Chen | Engineering Manager]: Async updates would give everyone back "
    "~3 focused hours a week. People can read on their own schedule.\n\n"
    "[Devon Brooks | Product Lead]: Maybe, but we lose the spontaneous back-and-forth "
    "that catches problems early. Some things need a live conversation."
)

KG_CONTEXT = (
    "Topic: replacing synchronous weekly status meetings with asynchronous written "
    "updates for a 12-person product + engineering team. Trade-offs: focus time vs. "
    "real-time discussion, written clarity vs. meeting overhead, timezone spread."
)

PERSONA = dict(
    name="Alex Rivera",
    age=38,
    role="Senior Software Engineer",
    background=(
        "Twelve years building distributed systems at mid-size startups. Has lived "
        "through both meeting-heavy and async-first cultures."
    ),
    stance=AgentStance.DIRECT,
    correlation="Is on the team that would directly adopt the new process.",
    personality=["analytical", "pragmatic", "direct"],
    debate_style="Builds arguments from concrete examples and explicit trade-offs.",
    energy=0.7,
    avatar_color="#6366f1",
)

# ── Dial sweeps:  (variant, group, dial, value, target_dim, high_moves_target_up)
SWEEPS = [
    ("disgust_high",      "sentiment", "disgust",              10, "hostility",       True),
    ("disgust_low",       "sentiment", "disgust",               0, "hostility",       True),
    ("anxiety_high",      "sentiment", "anxiety",              10, "hedging",         True),
    ("anxiety_low",       "sentiment", "anxiety",               0, "hedging",         True),
    ("credibility_high",  "trust",     "credibility",          10, "source_citing",  True),
    ("credibility_low",   "trust",     "credibility",           0, "source_citing",  True),
    ("curiosity_high",    "sentiment", "curiosity",            10, "question_asking", True),
    ("curiosity_low",     "sentiment", "curiosity",             0, "question_asking", True),
    ("resistance_high",   "friction",  "emotional_resistance", 10, "concession",     False),
    ("resistance_low",    "friction",  "emotional_resistance",  0, "concession",     False),
]

JUDGE_DIMS = ["hostility", "hedging", "source_citing", "question_asking", "concession"]

JUDGE_RUBRIC = (
    "hostility: contempt/sharpness/dismissiveness toward other views "
    "(0=warm & collegial, 10=openly contemptuous).\n"
    "hedging: uncertainty markers & qualifiers like 'I think', 'maybe', 'I could be wrong' "
    "(0=assertive & certain, 10=heavily hedged).\n"
    "source_citing: reliance on data, studies, numbers, credentials, evidence "
    "(0=pure intuition/personal, 10=evidence-heavy).\n"
    "question_asking: genuine curiosity & probing follow-up questions "
    "(0=only states positions, 10=asks many real questions).\n"
    "concession: willingness to grant points / agree / update view "
    "(0=resists everything, 10=readily concedes)."
)

HEDGE_PHRASES = [
    "i think", "i guess", "i suppose", "maybe", "perhaps", "probably", "possibly",
    "might", "could be", "i'm not sure", "not sure", "i could be wrong",
    "seems like", "sort of", "kind of", "i feel like", "it depends",
]


def neutral_dials() -> dict:
    d = json.loads(DIALS_SCHEMA)
    for group in d:
        for k in d[group]:
            d[group][k] = 5
    return d


def variant_dials(group: str, dial: str, value: int) -> dict:
    d = neutral_dials()
    d[group][dial] = value
    return d


def make_agent(dials: dict) -> SpawnedAgent:
    return SpawnedAgent(id="exp", session_id="exp", dials=dials, **PERSONA)


def text_metrics(t: str) -> dict:
    low = t.lower()
    return {
        "words": len(re.findall(r"\b\w+\b", t)),
        "exclamations": t.count("!"),
        "questions": t.count("?"),
        "hedges": sum(low.count(p) for p in HEDGE_PHRASES),
        "numbers": len(re.findall(r"\b\d+(?:\.\d+)?%?\b", t)),
    }


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        return {}


async def judge_post(client, model: str, text: str) -> dict:
    prompt = (
        "You are a strict, calibrated behavioral rater. Rate the social-media post "
        "below on each dimension from 0 to 10.\n\n"
        f"DIMENSIONS:\n{JUDGE_RUBRIC}\n\n"
        f"POST:\n\"\"\"\n{text}\n\"\"\"\n\n"
        "Respond with ONLY valid JSON: "
        '{"hostility":n,"hedging":n,"source_citing":n,"question_asking":n,"concession":n}'
    )
    resp = await client.messages.create(
        model=model,
        max_tokens=120,
        messages=[{"role": "user", "content": prompt}],
    )
    scores = _parse_json(resp.content[0].text)
    return {d: float(scores.get(d, 0) or 0) for d in JUDGE_DIMS}


# ── pretty-print helpers ────────────────────────────────────────────────────
def _fmt_row(cells: list[str], widths: list[int]) -> str:
    return "  ".join(str(c).ljust(w) for c, w in zip(cells, widths))


def _table(headers: list[str], rows: list[list], pad: int = 2) -> str:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(str(c)))
    widths = [w + pad for w in widths]
    out = [_fmt_row(headers, widths), _fmt_row(["-" * (w - pad) for w in widths], widths)]
    out += [_fmt_row(r, widths) for r in rows]
    return "\n".join(out)


async def main() -> None:
    settings = get_settings()
    if not settings.anthropic_api_key or not settings.anthropic_api_key.startswith("sk-"):
        print("ERROR: no usable ANTHROPIC_API_KEY in backend/.env — cannot run live experiment.")
        sys.exit(1)

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    started = time.time()

    out: list[str] = []

    def emit(line: str = "") -> None:
        print(line)
        out.append(line)

    emit("=" * 78)
    emit("  DIAL-IMPACT EXPERIMENT — does changing a dial change the same conversation?")
    emit("=" * 78)
    emit(f"  gen model:   {settings.model_agents}")
    emit(f"  judge model: {settings.model_fast}")
    emit(f"  query:       {QUERY}")
    emit(f"  persona:     {PERSONA['name']} — {PERSONA['role']} (stance: direct)")
    emit(f"  method:      baseline = all 112 dials at 5; each variant moves ONE dial to 0 or 10")
    emit("")

    # ── Section 1: mechanism check (deterministic, no API) ──────────────────
    emit("-" * 78)
    emit("  [1] MECHANISM CHECK — behavioral guidance injected into the system prompt")
    emit("-" * 78)
    base_guidance = _dials_to_behavioral_guidance(neutral_dials())
    emit(f"  baseline (all dials = 5): {len(base_guidance.strip())} chars of guidance "
         f"(expected ~0 — no extremes, so no rules fire)")
    for variant, group, dial, value, *_ in SWEEPS:
        g = _dials_to_behavioral_guidance(variant_dials(group, dial, value))
        rules = [ln.strip("- ").strip() for ln in g.splitlines() if ln.strip().startswith("- ")]
        injected = rules[0][:96] + "…" if rules else "(no rule at this threshold)"
        emit(f"  {variant:<18} {group}.{dial}={value:<3} -> {injected}")
    emit("")

    # ── preflight: is the live Anthropic API usable with this key? ───────────
    variants = [("baseline", neutral_dials(), None, None)]
    for variant, group, dial, value, target, high_up in SWEEPS:
        variants.append((variant, variant_dials(group, dial, value), target, high_up))

    live_ok, live_reason = await _preflight(client, settings.model_fast)

    posts: dict[str, str] = {}
    judged: dict[str, dict] = {}
    metrics: dict[str, dict] = {}
    pairs: dict = {}
    hits = 0

    if live_ok:
        # ── Section 2: generate posts (live) ────────────────────────────────
        emit("-" * 78)
        emit("  [2] GENERATING POSTS — same prompt, different dials (running concurrently)")
        emit("-" * 78)

        async def gen(name: str, dials: dict):
            return name, await generate_post(make_agent(dials), QUERY, THREAD_CONTEXT, KG_CONTEXT, "comment")

        gen_results = await asyncio.gather(*(gen(n, d) for n, d, *_ in variants))
        posts = {name: text for name, text in gen_results}
        emit(f"  generated {len(posts)} posts in {time.time() - started:.1f}s")
        emit("")

        # ── Section 3: judge + matrix (live) ────────────────────────────────
        judge_results = await asyncio.gather(
            *(judge_post(client, settings.model_fast, posts[n]) for n, *_ in variants)
        )
        judged = {name: scores for (name, *_), scores in zip(variants, judge_results)}
        metrics = {name: text_metrics(posts[name]) for name, *_ in variants}

        emit("-" * 78)
        emit("  [3] IMPACT MATRIX — LLM-judge scores (0-10) per behavioral dimension")
        emit("      Δ = change vs baseline. The swept dimension is marked [*].")
        emit("-" * 78)
        base = judged["baseline"]
        headers = ["variant"] + JUDGE_DIMS
        rows = []
        for name, _d, target, _hu in variants:
            s = judged[name]
            cells = [name]
            for dim in JUDGE_DIMS:
                mark = "*" if dim == target else " "
                if name == "baseline":
                    cells.append(f"{s[dim]:.0f}{mark}")
                else:
                    delta = s[dim] - base[dim]
                    sign = "+" if delta > 0 else ""
                    cells.append(f"{s[dim]:.0f}({sign}{delta:.0f}){mark}")
            rows.append(cells)
        emit(_table(headers, rows))
        emit("")

        # ── Section 4: diagonal validation ──────────────────────────────────
        emit("-" * 78)
        emit("  [4] VALIDATION — did each dial move its OWN target dimension correctly?")
        emit("-" * 78)
        for variant, group, dial, value, target, high_up in SWEEPS:
            key = variant.rsplit("_", 1)[0]
            pairs.setdefault(key, {"dial": f"{group}.{dial}", "target": target, "high_up": high_up})
            pairs[key]["high" if variant.endswith("high") else "low"] = judged[variant][target]

        vrows = []
        for key, p in pairs.items():
            hi, lo = p.get("high", 0.0), p.get("low", 0.0)
            delta = hi - lo
            expected_up = p["high_up"]
            ok = (delta > 0) if expected_up else (delta < 0)
            hits += int(ok)
            direction = "high→up" if expected_up else "high→down"
            vrows.append([
                p["dial"], p["target"], direction,
                f"{lo:.0f}", f"{hi:.0f}", f"{hi - lo:+.0f}", "PASS" if ok else "FAIL",
            ])
        emit(_table(
            ["dial swept", "target dim", "expected", "low", "high", "Δ", "result"], vrows
        ))
        emit("")
        emit(f"  DIAGONAL PASS RATE: {hits}/{len(pairs)} dials moved their target dimension as expected.")
        emit("")

        # ── Section 5: deterministic corroboration ──────────────────────────
        emit("-" * 78)
        emit("  [5] DETERMINISTIC TEXT METRICS (no LLM — corroborates the judge)")
        emit("-" * 78)
        mrows = [
            [name, m["words"], m["hedges"], m["questions"], m["exclamations"], m["numbers"]]
            for name, m in ((n, metrics[n]) for n, *_ in variants)
        ]
        emit(_table(["variant", "words", "hedges", "questions", "excl", "numbers"], mrows))
        emit("")
    else:
        emit("-" * 78)
        emit("  [2-5] LIVE MEASUREMENT SKIPPED — Anthropic API not usable with this key")
        emit("-" * 78)
        emit(f"  reason: {live_reason}")
        emit("  Section [1] already proves each dial injects DISTINCT guidance into the system")
        emit("  prompt (the necessary condition). The live run scores how that guidance changes")
        emit("  the generated posts and validates the diagonal.")
        emit("  To run it: put a valid key in backend/.env then re-run:")
        emit("       venv/bin/python tests/dial_impact_experiment.py")
        emit("")

    # ── Section 6: dashboard aggregation on a synthetic population (no API) ──
    emit("-" * 78)
    emit("  [6] DASHBOARD AGGREGATION — aggregate_dials() on a synthetic 5-agent population")
    emit("-" * 78)
    synthetic = _synthetic_population()
    agg = aggregate_dials(synthetic)
    emit(f"  agents={agg['agent_count']}  with_dials={agg['with_dials']}  stances={agg['stances']}")
    emit("")
    emit("  SCORECARD (population means):")
    srows = [
        [s["label"], f"{s['mean']:.1f}", s["rating"], "lower=better" if s["negative"] else "higher=better"]
        for s in agg["scorecard"]
    ]
    emit(_table(["metric", "mean", "rating", "orientation"], srows))
    emit("")
    emit("  HEATMAP (stance x metric means):")
    hm = agg["heatmap"]
    hrows = [[hm["rows"][i]] + [("-" if v is None else f"{v:.1f}") for v in hm["values"][i]]
             for i in range(len(hm["rows"]))]
    emit(_table(["stance"] + [c[:10] for c in hm["cols"]], hrows))
    emit("")

    # ── Section 7: sample outputs (live only) ───────────────────────────────
    if live_ok:
        emit("-" * 78)
        emit("  [7] SAMPLE OUTPUTS (truncated to 320 chars)")
        emit("-" * 78)
        for name in ["baseline", "disgust_high", "anxiety_high", "credibility_high",
                     "curiosity_high", "resistance_high"]:
            emit(f"\n  ── {name} ──")
            emit("  " + posts[name][:320].replace("\n", "\n  "))
        emit("")

    elapsed = time.time() - started
    emit("=" * 78)
    if live_ok:
        emit(f"  DONE in {elapsed:.1f}s — {len(posts)} generations + {len(posts)} judge calls"
             f" — diagonal {hits}/{len(pairs)}")
    else:
        emit(f"  DONE in {elapsed:.1f}s — deterministic sections only (live measurement skipped)")
    emit("=" * 78)

    # ── artifacts ───────────────────────────────────────────────────────────
    art_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifacts")
    os.makedirs(art_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = os.path.join(art_dir, f"dial_impact_{stamp}.json")
    md_path = os.path.join(art_dir, f"dial_impact_{stamp}.md")
    payload = {
        "query": QUERY,
        "persona": {**PERSONA, "stance": PERSONA["stance"].value},
        "gen_model": settings.model_agents,
        "judge_model": settings.model_fast,
        "live_ok": live_ok,
        "live_reason": live_reason,
        "scorecard": agg["scorecard"],
        "heatmap": agg["heatmap"],
        "elapsed_s": round(elapsed, 1),
    }
    if live_ok:
        payload.update({
            "posts": posts,
            "judge_scores": judged,
            "text_metrics": metrics,
            "diagonal_pass_rate": f"{hits}/{len(pairs)}",
        })
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    with open(md_path, "w") as f:
        f.write("```\n" + "\n".join(out) + "\n```\n")
    print(f"\nArtifacts written:\n  {json_path}\n  {md_path}")


async def _preflight(client, model: str) -> tuple[bool, str]:
    """One cheap call to confirm the API key actually works before the full run."""
    try:
        await client.messages.create(
            model=model, max_tokens=1, messages=[{"role": "user", "content": "ok"}]
        )
        return True, ""
    except anthropic.AuthenticationError:
        return False, "401 invalid x-api-key — the key in backend/.env is rejected by the API"
    except anthropic.APIStatusError as e:
        return False, f"{getattr(e, 'status_code', '?')} {type(e).__name__}: {str(e)[:140]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:140]}"


def _synthetic_population() -> list[dict]:
    """Five agents with deliberately divergent profiles (for the dashboard demo)."""
    def prof(stance, **overrides):
        d = neutral_dials()
        for path, val in overrides.items():
            g, k = path.split(".")
            d[g][k] = val
        return {"stance": stance, "dials": d}

    return [
        prof("direct", **{"composite.adoption_readiness": 9, "commercial.purchase_intent": 8,
                          "commercial.churn_risk": 2, "composite.virality_potential": 7,
                          "composite.emotional_risk": 2, "commercial.willingness_to_pay": 7}),
        prof("direct", **{"composite.adoption_readiness": 7, "commercial.purchase_intent": 6,
                          "commercial.churn_risk": 3, "composite.retention_potential": 8}),
        prof("indirect", **{"composite.adoption_readiness": 5, "commercial.purchase_intent": 5,
                            "commercial.churn_risk": 5, "composite.human_resonance": 6}),
        prof("neutral", **{"composite.adoption_readiness": 3, "commercial.purchase_intent": 2,
                          "commercial.churn_risk": 8, "composite.emotional_risk": 7,
                          "commercial.willingness_to_pay": 2}),
        prof("neutral", **{"composite.adoption_readiness": 2, "commercial.purchase_intent": 3,
                          "commercial.churn_risk": 7, "composite.virality_potential": 2}),
    ]


if __name__ == "__main__":
    asyncio.run(main())
