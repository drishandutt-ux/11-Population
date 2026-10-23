from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
import os
import uuid


class Base(DeclarativeBase):
    pass


def _build_url() -> str:
    """
    Railway injects DATABASE_URL as  postgresql://...
    SQLAlchemy async needs   postgresql+asyncpg://...
    Fall back to local SQLite when DATABASE_URL is not set.
    """
    raw = os.environ.get("DATABASE_URL", "").strip()
    if raw:
        if raw.startswith("postgres://"):
            raw = raw.replace("postgres://", "postgresql+asyncpg://", 1)
        elif raw.startswith("postgresql://") and "+asyncpg" not in raw:
            raw = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
        print(f"[database] Using PostgreSQL: {raw[:40]}...")
        return raw
    # Local dev / fallback: SQLite
    db_path = os.path.join(os.path.dirname(__file__), "..", "..", "eleven_minds.db")
    url = f"sqlite+aiosqlite:///{os.path.abspath(db_path)}"
    print(f"[database] No DATABASE_URL — using SQLite: {url}")
    return url


DATABASE_URL = _build_url()
_sqlite = DATABASE_URL.startswith("sqlite")


def _app_url(url: str) -> str:
    """The app's own connections go through Supabase's TRANSACTION pooler (port 6543).

    The session pooler (5432, what DATABASE_URL names) gives each client connection a database
    connection of its own and refuses the 16th outright (EMAXCONNSESSION, pool_size 15) — four
    analysts running Lab tools at once, or the old and new containers overlapping during a
    deploy, crossed it and failed whole runs. The transaction pooler shares the 15 between
    hundreds of client connections and makes a burst wait instead of failing. Migrations keep
    the session URL (alembic/env.py calls _build_url). DB_POOL_MODE=session switches back."""
    if os.environ.get("DB_POOL_MODE", "transaction").strip().lower() == "session":
        return url
    if "pooler.supabase.com:5432/" in url:
        return url.replace("pooler.supabase.com:5432/", "pooler.supabase.com:6543/", 1)
    return url


APP_DATABASE_URL = _app_url(DATABASE_URL)


def _engine_kwargs(url: str = None) -> dict:
    url = url or APP_DATABASE_URL
    if _sqlite:
        return {"connect_args": {"check_same_thread": False}}
    if ":6543/" in url:
        # Transaction mode: a client connection costs no database connection while idle, so the
        # app may keep plenty. Prepared statements cannot be cached across transactions there,
        # and each one gets a unique name so two clients sharing a backend never collide.
        size = int(os.environ.get("DB_POOL_SIZE", "10"))
        overflow = int(os.environ.get("DB_MAX_OVERFLOW", "30"))
        return {"pool_pre_ping": True, "pool_size": size, "max_overflow": overflow, "pool_timeout": 60, "pool_recycle": 1800,
                "connect_args": {"statement_cache_size": 0, "prepared_statement_cache_size": 0,
                                 "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4().hex}__"}}
    # Session mode (5432): the pooler refuses a client's 16th connection, so the ceiling stays under it.
    size = int(os.environ.get("DB_POOL_SIZE", "6"))
    overflow = int(os.environ.get("DB_MAX_OVERFLOW", "8"))
    return {"pool_pre_ping": True, "pool_size": size, "max_overflow": overflow, "pool_timeout": 30, "pool_recycle": 1800}


if not _sqlite:
    print(f"[database] App pool: {'transaction pooler :6543' if ':6543/' in APP_DATABASE_URL else 'session / direct'}")

engine = create_async_engine(APP_DATABASE_URL, echo=False, **_engine_kwargs())
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


POOL_MODE = "sqlite" if _sqlite else ("transaction" if ":6543/" in APP_DATABASE_URL else "session")


