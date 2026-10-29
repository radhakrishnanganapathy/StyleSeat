from contextlib import asynccontextmanager
from fastapi import FastAPI

from core.database import engine
from models.user import Base
import models.internal_salon  # Ensures salons and branches tables are registered

from app.api.v1.auth import internal_auth_router, client_auth_router
from app.api.v1.internal_salon import router as internal_salon_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create all tables on startup if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(
    title="SaloonAI Backend",
    version="1.0.0",
    description="Backend API for SaloonAI Multi-Tenant Platform",
    lifespan=lifespan
)

# 1. Internal Platform Admin Auth
app.include_router(internal_auth_router, prefix="/api/v1")

# 2. Client Salon Auth
app.include_router(client_auth_router, prefix="/api/v1")

# 3. Internal Salon & Branch Management
app.include_router(internal_salon_router, prefix="/api/v1")

@app.get("/")
async def read_root():
    return {"message": "SaloonAI Backend is running"}
