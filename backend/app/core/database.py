from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
import os


class Base(DeclarativeBase):
    pass


def _build_url() -> str:
    """
    Railway injects DATABASE_URL as  postgresql://...
    SQLAlchemy async needs   postgresql+asyncpg://...
    Fall back to local SQLite when DATABASE_URL is not set.
    """
    raw = os.environ.get("DATABASE_URL", "")
    if raw:
        if raw.startswith("postgres://"):
            raw = raw.replace("postgres://", "postgresql+asyncpg://", 1)
        elif raw.startswith("postgresql://"):
            raw = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
        return raw
    # Local dev: SQLite
    db_path = os.path.join(os.path.dirname(__file__), "..", "..", "eleven_minds.db")
    return f"sqlite+aiosqlite:///{os.path.abspath(db_path)}"


DATABASE_URL = _build_url()
_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    **{"connect_args": {"check_same_thread": False}} if _sqlite else {},
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
