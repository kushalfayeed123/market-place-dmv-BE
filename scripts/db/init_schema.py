# scripts/db/init_schema.py
"""
Create all tables from the SQLAlchemy models.

Use this on MySQL (local dev) where the checked-in Alembic migrations are
PostgreSQL-specific. The resulting schema is equivalent to what the Alembic
migrations produce on PostgreSQL (an odd-number-steps ago it was generated
via autogenerate against the models, so metadata is the source of truth).

Run with:
    python -m scripts.db.init_schema
"""

import asyncio

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.db.base import Base
from app.db.session import engine


async def create_schema() -> None:
    """Create all tables (idempotent) and dispose the engine."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Schema created successfully.")


if __name__ == "__main__":
    asyncio.run(create_schema())