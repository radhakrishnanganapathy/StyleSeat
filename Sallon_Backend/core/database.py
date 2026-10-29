from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from core.config import settings

engine = create_async_engine(settings.Database_URL, echo=True)
async_session_maker = async_sessionmaker(engine, class_ =AsyncSession, expire_on_commit=False)

async def get_db():
    async with async_session_maker() as session:
        yield session