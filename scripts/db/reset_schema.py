# scripts/db/reset_schema.py
"""
Drop and recreate all tables from the SQLAlchemy models (MySQL local dev).

Run with:
    python -m scripts.db.reset_schema
"""

import asyncio

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.db.base import Base
from app.db.session import engine


async def reset_schema() -> None:
    """Drop all tables then recreate them, disposing the engine afterwards."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Schema reset complete.")


if __name__ == "__main__":
    asyncio.run(reset_schema())