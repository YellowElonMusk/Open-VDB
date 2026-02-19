from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings

async_engine = create_async_engine(settings.database_url, echo=settings.debug, pool_size=20, max_overflow=10)
async_session = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
