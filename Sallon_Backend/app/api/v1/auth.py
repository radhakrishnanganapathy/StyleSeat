from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from core.database import get_db
from core.security import verify_password, create_access_token
from core.dependencies import get_current_internal_admin, get_current_client_user
from models.user import User, UserRole
from schemas.auth import LoginRequest, TokenResponse, UserResponse

# ==========================================
# 1. INTERNAL ADMIN AUTHENTICATION ROUTER
# ==========================================
internal_auth_router = APIRouter(prefix="/internal/auth", tags=["Internal Authentication"])


@internal_auth_router.post("/login", response_model=TokenResponse)
async def internal_admin_login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(or_(User.email == request.email, User.username == request.email))
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Reject non-internal users
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: This portal is for internal platform admins only"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin account is deactivated"
        )

    # Issue INTERNAL JWT
    token_data = {
        "sub": str(user.id),
        "user_type": "INTERNAL",
        "role": user.role.value
    }
    access_token = create_access_token(data=token_data)

    return TokenResponse(
        access_token=access_token,
        role=user.role,
        user_type="INTERNAL"
    )


@internal_auth_router.get("/me", response_model=UserResponse)
async def get_internal_admin_profile(current_admin: User = Depends(get_current_internal_admin)):
    return current_admin


# ==========================================
# 2. CLIENT / SALON AUTHENTICATION ROUTER
# ==========================================
client_auth_router = APIRouter(prefix="/client/auth", tags=["Client Authentication"])


@client_auth_router.post("/login", response_model=TokenResponse)
async def client_login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(or_(User.email == request.email, User.username == request.email))
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Reject super admins from logging in via client portal
    if user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal administrators must use the internal portal (/internal/auth/login)"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client account is deactivated"
        )

    # Issue CLIENT JWT
    token_data = {
        "sub": str(user.id),
        "user_type": "CLIENT",
        "role": user.role.value,
        "salon_id": str(user.salon_id) if user.salon_id else None,
        "shop_id": str(user.shop_id) if user.shop_id else None
    }
    access_token = create_access_token(data=token_data)

    return TokenResponse(
        access_token=access_token,
        role=user.role,
        user_type="CLIENT"
    )


@client_auth_router.get("/me", response_model=UserResponse)
async def get_client_profile(current_client: User = Depends(get_current_client_user)):
    return current_client
