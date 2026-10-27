"""The bin for deleted sessions (2026-10-22).

Deleting a session only stamps `deleted_at`: it disappears from every list and page, and the
owner can restore it from *Recently deleted* for TRASH_DAYS. After that the daily purge removes
it for good — the row (and everything hanging off it, as the old hard delete did) and its
knowledge graph. *Delete forever* in the bin does the same at once."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core import database as dbm

TRASH_DAYS = 30
PURGE_EVERY_SEC = 6 * 3600


def purge_at(deleted_at: datetime | None) -> datetime | None:
    return deleted_at + timedelta(days=TRASH_DAYS) if deleted_at else None


async def hard_delete(db, session) -> None:
    """Remove a session for good (what DELETE did before the bin)."""
    sid = session.id
    await db.delete(session)
    await db.commit()
    from app.services.knowledge_graph.lightrag_service import forget
    forget(sid)


async def purge_expired(now: datetime | None = None) -> int:
    """Hard-delete every session that has sat in the bin longer than TRASH_DAYS. Returns the count."""
    from app.models.session import AnalysisSession
    cutoff = (now or datetime.utcnow()) - timedelta(days=TRASH_DAYS)
    n = 0
    async with dbm.AsyncSessionLocal() as db:
        rows = (await db.execute(select(AnalysisSession).where(AnalysisSession.deleted_at.is_not(None), AnalysisSession.deleted_at < cutoff))).scalars().all()
        for s in rows:
            try:
                await hard_delete(db, s)
                n += 1
            except Exception as e:  # noqa: BLE001 — one stuck row must not stop the rest
                await db.rollback()
                print(f"[trash] could not purge {s.id}: {type(e).__name__}: {e}")
    return n


async def purge_loop(stop: "asyncio.Event | None" = None) -> None:
    """Runs for the life of the server: purge on startup, then every PURGE_EVERY_SEC.

    `stop` ends it at shutdown. A cancel alone is not enough: one that lands while a purge is
    closing a pooled connection is swallowed by the database driver, the purge then fails as an
    ordinary error, and the loop went back to sleep for hours with the server waiting on it."""
    while not (stop and stop.is_set()):
        try:
            n = await purge_expired()
            if n:
                print(f"[trash] purged {n} session(s) deleted more than {TRASH_DAYS} days ago")
        except Exception as e:  # noqa: BLE001
            print(f"[trash] purge failed: {type(e).__name__}: {e}")
        if stop is None:
            await asyncio.sleep(PURGE_EVERY_SEC)
            continue
        try:
            await asyncio.wait_for(stop.wait(), PURGE_EVERY_SEC)
        except asyncio.TimeoutError:
            pass
