import asyncio
from core.database import engine, async_session_maker
from core.security import get_password_hash
from models.user import Base, User, UserRole
import models.internal_salon  # Load all models into Base.metadata

async def seed_user():
    # 1. Create all tables if they don't exist yet
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database tables checked/created.")

    # 2. Insert or update the initial internal admin user
    async with async_session_maker() as session:
        from sqlalchemy import select
        existing = await session.execute(select(User).where(User.email == "admin@salon.ai"))
        user = existing.scalar_one_or_none()
        if not user:
            user = User(
                username="admin",
                email="admin@salon.ai",
                hashed_password=get_password_hash("Admin@123"),
                role=UserRole.SUPER_ADMIN,
                is_active=True
            )
            session.add(user)
            await session.commit()
            print("✅ Internal Admin created (email: admin@salon.ai, password: Admin@123)")
        else:
            print("ℹ️ Internal Admin already exists.")

if __name__ == "__main__":
    asyncio.run(seed_user())
