from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
import os


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

def _engine_kwargs() -> dict:
    if _sqlite:
        return {"connect_args": {"check_same_thread": False}}
    kw: dict = {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 5, "pool_recycle": 1800}
    # Supabase shared pooler in TRANSACTION mode (port 6543) cannot use prepared statements.
    if ":6543/" in DATABASE_URL:
        from sqlalchemy.pool import NullPool
        kw = {"poolclass": NullPool, "connect_args": {"statement_cache_size": 0, "prepared_statement_cache_size": 0}}
    return kw


engine = create_async_engine(DATABASE_URL, echo=False, **_engine_kwargs())
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def create_tables():
    """Bring the schema up to date.

    Postgres (production): run Alembic migrations (`backend/alembic/`) — the schema is
    versioned and the Supabase project is stamped at the current head.
    SQLite (local dev / tests): create_all + the idempotent column adds below."""
    import app.models.kg, app.models.profile  # noqa: F401 — make sure every model is registered on Base
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
    ]
    for ddl in migrations:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(ddl))
        except Exception:
            pass  # column already exists (fresh DB just created it)
