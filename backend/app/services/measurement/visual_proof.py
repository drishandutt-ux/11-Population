"""The proof behind a new version (the Visual Lab, 2026-10-27): every remake is re-shown to the
same twins who judged its parent, and the paired shift is the result that travels with the image.

A chatbot can produce a poster. It cannot say *this version moved 23 of the 61 people the last one
did not work on, and lost 4 of the 39 it did*. That number is what the population is for, so a
remake does not end with a picture: when it is ready, a Visuals run is started on it with the
parent run's question, setting and twins (the ones who actually answered), each twin answering
blind to what it said about the parent (the runner hides earlier Visuals answers on a re-test,
the way an A/B arm hides its siblings). When that run finishes the two sets of answers are paired
by twin and the shift is counted: who it won, who it lost, by how much, in which segments, and in
the movers' own words. The proof sits on the child image's brief and on the re-test run.
"""
from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select

from app.core import database as _db
from app.models.agent import SpawnedAgent
from app.models.measurement import Probe, ProbeAnswer, SessionImage
from app.services.evidence.llm import clip
from app.services.measurement import images as images_mod
from app.services.measurement import stats
from app.services.measurement.probe import answered, prompt_hash, run_probe, segments_for, split_keys

MAX_MOVERS = 12
RETEST_KEY = "retest"


def _yes(answer: dict) -> float:
    return 1.0 if answer.get("verdict") == "yes" else 0.0


async def _rows(session_id: str, probe_id: str) -> dict[str, dict]:
    """{agent_id: {agent, answer, segments}} for one run, refusals left out."""
    async with _db.AsyncSessionLocal() as db:
        pairs = (await db.execute(
            select(ProbeAnswer, SpawnedAgent)
            .join(SpawnedAgent, SpawnedAgent.id == ProbeAnswer.agent_id, isouter=True)
            .where(ProbeAnswer.probe_id == probe_id, ProbeAnswer.session_id == session_id)
        )).all()
    out: dict[str, dict] = {}
    for a, ag in pairs:
        if not answered({"answer": a.answer or {}}):
            continue
        out[a.agent_id] = {
            "agent": {"name": getattr(ag, "name", ""), "role": getattr(ag, "role", ""), "weight": float(getattr(ag, "weight", None) or 1.0)},
            "answer": a.answer or {},
            "segments": segments_for(ag) if ag else {},
        }
    return out


async def start_retest(child_id: str) -> Optional[str]:
    """Queue the re-test run for a ready remake. Returns the probe id, or None when there is no
    parent run to pair with (an image remade from a typed change on an image never shown)."""
    async with _db.AsyncSessionLocal() as db:
        child = await db.get(SessionImage, child_id)
        if not child or child.status != "ready":
            return None
        brief = dict(child.brief or {})
        parent_probe_id = brief.get("reactions_probe_id") or brief.get("probe_id")
        parent_probe = await db.get(Probe, parent_probe_id) if parent_probe_id else None
        if not parent_probe or parent_probe.session_id != child.session_id or not (parent_probe.aggregates or {}).get("n"):
            return None
        agent_ids = sorted({a for (a,) in (await db.execute(
            select(ProbeAnswer.agent_id).where(ProbeAnswer.probe_id == parent_probe.id)
        )).all()})
        if not agent_ids:
            return None
        pspec = dict(parent_probe.spec or {})
        spec: dict[str, Any] = {
            images_mod.IMAGES_KEY: [{"id": child.id, "label": child.label or "new version"}],
            "question": pspec.get("question") or "",
            "agent_filter": {"agent_ids": agent_ids},
            "seed": int(parent_probe.seed or 0),
            RETEST_KEY: {"image_id": child.id, "parent_image_id": child.parent_id, "parent_probe_id": parent_probe.id},
        }
        if pspec.get("setting"):
            spec["setting"] = pspec["setting"]
        if isinstance(pspec.get("context"), dict):
            spec["context"] = pspec["context"]
        from app.services.measurement import instruments
        inst = instruments.get("visual")
        probe = Probe(
            session_id=child.session_id, instrument="visual", schema_id=inst.schema_id(), spec=spec, seed=spec["seed"],
            model=str(brief.get("model") or parent_probe.model or ""), prompt_hash=prompt_hash(inst, spec), status="queued",
        )
        db.add(probe)
        await db.flush()
        brief[RETEST_KEY] = {"probe_id": probe.id, "parent_probe_id": parent_probe.id, "status": "running", "agents": len(agent_ids),
                             "started_at": datetime.utcnow().isoformat()}
        child.brief = brief
        await db.commit()
        return probe.id


