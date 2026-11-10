from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.database import engine
from models.user import Base
import models.internal_salon  # Ensures salons and branches tables are registered
import models.client          # Ensures all client, booking, and messaging tables are registered

# Auth & Internal Routers
from app.api.v1.auth import internal_auth_router, client_auth_router
from app.api.v1.internal_salon import router as internal_salon_router

# Client-Side Routers
from app.api.v1.client.catalog import router as client_catalog_router
from app.api.v1.client.staff import router as client_staff_router
from app.api.v1.client.bookings import router as client_bookings_router
from app.api.v1.client.tasks import router as client_tasks_router
from app.api.v1.client.dashboard import router as client_dashboard_router
from app.api.v1.client.messages import router as client_messages_router


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

# Enable CORS for Mobile Apps and Web Dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Internal Platform Admin Auth & Management
app.include_router(internal_auth_router, prefix="/api/v1")
app.include_router(internal_salon_router, prefix="/api/v1")

# 2. Client Salon Auth
app.include_router(client_auth_router, prefix="/api/v1")

# 3. Client Operations & Modules
app.include_router(client_dashboard_router, prefix="/api/v1")
app.include_router(client_tasks_router, prefix="/api/v1")
app.include_router(client_bookings_router, prefix="/api/v1")
app.include_router(client_messages_router, prefix="/api/v1")
app.include_router(client_staff_router, prefix="/api/v1")
app.include_router(client_catalog_router, prefix="/api/v1")


@app.get("/")
async def read_root():
    return {"message": "SaloonAI Backend is running", "status": "ONLINE"}
