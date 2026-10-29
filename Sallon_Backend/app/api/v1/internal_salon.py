import secrets
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from core.database import get_db
from core.dependencies import get_current_internal_admin
from core.security import get_password_hash
from models.user import User, UserRole
from models.internal_salon import Salon, Branch, SalonStatus, SubscriptionStatus
from schemas.internal_salon import (
    SalonCreate, SalonUpdate, SalonResponse,
    BranchCreate, BranchResponse,
    InviteUserRequest, InviteUserResponse,
    SubscriptionUpdateRequest
)

router = APIRouter(
    prefix="/internal/salons",
    tags=["Internal Salon Management"],
    dependencies=[Depends(get_current_internal_admin)]
)


# ==========================================
# 1. SALON CRUD
# ==========================================

@router.post("", response_model=SalonResponse, status_code=status.HTTP_201_CREATED)
async def create_salon(payload: SalonCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Salon).where(Salon.slug == payload.slug.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Salon slug already exists")

    salon = Salon(
        name=payload.name,
        slug=payload.slug.lower(),
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone,
        subscription_plan=payload.subscription_plan,
        max_branches=payload.max_branches,
        status=SalonStatus.ACTIVE,
        subscription_status=SubscriptionStatus.TRIAL
    )
    db.add(salon)
    await db.commit()
    await db.refresh(salon)
    return salon


@router.get("", response_model=list[SalonResponse])
async def list_salons(skip: int = 0, limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Salon).where(Salon.status != SalonStatus.DELETED).offset(skip).limit(limit)
    )
    return result.scalars().all()


@router.get("/{salon_id}", response_model=SalonResponse)
async def get_salon(salon_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Salon).where(Salon.id == salon_id))
    salon = result.scalar_one_or_none()
    if not salon or salon.status == SalonStatus.DELETED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Salon not found")
    return salon


@router.put("/{salon_id}", response_model=SalonResponse)
async def update_salon(salon_id: uuid.UUID, payload: SalonUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Salon).where(Salon.id == salon_id))
    salon = result.scalar_one_or_none()
    if not salon or salon.status == SalonStatus.DELETED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Salon not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(salon, field, value)

    await db.commit()
    await db.refresh(salon)
    return salon


@router.delete("/{salon_id}")
async def soft_delete_salon(salon_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Salon).where(Salon.id == salon_id))
    salon = result.scalar_one_or_none()
    if not salon or salon.status == SalonStatus.DELETED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Salon not found")

    salon.status = SalonStatus.DELETED
    await db.commit()
    return {"message": f"Salon '{salon.name}' has been soft deleted successfully"}


# ==========================================
# 2. INVITE USER WITH SALON ID BY EMAIL
# ==========================================

@router.post("/{salon_id}/invite", response_model=InviteUserResponse)
async def invite_user_to_salon(salon_id: uuid.UUID, payload: InviteUserRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Salon).where(Salon.id == salon_id))
    salon = result.scalar_one_or_none()
    if not salon or salon.status != SalonStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Salon not found or inactive")

    invite_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=48)

    user_check = await db.execute(select(User).where(User.email == payload.email))
    existing_user = user_check.scalar_one_or_none()

    if existing_user:
        existing_user.invite_token = invite_token
        existing_user.invite_expires_at = expires_at
        existing_user.salon_id = salon.id
        existing_user.role = payload.role
    else:
        new_user = User(
            username=payload.username,
            email=payload.email,
            hashed_password=get_password_hash(secrets.token_hex(16)),
            role=payload.role,
            is_active=False,
            salon_id=salon.id,
            invite_token=invite_token,
            invite_expires_at=expires_at
        )
        db.add(new_user)

    await db.commit()

    invite_link = f"https://yourdomain.com/accept-invite?token={invite_token}"

    return InviteUserResponse(
        message=f"Invite created for {payload.email}",
        email=payload.email,
        invite_token=invite_token,
        invite_link=invite_link,
        expires_at=expires_at
    )