async def run_retest(child_id: str, probe_id: str) -> None:
    """Background: run the re-test, then count the shift and store it on the child."""
    try:
        await run_probe(probe_id)
        proof = await compute_proof(child_id, probe_id)
        async with _db.AsyncSessionLocal() as db:
            child = await db.get(SessionImage, child_id)
            probe = await db.get(Probe, probe_id)
            if child:
                brief = dict(child.brief or {})
                brief[RETEST_KEY] = {**(brief.get(RETEST_KEY) or {}), "status": "complete" if proof else "failed",
                                     "finished_at": datetime.utcnow().isoformat()}
                if proof:
                    brief["proof"] = proof
                child.brief = brief
            if probe and proof:
                agg = dict(probe.aggregates or {})
                agg["proof"] = proof
                probe.aggregates = agg
            await db.commit()
        print(f"[visual_proof] {child_id}: {(proof or {}).get('sentence', 'no proof')[:140]}")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        async with _db.AsyncSessionLocal() as db:
            child = await db.get(SessionImage, child_id)
            if child:
                brief = dict(child.brief or {})
                brief[RETEST_KEY] = {**(brief.get(RETEST_KEY) or {}), "status": "failed", "error": f"{type(e).__name__}: {str(e)[:200]}"}
                child.brief = brief
                await db.commit()


