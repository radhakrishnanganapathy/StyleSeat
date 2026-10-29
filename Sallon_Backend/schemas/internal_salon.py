import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field
from models.internal_salon import SalonStatus, SubscriptionPlan, SubscriptionStatus
from models.user import UserRole


# --- Salon Schemas ---
class SalonCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    slug: str = Field(..., min_length=2, max_length=100)
    contact_email: EmailStr
    contact_phone: str = Field(..., min_length=8, max_length=20)
    subscription_plan: SubscriptionPlan = SubscriptionPlan.FREE_TRIAL
    max_branches: int = Field(default=1, ge=1)


class SalonUpdate(BaseModel):
    name: str | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = None
    max_branches: int | None = Field(default=None, ge=1)


class SalonResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    contact_email: EmailStr
    contact_phone: str
    status: SalonStatus
    subscription_plan: SubscriptionPlan
    subscription_status: SubscriptionStatus
    max_branches: int
    created_at: datetime

    class Config:
        from_attributes = True


# --- Branch Schemas ---
class BranchCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    address: str | None = None
    phone: str | None = None


class BranchResponse(BaseModel):
    id: uuid.UUID
    salon_id: uuid.UUID
    name: str
    address: str | None
    phone: str | None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# --- Invite Schemas ---
class InviteUserRequest(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    role: UserRole = UserRole.SHOP_ADMIN


class InviteUserResponse(BaseModel):
    message: str
    email: str
    invite_token: str
    invite_link: str
    expires_at: datetime


# --- Subscription Schemas ---
class SubscriptionUpdateRequest(BaseModel):
    subscription_plan: SubscriptionPlan
    max_branches: int = Field(default=1, ge=1)

