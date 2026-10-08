"""Start a Population Studio build from a kit instead of from research.

The kit replaces detect, gather, frame and plan: the build is created already planned (status
awaiting_review, every segment accepted), with the kit's sampling frame and each segment's
drawn cards. The analyst reviews it like any plan — or it is approved straight away — and the
ordinary approve → spawn path writes the personas (agent_factory routes kit segments to the
kit writer)."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select

from app.core import database as dbm
from app.models.population import PopulationBuild
from app.services.kits import registry
from app.services.population import builder


async def start_kit_build(session_id: str, kit_id: str, *, count: int, mode: str = "fast", preset: Optional[str] = None,
                          seed: int = 0, approve: bool = False) -> PopulationBuild:
    kit = registry.load_kit(kit_id)
    if not kit:
        raise ValueError(f"Unknown population kit '{kit_id}'")
    count = max(len(kit.get("segments") or []), min(1000, int(count or 100)))
    plan = registry.plan_from_kit(kit, count, preset=preset, seed=seed)
    frame = registry.frame_from_kit(kit)
    async with dbm.AsyncSessionLocal() as db:
        for o in (await db.execute(select(PopulationBuild).where(PopulationBuild.session_id == session_id, PopulationBuild.status.in_(list(builder.ACTIVE))))).scalars().all():
            o.status = "stopped"
            builder._stop[o.id] = True
        bld = PopulationBuild(id=str(uuid.uuid4()), session_id=session_id, status="awaiting_review", mode="pro" if mode == "pro" else "fast",
                              target_count=count, constraints={"kit": {"id": kit_id, "preset": plan["kit"]["preset"], "seed": seed}},
                              sources={}, questions=[], log=[], plan=plan, frame=frame,
                              detected={"topic": kit.get("title"), "target_population": kit.get("population"), "population_kind": "general public",
                                        "geography": kit.get("population"), "confidence": 100, "decision": "From a published segmentation kit"})
        db.add(bld)
        await db.commit()
        await db.refresh(bld)
    preset_label = ((kit.get("share_presets") or {}).get(plan["kit"]["preset"]) or {}).get("label") or plan["kit"]["preset"]
    await builder.log(bld.id, "plan", "decision", f"Population kit: {kit.get('title')}", kit.get("description"))
    await builder.log(bld.id, "plan", "info", f"Segment shares: {preset_label}", ((kit.get("share_presets") or {}).get(plan["kit"]["preset"]) or {}).get("source"))
    for sg in plan["segments"]:
        cards = sg.get("kit_cards") or []
        await builder.log(bld.id, "plan", "info", f"{sg['name']} — {sg['share_pct']}% ({sg['count']} agents)",
                          _mix_line(cards))
    if frame:
        await builder.log(bld.id, "frame", "ok", "Sampling frame from the kit: " + ", ".join(d["label"] for d in frame["dimensions"]),
                          " · ".join(f"{d['label']}: {frame['targets'][d['key']].get('source')}" for d in frame["dimensions"]))
    for a in (plan.get("assumptions") or [])[:6]:
        await builder.log(bld.id, "plan", "warn", f"Assumed: {a}")
    await builder.log(bld.id, "plan", "ok", f"Plan ready from the kit: {len(plan['segments'])} segments for {count} agents.", plan.get("evidence_coverage"))
    await builder.refresh_frame_report(bld.id)
    if approve:
        bld = await builder.approve(bld.id) or bld
    return bld


def _mix_line(cards: list[dict]) -> str:
    """One line on what was drawn for a segment: age bands, gender and past vote."""
    if not cards:
        return ""
    n = len(cards)
    parts = []
    for key, label in (("age_band", "age"), ("gender", "gender"), ("ge2019", "2019 vote"), ("education", "education")):
        vals: dict[str, int] = {}
        for c in cards:
            if c.get(key):
                vals[c[key]] = vals.get(c[key], 0) + 1
        if vals:
            parts.append(f"{label}: " + ", ".join(f"{k} {round(100 * v / n)}%" for k, v in sorted(vals.items(), key=lambda kv: -kv[1])[:4]))
    return " · ".join(parts)
