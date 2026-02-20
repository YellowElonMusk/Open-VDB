"""Database connection and session management"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

# Create async engine
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.debug,
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db():
    """Dependency for getting database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Initialize database tables"""
    from app.models.database import Base as ModelBase
    async with engine.begin() as conn:
        await conn.run_sync(ModelBase.metadata.create_all)
    logger.info("Database initialized")


async def close_db():
    """Close database connections"""
    await engine.dispose()
    logger.info("Database connections closed")
