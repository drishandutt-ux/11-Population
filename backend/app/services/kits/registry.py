"""Population kits: a published segmentation, turned into a ready population plan.

A kit (app/data/kits/<id>/kit.json) carries everything the Population Studio would otherwise
have to research and guess:
  - the segments, their shares (one or more named presets — the published shares, or the
    composition of a particular poll's sample), who is in each and how they think;
  - per segment, the distributions individual people are drawn from: age, gender, region,
    ethnicity, education, past vote — each with its source;
  - per segment, belief items with the share of the segment that holds each side, so every
    agent carries its OWN set of beliefs and a segment answers as a spread, not as one voice;
  - the population-wide sampling frame (GB targets) the roster is raked to.

`plan_from_kit` turns a kit into the plan a PopulationBuild stores: segments in the Studio's
shape plus, on each, the drawn `kit_cards` (one card per agent: the facts the persona writer
must honour). Drawing is seeded and stratified (largest remainder per category), so the same
kit and count give the same people, and a segment's mix matches its published mix as closely
as whole agents allow.

Nothing in a kit may come from a benchmark the population will be scored against — a kit
built from the answers it is graded on would be grading itself."""
from __future__ import annotations

import json
import os
import random
from typing import Any, Optional

KITS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "kits")


def list_kits() -> list[dict]:
    out = []
    if not os.path.isdir(KITS_DIR):
        return out
    for name in sorted(os.listdir(KITS_DIR)):
        k = load_kit(name)
        if k:
            out.append(summary(k))
    return out


