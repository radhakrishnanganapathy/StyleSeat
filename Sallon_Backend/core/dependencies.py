import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.config import settings
from core.database import get_db
from models.user import User, UserRole

security = HTTPBearer()

async def decode_token_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, settings.Secret_Key, algorithms=[settings.Algorithm])
        if payload.get("sub") is None:
            raise credentials_exception
        return payload
    except jwt.PyJWTError:
        raise credentials_exception


# --- 1. INTERNAL ADMIN GUARD (Requires user_type: INTERNAL and role: SUPER_ADMIN) ---
async def get_current_internal_admin(
    payload: dict = Depends(decode_token_payload),
    db: AsyncSession = Depends(get_db)
) -> User:
    if payload.get("user_type") != "INTERNAL":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Internal admin token required"
        )

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin user not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin account is inactive")
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Internal admin privileges required"
        )
    return user


# --- 2. CLIENT USER GUARD (Requires user_type: CLIENT) ---
async def get_current_client_user(
    payload: dict = Depends(decode_token_payload),
    db: AsyncSession = Depends(get_db)
) -> User:
    if payload.get("user_type") != "CLIENT":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Client token required"
        )

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client user not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client account is inactive")
    if user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Super admins must use the internal portal"
        )
    return user


# --- 3. GENERIC USER RESOLVER (Optional fallback) ---
async def get_current_user(
    payload: dict = Depends(decode_token_payload),
    db: AsyncSession = Depends(get_db)
) -> User:
    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    return user


def role_guard(*allowed_roles: UserRole):
    def role_checker(user: User = Depends(get_current_user)):
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource"
            )
        return user
    return role_checker
