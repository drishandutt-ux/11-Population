"""Population kits and benchmarks.

Kits: published segmentations that build a population directly (no research or planning step).
Benchmarks: a real poll's results, its questionnaire as a ready Forms survey, and the score of
a finished survey run against the poll — per question, per segment, per demographic cut."""
from __future__ import annotations

import random
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, get_current_user, get_owned_session
from app.core.database import get_db
from app.models.agent import SpawnedAgent
from app.models.measurement import Probe, ProbeAnswer
from app.services.kits import benchmark as bench_svc
from app.services.kits import registry
from app.services.population import builder

router = APIRouter(tags=["kits"])


class KitBuildRequest(BaseModel):
    kit_id: str
    count: int = 200
    mode: str = "fast"                      # fast (Haiku) | pro (Sonnet) writes the personas
    preset: Optional[str] = None            # which segment shares (the kit's share_presets)
    seed: int = 0
    approve: bool = False                   # build the agents straight away instead of stopping at review


class BenchmarkRunRequest(BaseModel):
    mode: str = "fast"
    seed: Optional[int] = None


@router.get("/kits")
async def list_kits(user: AuthUser = Depends(get_current_user)):
    return {"kits": registry.list_kits(), "benchmarks": bench_svc.list_benchmarks()}


@router.get("/kits/{kit_id}")
async def get_kit(kit_id: str, user: AuthUser = Depends(get_current_user)):
    kit = registry.load_kit(kit_id)
    if not kit:
        raise HTTPException(404, "Unknown population kit")
    return kit


@router.post("/sessions/{session_id}/population/kit")
async def build_from_kit(session_id: str, body: KitBuildRequest, user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Create a population build from a kit: planned already, every segment accepted, the
    kit's frame attached. With approve=true the agents are written straight away."""
    await get_owned_session(session_id, user, db)
    from app.services.kits.apply import start_kit_build
    try:
        bld = await start_kit_build(session_id, body.kit_id, count=body.count, mode=body.mode, preset=body.preset, seed=body.seed, approve=body.approve)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return builder.build_payload(bld)


@router.get("/benchmarks/{benchmark_id}/form")
async def benchmark_form(benchmark_id: str, user: AuthUser = Depends(get_current_user)):
    form = bench_svc.load_form(benchmark_id)
    if not form:
        raise HTTPException(404, "Unknown benchmark")
    return form


@router.post("/sessions/{session_id}/benchmarks/{benchmark_id}/run")
async def run_benchmark(session_id: str, benchmark_id: str, body: BenchmarkRunRequest, background_tasks: BackgroundTasks,
                        user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Put the benchmark's questionnaire to every agent in the session, as a Forms survey."""
    await get_owned_session(session_id, user, db)
    form = bench_svc.load_form(benchmark_id)
    if not form:
        raise HTTPException(404, "Unknown benchmark")
    from app.api.v1.measurement import ProbeRequest, create_probe
    spec = {**form, "benchmark_id": benchmark_id}
    return await create_probe(session_id, ProbeRequest(instrument="survey", spec=spec, mode=body.mode, seed=body.seed if body.seed is not None else random.randint(1, 2**31 - 1)),
                              background_tasks, user, db)


@router.get("/sessions/{session_id}/probes/{probe_id}/benchmark")
async def score_probe_auto(session_id: str, probe_id: str, min_n: int = 5, estimator: str = "auto",
                           user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The scorecard against whichever real poll this run's form reproduces (404 when none)."""
    await get_owned_session(session_id, user, db)
    p = await db.get(Probe, probe_id)
    if not p or p.session_id != session_id:
        raise HTTPException(404, "Probe not found")
    bid = bench_svc.match(p.spec or {})
    if not bid:
        raise HTTPException(404, "This run does not reproduce a real poll on file")
    return await score_probe(session_id, probe_id, bid, min_n=min_n, estimator=estimator, user=user, db=db)


@router.get("/sessions/{session_id}/probes/{probe_id}/benchmark/{benchmark_id}")
async def score_probe(session_id: str, probe_id: str, benchmark_id: str, min_n: int = 5, estimator: str = "auto",
                      user: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The scorecard: a finished survey run against the real poll it reproduces."""
    await get_owned_session(session_id, user, db)
    p = await db.get(Probe, probe_id)
    if not p or p.session_id != session_id:
        raise HTTPException(404, "Probe not found")
    bench = bench_svc.load(benchmark_id)
    if not bench:
        raise HTTPException(404, "Unknown benchmark")
    rows = (await db.execute(
        select(ProbeAnswer, SpawnedAgent).join(SpawnedAgent, SpawnedAgent.id == ProbeAnswer.agent_id, isouter=True)
        .where(ProbeAnswer.probe_id == probe_id)
    )).all()
    responses = [{"answer": a.answer or {}, "segment": getattr(ag, "segment", "") or "", "age": getattr(ag, "age", None),
                  "demographics": getattr(ag, "demographics", None) or {}, "weight": getattr(ag, "weight", None) or 1.0}
                 for a, ag in rows if a.answer]
    if not responses:
        raise HTTPException(400, "This run has no answers yet.")
    out = bench_svc.score(bench, responses, min_n=max(1, min_n), estimator=estimator if estimator in ("auto", "draws", "likelihood") else "auto")
    out["probe_id"] = probe_id
    out["benchmark_title"] = bench.get("title")
    out["fieldwork"] = (bench.get("method") or {}).get("Fieldwork dates")
    out["sample"] = (bench.get("method") or {}).get("Sample size")
    return out
