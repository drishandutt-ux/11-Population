import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.database import create_tables
from app.core.redis_client import subscribe, unsubscribe, session_channel
from app.api.v1 import sessions, ingestion, simulation, agents, reports, presets, users, research, measurement


#: Why the schema is not up to date, if it isn't. Surfaced on /health — a failed migration
#: used to be a printed warning only, while /health still said the database was fine, so a
#: missing table looked like a working deploy until the first request touched it.
SCHEMA_ERROR: "str | None" = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global SCHEMA_ERROR
    try:
        await create_tables()
        SCHEMA_ERROR = None
        print("[startup] Database tables ready.")
    except Exception as e:
        SCHEMA_ERROR = f"{type(e).__name__}: {str(e)[:300]}"
        print(f"[startup] WARNING: create_tables() failed: {e}")
        print("[startup] App will start anyway — DB errors will surface per-request.")
    yield


app = FastAPI(title="11 Minds Army", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """Return JSON 500s from inside the middleware stack so CORS headers are attached. Without
    this, an unhandled error reached the browser with no CORS headers and showed up as
    "Couldn't reach the server" instead of the real message."""
    import traceback
    traceback.print_exception(type(exc), exc, exc.__traceback__)
    return JSONResponse(status_code=500, content={"detail": f"Server error: {type(exc).__name__}: {str(exc)[:300]}"})


app.include_router(sessions.router, prefix="/api/v1")
app.include_router(ingestion.router, prefix="/api/v1")
app.include_router(simulation.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(presets.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(research.router, prefix="/api/v1")
app.include_router(measurement.router, prefix="/api/v1")


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Live events for one session. With auth on, the client passes its Supabase access
    token as `?token=`; the socket is refused (4401/4404) unless the token is valid and the
    session belongs to that user."""
    from app.core.auth import user_from_ws_token, owns
    from app.core.database import AsyncSessionLocal
    from app.models.session import AnalysisSession
    from sqlalchemy import select

    user = await user_from_ws_token(websocket.query_params.get("token"))
    if user is None:
        await websocket.close(code=4401)
        return
    async with AsyncSessionLocal() as db:
        sess = (await db.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))).scalar_one_or_none()
    if sess is None or not owns(sess, user):
        await websocket.close(code=4404)
        return

    await websocket.accept()
    channel = session_channel(session_id)
    q = subscribe(channel)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_text('{"type":"ping"}')
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        unsubscribe(channel, q)


_health_cache: dict = {}


@app.get("/health")
async def health():
    """Liveness + an honest database check: runs SELECT 1 so a bad DATABASE_URL shows here
    (`database_ok: false` + the driver's message) instead of as 500s on every request."""
    from app.core.auth import auth_enabled, project_url
    from app.core.database import _sqlite, AsyncSessionLocal
    from sqlalchemy import text
    import time
    # Cache the probe for 30 s: with a wrong password every health call is a failed login, and the
    # Supabase pooler trips a circuit breaker after too many of those.
    now = time.time()
    cached = _health_cache.get("at", 0)
    if now - cached < 30:
        db_ok, db_error = _health_cache["ok"], _health_cache["err"]
    else:
        db_ok, db_error = True, None
        try:
            async with AsyncSessionLocal() as db:
                await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=8)
        except Exception as e:  # noqa: BLE001
            db_ok, db_error = False, f"{type(e).__name__}: {str(e)[:200]}"
        _health_cache.update({"at": now, "ok": db_ok, "err": db_error})
    return {
        "status": "ok" if (db_ok and not SCHEMA_ERROR) else "degraded",
        "auth": "supabase" if auth_enabled() else "off (dev)",
        "auth_issuer": (project_url() + "/auth/v1") if auth_enabled() else None,
        "database": "sqlite" if _sqlite else "postgres",
        "database_ok": db_ok,
        "database_error": db_error,
        "schema_ok": SCHEMA_ERROR is None,
        "schema_error": SCHEMA_ERROR,
    }
