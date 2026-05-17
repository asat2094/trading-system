from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
import psycopg2
from core.config import settings

engine = create_async_engine(settings.POSTGRES_URL, pool_size=10, max_overflow=20)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


def get_questdb_conn():
    """Synchronous psycopg2 connection to QuestDB PG wire."""
    return psycopg2.connect(settings.QUESTDB_URL)
