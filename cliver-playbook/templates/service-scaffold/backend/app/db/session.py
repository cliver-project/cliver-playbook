"""Async engine and session factory.

The engine binds to `settings.db_url` (asyncpg). Sessions are created with
`expire_on_commit=False` so detached reads after commit keep their attributes —
the standard choice for request-scoped sessions returned by FastAPI dependencies.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.db_url, future=True, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped session (rolled back on error)."""
    async with SessionLocal() as session:
        yield session
