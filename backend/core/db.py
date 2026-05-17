from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
import psycopg2
from core.config import settings

engine = create_async_engine(
    settings.POSTGRES_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def get_questdb_conn():
    """Synchronous psycopg2 connection to QuestDB PG wire.

    Sync-only: callers from async paths must use asyncio.to_thread to avoid
    blocking the event loop.
    """
    return psycopg2.connect(settings.QUESTDB_URL)
