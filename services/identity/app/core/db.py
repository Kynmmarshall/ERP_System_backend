from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings

# NullPool: a connection is opened, used, and closed entirely within one
# request/session's own event loop, never pooled/reused across loops. This
# avoids a real asyncpg-on-Windows crash where a pooled connection created in
# one asyncio loop gets touched by a later, different loop (observed in the
# test suite). Slightly higher per-request connection overhead in exchange
# for correctness; acceptable at this project's scale.
engine: AsyncEngine = create_async_engine(settings.database_url, poolclass=NullPool)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


async def database_is_ready() -> bool:
    """Used by /readyz; a failed SELECT means the service cannot serve real traffic."""
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False
