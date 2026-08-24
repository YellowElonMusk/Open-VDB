"""Idempotent database bootstrap — makes deployment one command.

Creates the pgvector extension, all tables, and applies the small set of
in-place upgrades needed when moving between releases. Safe to run on
every startup: everything here is a no-op if already applied.

Run standalone (the Docker container does this before starting the API):

    python -m src.db.bootstrap
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from src.core.config import settings
from src.models.database import Base

# In-place upgrades for databases created by earlier releases.
# Each statement must be idempotent.
UPGRADE_STATEMENTS = [
    # Embeddings became optional when markdown/sqlite outputs were added
    "ALTER TABLE chunks ALTER COLUMN embedding DROP NOT NULL",
    # Output format choice per document (existing docs were all vector)
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS "
    "output_formats VARCHAR(100) NOT NULL DEFAULT 'vector'",
]


async def ensure_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        for statement in UPGRADE_STATEMENTS:
            await conn.execute(text(statement))


async def main() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    attempts = 30
    for attempt in range(1, attempts + 1):
        try:
            await ensure_schema(engine)
            print("Database schema is ready.")
            break
        except Exception as e:
            if attempt == attempts:
                raise
            print(f"Database not ready yet ({type(e).__name__}), retrying ({attempt}/{attempts})...")
            await asyncio.sleep(2)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
