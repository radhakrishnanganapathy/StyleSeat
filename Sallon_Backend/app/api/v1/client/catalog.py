import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from core.dependencies import get_current_client_user, get_active_branch_id
from models.user import User, UserRole
from models.client import Service, BranchSchedule
from schemas.client import (
    ServiceCreate, ServiceUpdate, ServiceResponse,
    BusinessHoursUpdate, BusinessHoursResponse
)

router = APIRouter(prefix="/client/catalog", tags=["Client - Catalog & Hours"])


# ==========================================
# 1. SERVICES CRUD
# ==========================================

@router.get("/services", response_model=list[ServiceResponse])
async def list_services(
    active_only: bool = True,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(Service).where(Service.branch_id == branch_id)
    if active_only:
        query = query.where(Service.is_active == True)
    result = await db.execute(query.order_by(Service.category, Service.name))
    return result.scalars().all()


@router.post("/services", response_model=ServiceResponse, status_code=status.HTTP_201_CREATED)
async def create_service(
    payload: ServiceCreate,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in [UserRole.SHOP_ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only salon managers can create services")

    service = Service(
        branch_id=branch_id,
        name=payload.name,
        category=payload.category,
        duration_minutes=payload.duration_minutes,
        price=payload.price,
        target_gender=payload.target_gender,
        is_active=True
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return service


@router.put("/services/{service_id}", response_model=ServiceResponse)
async def update_service(
    service_id: uuid.UUID,
    payload: ServiceUpdate,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in [UserRole.SHOP_ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only salon managers can edit services")

    result = await db.execute(select(Service).where(Service.id == service_id, Service.branch_id == branch_id))
    service = result.scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(service, field, value)

    await db.commit()
    await db.refresh(service)
    return service


@router.delete("/services/{service_id}")
async def delete_service(
    service_id: uuid.UUID,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in [UserRole.SHOP_ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only salon managers can delete services")

    result = await db.execute(select(Service).where(Service.id == service_id, Service.branch_id == branch_id))
    service = result.scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")

    service.is_active = False  # Soft delete
    await db.commit()
    return {"message": f"Service '{service.name}' deactivated successfully"}


# ==========================================
# 2. BUSINESS HOURS & SCHEDULE
# ==========================================

@router.get("/business-hours", response_model=BusinessHoursResponse)
async def get_business_hours(
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(BranchSchedule).where(BranchSchedule.branch_id == branch_id))
    schedule = result.scalar_one_or_none()
    if not schedule:
        # Default schedule if not configured
        schedule = BranchSchedule(branch_id=branch_id)
        db.add(schedule)
        await db.commit()
        await db.refresh(schedule)
    return schedule


@router.put("/business-hours", response_model=BusinessHoursResponse)
async def update_business_hours(
    payload: BusinessHoursUpdate,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in [UserRole.SHOP_ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only salon managers can update business hours")

    result = await db.execute(select(BranchSchedule).where(BranchSchedule.branch_id == branch_id))
    schedule = result.scalar_one_or_none()
    if not schedule:
        schedule = BranchSchedule(branch_id=branch_id)
        db.add(schedule)

    schedule.opening_time = payload.opening_time
    schedule.closing_time = payload.closing_time
    schedule.slot_interval_minutes = payload.slot_interval_minutes
    schedule.weekly_off_day = payload.weekly_off_day

    await db.commit()
    await db.refresh(schedule)
    return schedule
