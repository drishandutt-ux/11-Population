import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import create_tables
from app.core.redis_client import subscribe, unsubscribe, session_channel
from app.api.v1 import sessions, ingestion, simulation, agents, reports, presets


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await create_tables()
        print("[startup] Database tables ready.")
    except Exception as e:
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

app.include_router(sessions.router, prefix="/api/v1")
app.include_router(ingestion.router, prefix="/api/v1")
app.include_router(simulation.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(presets.router, prefix="/api/v1")


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


@app.get("/health")
async def health():
    from app.core.auth import auth_enabled, project_url
    from app.core.database import _sqlite
    return {
        "status": "ok",
        "auth": "supabase" if auth_enabled() else "off (dev)",
        "auth_issuer": (project_url() + "/auth/v1") if auth_enabled() else None,
        "database": "sqlite" if _sqlite else "postgres",
    }
