"""Public benchmarks (2026-10-27): SimBench grouped, run from the admin page.

A run builds hundreds of subgroup lineups and spends real money, so every route is admin only and
a second run cannot start while one is in flight."""
from __future__ import annotations

import csv
import io
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.core.auth import AuthUser, require_admin
from app.core.database import get_db
from app.models.benchmark import BenchmarkRun
from app.services.kits import simbench
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["benchmarks"])

IN_FLIGHT = ("queued", "running", "stopping")


class SimBenchRunRequest(BaseModel):
    cases: int = simbench.DEFAULT_CASES
    twins: int = simbench.DEFAULT_TWINS
    mode: str = "fast"
    seed: Optional[int] = None
    parallel_groups: int = simbench.DEFAULT_PARALLEL_GROUPS
    bare: bool = True
    groups_limit: int = 0


def _clean_mode(mode: str) -> str:
    return "pro" if mode == "pro" else "fast"


@router.get("/admin/benchmarks/simbench")
async def simbench_overview(admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """The subset on file, a default estimate, and every run (newest first)."""
    runs = (await db.execute(select(BenchmarkRun).where(BenchmarkRun.benchmark == simbench.BENCHMARK_ID)
                             .order_by(BenchmarkRun.created_at.desc()).limit(20))).scalars().all()
    counts = simbench.plan_counts()
    return {"subset": simbench.subset_overview(),
            "estimate": {**counts, **simbench.estimate(counts["cases"], counts["groups"], simbench.DEFAULT_TWINS, "fast")},
            "runs": [await simbench.run_payload(r) for r in runs]}


@router.get("/admin/benchmarks/simbench/estimate")
async def simbench_estimate(cases: int = simbench.DEFAULT_CASES, twins: int = simbench.DEFAULT_TWINS, mode: str = "fast",
                            groups_limit: int = 0, admin: AuthUser = Depends(require_admin)):
    counts = simbench.plan_counts(cases, groups_limit)
    twins = max(10, min(200, int(twins)))
    return {**counts, "twins": twins, **simbench.estimate(counts["cases"], counts["groups"], twins, _clean_mode(mode))}


@router.post("/admin/benchmarks/simbench/runs")
async def simbench_start(body: SimBenchRunRequest, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    busy = (await db.execute(select(BenchmarkRun.id).where(BenchmarkRun.status.in_(IN_FLIGHT)))).scalars().first()
    if busy:
        raise HTTPException(409, "A benchmark run is already in progress — stop it or wait for it to finish.")
    try:
        run = await simbench.start(None if admin.is_dev else admin.id, cases=body.cases, twins=body.twins, mode=_clean_mode(body.mode),
                                   seed=body.seed, parallel_groups=body.parallel_groups, bare=body.bare, groups_limit=body.groups_limit)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except OSError as e:
        raise HTTPException(502, f"Could not fetch the SimBench data: {e}")
    return await simbench.run_payload(run)


async def _get(db: AsyncSession, run_id: str) -> BenchmarkRun:
    run = await db.get(BenchmarkRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.get("/admin/benchmarks/simbench/runs/{run_id}")
async def simbench_run(run_id: str, cases: bool = False, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await simbench.run_payload(await _get(db, run_id), with_cases=cases)


@router.post("/admin/benchmarks/simbench/runs/{run_id}/stop")
async def simbench_stop(run_id: str, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    await _get(db, run_id)
    if not await simbench.stop(run_id):
        raise HTTPException(409, "This run is not running.")
    return {"ok": True}


@router.post("/admin/benchmarks/simbench/runs/{run_id}/resume")
async def simbench_resume(run_id: str, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    await _get(db, run_id)
    busy = (await db.execute(select(BenchmarkRun.id).where(BenchmarkRun.status.in_(IN_FLIGHT), BenchmarkRun.id != run_id))).scalars().first()
    if busy:
        raise HTTPException(409, "Another benchmark run is in progress.")
    if not await simbench.resume(run_id):
        raise HTTPException(409, "This run cannot be resumed (it is running or already complete).")
    return await simbench.run_payload(await _get(db, run_id))


@router.get("/admin/benchmarks/simbench/runs/{run_id}/cases.csv")
async def simbench_cases_csv(run_id: str, admin: AuthUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Every scored case — the human distribution beside the twins' and the bare model's — for
    publishing the run alongside its summary."""
    run = await _get(db, run_id)
    state = run.state or {}
    groups = state.get("groups") or {}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["case_id", "dataset", "group", "status", "answers", "refused", "score_twins_likelihood", "score_twins_draws", "score_bare",
                "twins_likelihood", "twins_draws", "bare", "error"])
    for cid, c in sorted((state.get("cases") or {}).items(), key=lambda kv: int(kv[0])):
        sc = c.get("scores") or {}
        w.writerow([cid, c.get("dataset"), (groups.get(c.get("group_id")) or {}).get("title", ""), c.get("status"), c.get("answers"), c.get("refused"),
                    (sc.get("likelihood") or {}).get("score"), (sc.get("draws") or {}).get("score"), (sc.get("bare") or {}).get("score"),
                    json.dumps(c.get("twins_likelihood")), json.dumps(c.get("twins_draws")), json.dumps(c.get("bare")), c.get("error") or ""])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="simbench-{run_id[:8]}.csv"'})