async def verify_pool() -> str:
    """Startup check of the transaction pooler with real queries — repeated parameterised
    statements and a few sessions side by side, the things prepared statements trip on. If any
    of it fails the app falls back to the session URL by itself, so a pooler problem costs
    capacity, never the site. Returns the mode in use (shown on /health)."""
    import asyncio
    global engine, POOL_MODE
    if POOL_MODE != "transaction":
        return POOL_MODE

    async def one(k: int):
        async with AsyncSessionLocal() as db:
            for _ in range(3):
                got = (await asyncio.wait_for(db.execute(text("SELECT CAST(:x AS text)"), {"x": f"ok{k}"}), timeout=10)).scalar()
                assert got == f"ok{k}", got
            await asyncio.wait_for(db.execute(text("SELECT count(*) FROM analysis_sessions")), timeout=10)
            await db.commit()

    try:
        await one(0)
        await asyncio.gather(*(one(k) for k in range(1, 6)))
        print("[database] Transaction pooler verified.")
    except Exception as e:  # noqa: BLE001
        print(f"[database] WARNING: transaction pooler failed its check ({type(e).__name__}: {str(e)[:200]}) — falling back to the session pooler")
        old = engine
        engine = create_async_engine(DATABASE_URL, echo=False, **_engine_kwargs(DATABASE_URL))
        AsyncSessionLocal.configure(bind=engine)
        POOL_MODE = f"session (fallback: {type(e).__name__})"
        try:
            await old.dispose()
        except Exception:  # noqa: BLE001
            pass
    return POOL_MODE


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def create_tables():
    """Bring the schema up to date.

    Postgres (production): run Alembic migrations (`backend/alembic/`) — the schema is
    versioned and the Supabase project is stamped at the current head.
    SQLite (local dev / tests): create_all + the idempotent column adds below."""
    import app.models.kg, app.models.profile, app.models.evidence, app.models.measurement, app.models.population, app.models.scoping, app.models.archetype, app.models.share, app.models.usage  # noqa: F401 — make sure every model is registered on Base
    if _sqlite:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns()
        return
    await _run_alembic_upgrade()


async def _run_alembic_upgrade():
    import asyncio
    from alembic import command
    from alembic.config import Config

    ini = os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
    cfg = Config(os.path.abspath(ini))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    # Alembic's async env.py opens its own engine/loop; run it off the server loop.
    await asyncio.to_thread(command.upgrade, cfg, "head")
    print("[database] Alembic migrations up to date.")


async def _ensure_columns():
    """Non-destructive, idempotent migrations: add columns that may be missing on
    tables that pre-date a model change. Each runs in its own transaction so a
    'duplicate column' failure on one doesn't abort the others."""
    migrations = [
        "ALTER TABLE spawned_agents ADD COLUMN humanity INTEGER DEFAULT 0",
        "ALTER TABLE spawned_agents ADD COLUMN verdict TEXT",
        "ALTER TABLE analysis_sessions ADD COLUMN user_id CHAR(32)",
        "ALTER TABLE agent_presets ADD COLUMN user_id CHAR(32)",
        "ALTER TABLE spawned_agents ADD COLUMN segment VARCHAR(120)",
        "ALTER TABLE spawned_agents ADD COLUMN demographics JSON",
        "ALTER TABLE kg_graphs ADD COLUMN ontology JSON",
        "ALTER TABLE spawned_agents ADD COLUMN exposure JSON",
        "ALTER TABLE spawned_agents ADD COLUMN weight FLOAT",
        "ALTER TABLE population_builds ADD COLUMN frame JSON",
        "ALTER TABLE spawned_agents ADD COLUMN character JSON",
        "ALTER TABLE analysis_sessions ADD COLUMN dynamic_dials JSON",
        "ALTER TABLE spawned_agents ADD COLUMN validation JSON",
        "ALTER TABLE report_queries ADD COLUMN structure JSON",
        "ALTER TABLE spawned_agents ADD COLUMN knowledge JSON",
        "ALTER TABLE spawned_agents ADD COLUMN standing JSON",
        "ALTER TABLE simulation_posts ADD COLUMN footprint JSON",
        "ALTER TABLE analysis_sessions ADD COLUMN deleted_at DATETIME",
        "ALTER TABLE analysis_sessions ADD COLUMN model_tier VARCHAR(8) DEFAULT 'fast'",
    ]
    for ddl in migrations:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(ddl))
        except Exception:
            pass  # column already exists (fresh DB just created it)