def pair_and_count(before: dict[str, dict], after: dict[str, dict], *, seed: int = 0, expected: str = "") -> Optional[dict]:
    """The shift between two sets of answers, paired by twin. Pure; the tests drive it directly."""
    ids = sorted(set(before) & set(after))
    if not ids:
        return None
    won: list[str] = []      # no / mixed → yes
    lost: list[str] = []     # yes → no / mixed
    held_yes: list[str] = []
    held_no: list[str] = []
    for aid in ids:
        b, a = before[aid]["answer"], after[aid]["answer"]
        if b.get("verdict") == "yes":
            (held_yes if a.get("verdict") == "yes" else lost).append(aid)
        else:
            (won if a.get("verdict") == "yes" else held_no).append(aid)
    rejecters = len(won) + len(held_no)
    believers = len(lost) + len(held_yes)
    lift = stats.paired_lift([(_yes(before[i]["answer"]), _yes(after[i]["answer"])) for i in ids], seed=seed)
    feeling = stats.paired_lift([(float(before[i]["answer"].get("feeling") or 0), float(after[i]["answer"].get("feeling") or 0)) for i in ids], seed=seed)
    strength = stats.paired_lift([(float(before[i]["answer"].get("strength") or 0), float(after[i]["answer"].get("strength") or 0)) for i in ids], seed=seed)
    b_yes = stats.wilson(believers, len(ids))
    a_yes = stats.wilson(len(won) + len(held_yes), len(ids))

    # By segment: the same count inside every bucket, so a gain for one group that is a loss for
    # another is visible — that trade-off is the thing a single consensus version hides.
    rows = [{"agent_id": i, "segments": after[i].get("segments") or {}} for i in ids]
    by_segment: dict[str, list[dict]] = {}
    for key in split_keys(rows):
        buckets: dict[str, list[str]] = {}
        for r in rows:
            label = (r["segments"] or {}).get(key)
            if label is not None:
                buckets.setdefault(str(label), []).append(r["agent_id"])
        out = []
        for label, members in buckets.items():
            m_won = [i for i in members if i in won]
            m_lost = [i for i in members if i in lost]
            m_before = sum(1 for i in members if before[i]["answer"].get("verdict") == "yes")
            m_after = sum(1 for i in members if after[i]["answer"].get("verdict") == "yes")
            seg_lift = stats.paired_lift([(_yes(before[i]["answer"]), _yes(after[i]["answer"])) for i in members], seed=seed, iterations=600)
            out.append({"value": label, "n": len(members), "thin": len(members) < 3,
                        "before": round(m_before / len(members), 4), "after": round(m_after / len(members), 4),
                        "won": len(m_won), "lost": len(m_lost), "lift": seg_lift["mean"], "low": seg_lift["low"], "high": seg_lift["high"],
                        "significant": seg_lift["significant"]})
        out.sort(key=lambda d: (-d["n"], d["value"]))
        if len(out) >= 2:
            by_segment[key] = out

    def mover(aid: str, kind: str) -> dict:
        b, a = before[aid]["answer"], after[aid]["answer"]
        return {"agent_id": aid, "name": before[aid]["agent"].get("name", ""), "role": before[aid]["agent"].get("role", ""), "kind": kind,
                "from": b.get("verdict"), "to": a.get("verdict"),
                "before_put_off": clip(str(b.get("put_off") or ""), 120), "after_put_off": clip(str(a.get("put_off") or ""), 120),
                "before_reasoning": clip(str(b.get("reasoning") or ""), 220), "after_reasoning": clip(str(a.get("reasoning") or ""), 220),
                "segments": after[aid].get("segments") or {}}
    movers = [mover(i, "won") for i in won[: MAX_MOVERS - min(4, len(lost))]] + [mover(i, "lost") for i in lost[:4]]

    # Where the change paid and where it cost: the solid buckets with the biggest gain and loss.
    best = max((b_ for rows_ in by_segment.values() for b_ in rows_ if not b_["thin"]), key=lambda d: d["lift"], default=None)
    worst = min((b_ for rows_ in by_segment.values() for b_ in rows_ if not b_["thin"]), key=lambda d: d["lift"], default=None)
    verdict = "won" if lift["significant"] and lift["mean"] > 0 else "lost" if lift["significant"] and lift["mean"] < 0 else "flat"
    pts = round(lift["mean"] * 100)
    sentence = (
        f"Tested on the same {len(ids)} twins. "
        + (f"Moved {len(won)} of the {rejecters} it did not work on" if rejecters else "Nobody rejected the original")
        + (f"; lost {len(lost)} of the {believers} it did. " if believers else ". ")
        + f"Works on them {stats.pct(b_yes['share'])} → {stats.pct(a_yes['share'])}, {pts:+d} points "
        + f"(95% CI {round(lift['low'] * 100):+d} to {round(lift['high'] * 100):+d})"
        + ("." if verdict != "flat" else " — not a reliable change.")
    )
    trade = ""
    if best and worst and best is not worst and worst["lift"] < 0 < best["lift"]:
        trade = (f"Paid most with {best['value']} ({round(best['lift'] * 100):+d} pts, n={best['n']}); "
                 f"cost with {worst['value']} ({round(worst['lift'] * 100):+d} pts, n={worst['n']}).")
    elif best and best["lift"] > 0:
        trade = f"Paid most with {best['value']} ({round(best['lift'] * 100):+d} pts, n={best['n']}); no solid group moved the other way."
    return {
        "n_paired": len(ids),
        "before": b_yes, "after": a_yes,
        "won": len(won), "lost": len(lost), "held_yes": len(held_yes), "held_no": len(held_no),
        "rejecters": rejecters, "believers": believers,
        "lift": lift, "feeling_lift": feeling, "strength_lift": strength,
        "verdict": verdict,
        "by_segment": by_segment,
        "movers": movers,
        "expected": expected or "",
        "sentence": sentence,
        "trade_off": trade,
        "counted_at": datetime.utcnow().isoformat(),
    }


async def compute_proof(child_id: str, probe_id: str) -> Optional[dict]:
    async with _db.AsyncSessionLocal() as db:
        child = await db.get(SessionImage, child_id)
        probe = await db.get(Probe, probe_id)
        if not child or not probe:
            return None
        parent_probe_id = ((probe.spec or {}).get(RETEST_KEY) or {}).get("parent_probe_id")
        brief = dict(child.brief or {})
        expected = str(((brief.get("proposal") or {}).get("expected")) or "")
        seed = int(probe.seed or 0)
        session_id = child.session_id
    if not parent_probe_id:
        return None
    before = await _rows(session_id, parent_probe_id)
    after = await _rows(session_id, probe_id)
    proof = pair_and_count(before, after, seed=seed, expected=expected)
    if proof:
        proof["probe_id"] = probe_id
        proof["parent_probe_id"] = parent_probe_id
        proof["image_id"] = child_id
    return proof