# ==========================================
# 3. CREATE & LIST BRANCHES WITH SALON ID
# ==========================================

@router.post("/{salon_id}/branches", response_model=BranchResponse, status_code=status.HTTP_201_CREATED)
async def create_branch(salon_id: uuid.UUID, payload: BranchCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Salon).where(Salon.id == salon_id))
    salon = result.scalar_one_or_none()
    if not salon or salon.status == SalonStatus.DELETED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Salon not found")

    branch_count = await db.scalar(
        select(func.count(Branch.id)).where(Branch.salon_id == salon_id)
    )
    if branch_count >= salon.max_branches:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Branch limit reached ({salon.max_branches}). Please upgrade salon subscription."
        )

    branch = Branch(
        salon_id=salon_id,
        name=payload.name,
        address=payload.address,
        phone=payload.phone,
        is_active=True
    )
    db.add(branch)
    await db.commit()
    await db.refresh(branch)
    return branch


@router.get("/{salon_id}/branches", response_model=list[BranchResponse])
async def list_salon_branches(salon_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Branch).where(Branch.salon_id == salon_id))
    return result.scalars().all()


# ==========================================
# 4. SALON STATUS ACTIONS
# ==========================================

@router.post("/{salon_id}/activate", response_model=SalonResponse)
async def activate_salon(salon_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Salon).where(Salon.id == salon_id))
    salon = result.scalar_one_or_none()
    if not salon or salon.status == SalonStatus.DELETED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Salon not found")
    salon.status = SalonStatus.ACTIVE
    await db.commit()
    await db.refresh(salon)
    return salon


@router.post("/{salon_id}/deactivate", response_model=SalonResponse)
async def deactivate_salon(salon_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Salon).where(Salon.id == salon_id))
    salon = result.scalar_one_or_none()
    if not salon or salon.status == SalonStatus.DELETED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Salon not found")
    salon.status = SalonStatus.INACTIVE
    await db.commit()
    await db.refresh(salon)
    return salon


@router.post("/{salon_id}/suspend", response_model=SalonResponse)
async def suspend_salon(salon_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Salon).where(Salon.id == salon_id))
    salon = result.scalar_one_or_none()
    if not salon or salon.status == SalonStatus.DELETED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Salon not found")
    salon.status = SalonStatus.SUSPENDED
    await db.commit()
    await db.refresh(salon)
    return salon


@router.post("/{salon_id}/reactivate", response_model=SalonResponse)
async def reactivate_salon(salon_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Salon).where(Salon.id == salon_id))
    salon = result.scalar_one_or_none()
    if not salon or salon.status == SalonStatus.DELETED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Salon not found")
    salon.status = SalonStatus.ACTIVE
    await db.commit()
    await db.refresh(salon)
    return salon


# ==========================================
# 5. SUBSCRIPTION ACTIONS
# ==========================================

@router.post("/{salon_id}/subscribe", response_model=SalonResponse)
async def subscribe_salon(salon_id: uuid.UUID, payload: SubscriptionUpdateRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Salon).where(Salon.id == salon_id))
    salon = result.scalar_one_or_none()
    if not salon or salon.status == SalonStatus.DELETED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Salon not found")

    salon.subscription_plan = payload.subscription_plan
    salon.subscription_status = SubscriptionStatus.ACTIVE
    salon.max_branches = payload.max_branches
    salon.status = SalonStatus.ACTIVE
    await db.commit()
    await db.refresh(salon)
    return salon


@router.post("/{salon_id}/unsubscribe", response_model=SalonResponse)
async def unsubscribe_salon(salon_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Salon).where(Salon.id == salon_id))
    salon = result.scalar_one_or_none()
    if not salon or salon.status == SalonStatus.DELETED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Salon not found")

    salon.subscription_status = SubscriptionStatus.CANCELLED
    salon.status = SalonStatus.SUSPENDED
    await db.commit()
    await db.refresh(salon)
    return salon

