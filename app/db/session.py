# app/db/session.py
"""
Database session management.
Handles engine creation and session dependency for FastAPI.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

# Create async engine with connection pooling
if settings.is_development or settings.is_staging:
    # Use connection pooling for non-test environments
    engine = create_async_engine(
        settings.async_database_url,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
    )
else:
    # Use NullPool for tests to avoid connection issues
    engine = create_async_engine(
        settings.async_database_url,
        echo=settings.DB_ECHO,
        poolclass=NullPool,
    )

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncSession:
    """
    Dependency that provides a database session.
    Yields a session and ensures it's closed after use.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database connection (can be used for startup events)."""
    pass


async def close_db() -> None:
    """Close database engine (for shutdown events)."""
    await engine.dispose()