def load_kit(kit_id: str) -> Optional[dict]:
    if not kit_id or "/" in kit_id or kit_id.startswith("."):
        return None
    path = os.path.join(KITS_DIR, kit_id, "kit.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        kit = json.load(f)
    kit["id"] = kit_id
    return kit


def summary(kit: dict) -> dict:
    return {
        "id": kit["id"], "title": kit.get("title"), "publisher": kit.get("publisher"), "population": kit.get("population"),
        "description": kit.get("description"), "year": kit.get("year"),
        "share_presets": {k: {"label": v.get("label"), "source": v.get("source")} for k, v in (kit.get("share_presets") or {}).items()},
        "default_preset": kit.get("default_preset"),
        "segments": [{"id": s["id"], "name": s["name"], "share_pct": s.get("share_pct"), "tagline": s.get("tagline", "")} for s in kit.get("segments") or []],
        "benchmarks": kit.get("benchmarks") or [],
    }


# ── stratified drawing ────────────────────────────────────────────────────────

def quota(dist: dict[str, float], n: int) -> list[str]:
    """n labels whose mix matches `dist` as closely as whole people allow (largest remainder)."""
    items = [(k, float(v)) for k, v in (dist or {}).items() if v and float(v) > 0]
    if not items or n <= 0:
        return []
    tot = sum(v for _, v in items)
    exact = [(k, n * v / tot) for k, v in items]
    counts = {k: int(e) for k, e in exact}
    for k, _ in sorted(exact, key=lambda kv: kv[1] - int(kv[1]), reverse=True)[: n - sum(counts.values())]:
        counts[k] += 1
    return [k for k, c in counts.items() for _ in range(c)]


def _shuffled(labels: list[str], rng: random.Random) -> list[str]:
    labels = list(labels)
    rng.shuffle(labels)
    return labels


def _age_in(band: str, rng: random.Random) -> int:
    """A whole age inside a band label like '25-40' or '75+'."""
    b = band.replace("–", "-").strip()
    if b.endswith("+"):
        lo = int(b[:-1])
        return rng.randint(lo, lo + 12)
    lo, hi = (int(x) for x in b.split("-")[:2])
    return rng.randint(lo, hi)


def draw_cards(kit: dict, seg: dict, n: int, *, seed: int = 0) -> list[dict]:
    """One card per agent in this segment: fixed facts and the beliefs this person holds."""
    rng = random.Random(f"{kit['id']}:{seg['id']}:{n}:{seed}")
    frame_defaults = kit.get("frame_defaults") or {}
    attrs = dict(frame_defaults)
    attrs.update(seg.get("distributions") or {})
    columns: dict[str, list[str]] = {}
    for key, spec in attrs.items():
        dist = spec.get("dist") if isinstance(spec, dict) and "dist" in spec else spec
        columns[key] = _shuffled(quota(dist, n), rng)
    # Beliefs: one latent "how typical of the segment" score per person, so a person who holds
    # the segment's view on one item tends to hold it on the next — real attitudes cohere —
    # with noise so nobody is a caricature. Each item still lands on its published share.
    latent = [rng.random() for _ in range(n)]
    beliefs: list[list[str]] = [[] for _ in range(n)]
    for item in seg.get("beliefs") or []:
        p = max(0.0, min(1.0, float(item.get("agree_pct") or 0) / 100.0))
        typical_is_agree = p >= 0.5                     # the side most of the segment is on
        k = round((p if typical_is_agree else 1 - p) * n)
        score = [latent[j] + rng.gauss(0, 0.35) for j in range(n)]
        typical = set(sorted(range(n), key=lambda j: -score[j])[:k])
        for j in range(n):
            agrees = (j in typical) == typical_is_agree
            text = item.get("agree") if agrees else item.get("disagree")
            if text:
                beliefs[j].append(text)
    cards = []
    for j in range(n):
        c: dict[str, Any] = {"slot": j + 1}
        for key, col in columns.items():
            if j < len(col):
                c[key] = col[j]
        if "age_band" in c:
            c["age"] = _age_in(c["age_band"], rng)
        c["beliefs"] = beliefs[j]
        c["typicality"] = round(latent[j], 2)
        cards.append(c)
    return cards


# ── kit → plan and frame ──────────────────────────────────────────────────────

def shares_for(kit: dict, preset: Optional[str]) -> tuple[str, dict[str, float]]:
    presets = kit.get("share_presets") or {}
    key = preset if preset in presets else kit.get("default_preset") or next(iter(presets), "")
    if key and presets.get(key):
        return key, {k: float(v) for k, v in presets[key]["shares"].items()}
    return "", {s["id"]: float(s.get("share_pct") or 0) for s in kit.get("segments") or []}


def frame_from_kit(kit: dict) -> Optional[dict]:
    """The kit's population-wide targets as a Studio sampling frame (status 'uploaded')."""
    dims, targets = [], {}
    for d in kit.get("frame") or []:
        dims.append({"key": d["key"], "label": d["label"], "attribute": d.get("attribute", "other"), "kind": "demographic",
                     "why": d.get("why", ""), "matchable": True})
        targets[d["key"]] = {"status": "uploaded", "categories": d["categories"], "source": d.get("source", kit.get("title", "kit")),
                             "year": d.get("year", ""), "geography": kit.get("population", ""), "proxy_attribute": "other",
                             "note": d.get("note", "from the population kit"), "provenance": "kit"}
    if not dims:
        return None
    return {"dimensions": dims, "targets": targets, "report": None, "geography": kit.get("population", ""), "sizing": None}


def plan_from_kit(kit: dict, count: int, *, preset: Optional[str] = None, seed: int = 0) -> dict:
    """The plan a PopulationBuild stores, with each segment's cards drawn."""
    from app.services.population.builder import normalise_segments

    preset_key, shares = shares_for(kit, preset)
    segs = []
    for s in kit.get("segments") or []:
        demo = s.get("plan_demographics") or {}
        segs.append({
            "id": s["id"], "name": s["name"], "share_pct": shares.get(s["id"], s.get("share_pct") or 0),
            "stance": "neutral", "description": s.get("summary", ""),
            "demographics": {"age_min": demo.get("age_min", 18), "age_max": demo.get("age_max", 90),
                             "gender_female_pct": demo.get("gender_female_pct", 50), "regions": demo.get("regions") or [],
                             "income_band": demo.get("income_band", "mixed"), "education": demo.get("education", "mixed"),
                             "occupations": demo.get("occupations") or []},
            "sentiment": {"mood": "mixed", "temperature": s.get("temperature", 5), "top_emotions": s.get("top_emotions") or []},
            "arguments": [q.get("quote") if isinstance(q, dict) else str(q) for q in (s.get("voice") or [])][:5],
            "evidence": [f"{e.get('finding')} ({e.get('source')})" for e in (s.get("evidence") or [])][:4],
            "rationale": f"Published segment: {s.get('tagline', s['name'])}",
            "humanity_hint": s.get("humanity_hint", "balanced"),
            "frame_values": {},
            "decision": "accepted",
            "reason": None,
            "kit": {"kit_id": kit["id"], "segment_id": s["id"]},
        })
    segs = normalise_segments(segs, count, {"demographics": {"age_min": 18, "age_max": 100}})
    for sg in segs:
        src = next(s for s in kit["segments"] if s["id"] == sg["id"])
        sg["kit_cards"] = draw_cards(kit, src, int(sg.get("count") or 0), seed=seed)
    return {
        "segments": segs,
        "rationale": f"{kit.get('title')}: {len(segs)} published segments at the '{preset_key}' shares. Each agent's age, gender, region, ethnicity, education, income and 2016 referendum vote are drawn from its segment's published mix, and each carries its own beliefs drawn from the segment's published shares.",
        "assumptions": list(kit.get("assumptions") or []),
        "evidence_coverage": kit.get("evidence_coverage", ""),
        "voice": {"auto": False, "value": 50, "reason": "Natural voices: the kit fixes who people are; register follows each segment."},
        "facets": [],
        "dynamic_dials": [],
        "kit": {"id": kit["id"], "title": kit.get("title"), "preset": preset_key, "seed": seed},
    }


def segment_kit(seg: dict) -> Optional[dict]:
    """The kit segment a plan segment was made from (for the persona writer)."""
    ref = seg.get("kit") or {}
    kit = load_kit(ref.get("kit_id", ""))
    if not kit:
        return None
    return next((s for s in kit.get("segments") or [] if s["id"] == ref.get("segment_id")), None)


def ensure_cards(plan: dict, segments: list[dict]) -> None:
    """Re-draw a kit segment's cards when its count no longer matches (a share was edited, or
    the population size changed at approve). Same kit, same seed: unchanged counts keep their people."""
    ref = (plan or {}).get("kit") or {}
    kit = load_kit(ref.get("id", ""))
    if not kit:
        return
    for sg in segments:
        kref = sg.get("kit") or {}
        if not kref or sg.get("decision") == "rejected":
            continue
        n = int(sg.get("count") or 0)
        if len(sg.get("kit_cards") or []) != n:
            src = next((s for s in kit.get("segments") or [] if s["id"] == kref.get("segment_id")), None)
            if src:
                sg["kit_cards"] = draw_cards(kit, src, n, seed=int(ref.get("seed") or 0))
