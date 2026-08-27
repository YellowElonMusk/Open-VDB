"""Idempotent database bootstrap — makes deployment one command.

Schema changes live in Alembic migrations; this module just runs them.
Creating tables from model metadata at startup is how the ivfflat index
ended up being built on an empty table, and it silently skips any DDL that
metadata cannot express (generated columns, HNSW, trigram indexes).

Run standalone (the Docker container does this before starting the API):

    python -m src.db.bootstrap
"""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from src.core.config import settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url_sync)
    return config


def run_migrations() -> None:
    """Upgrade the database to the latest revision (idempotent)."""
    command.upgrade(alembic_config(), "head")


async def ensure_schema(engine: AsyncEngine) -> None:
    """Verify connectivity, then apply migrations.

    Migrations run through Alembic's synchronous engine, so this only uses
    the async engine to confirm the database is reachable first.
    """
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await asyncio.to_thread(run_migrations)


async def main() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    attempts = 30
    for attempt in range(1, attempts + 1):
        try:
            await ensure_schema(engine)
            print("Database schema is up to date.")
            break
        except Exception as e:
            if attempt == attempts:
                raise
            print(f"Database not ready yet ({type(e).__name__}), retrying ({attempt}/{attempts})...")
            await asyncio.sleep(2)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
