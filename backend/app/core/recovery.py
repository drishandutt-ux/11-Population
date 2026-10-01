"""Startup recovery for background jobs a restart killed.

Research runs and Population Studio builds run as in-process tasks. A redeploy (every push
to main restarts the backend) kills them mid-flight and leaves their rows saying "running",
so the UI shows a spinner forever — the Studio said "Research is finishing" for an hour after
the research task had died. On startup, every row still claiming to be in flight is marked
so, honestly, and a build that already has a plan stays buildable."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.core import database as dbm

RESEARCH_IN_FLIGHT = ("queued", "running", "stopping", "finalising")
BUILD_IN_FLIGHT = ("queued", "detecting", "gathering", "clarifying", "planning", "spawning")
# Lab runs (probes, their experiments) are in-process tasks too. One left "running" blocks the
# Journey page's *Refresh with amendments* button for good — it will not start a second amended
# run while one claims to be in flight (2026-10-01).
LAB_IN_FLIGHT = ("queued", "running")
LAB_INTERRUPTED = "Interrupted by a server restart (a redeploy). Answers already collected are kept; run it again."


async def recover_interrupted() -> dict:
    """Mark in-flight research runs `interrupted`, in-flight Studio builds `stopped` (with a
    log line), and in-flight Lab probes and experiments `failed` with the reason. Returns counts
    for the startup log."""
    from app.models.evidence import ResearchRun
    from app.models.measurement import Experiment, Probe
    from app.models.population import PopulationBuild

    counts = {"research_runs": 0, "population_builds": 0, "probes": 0, "experiments": 0}
    now = datetime.utcnow()
    async with dbm.AsyncSessionLocal() as db:
        runs = (await db.execute(select(ResearchRun).where(ResearchRun.status.in_(RESEARCH_IN_FLIGHT)))).scalars().all()
        for r in runs:
            r.status = "interrupted"
            r.note = "Interrupted by a server restart. What was gathered is kept; press Run again to continue."
            r.finished_at = now
            counts["research_runs"] += 1
        builds = (await db.execute(select(PopulationBuild).where(PopulationBuild.status.in_(BUILD_IN_FLIGHT)))).scalars().all()
        for b in builds:
            was = b.status
            b.status = "stopped"
            b.log = list(b.log or []) + [{
                "ts": now.isoformat() + "Z", "stage": was, "level": "warn",
                "message": "Interrupted by a server restart",
                "detail": ("The plan on file can still be approved and built." if b.plan else "Start a new plan; what was gathered is kept."),
            }]
            b.updated_at = now
            counts["population_builds"] += 1
        probes = (await db.execute(select(Probe).where(Probe.status.in_(LAB_IN_FLIGHT)))).scalars().all()
        for p in probes:
            p.status = "failed"
            p.error = LAB_INTERRUPTED
            p.completed_at = now
            counts["probes"] += 1
        exps = (await db.execute(select(Experiment).where(Experiment.status.in_(LAB_IN_FLIGHT)))).scalars().all()
        for e in exps:
            e.status = "failed"
            e.error = LAB_INTERRUPTED
            e.completed_at = now
            counts["experiments"] += 1
        await db.commit()
    return counts
