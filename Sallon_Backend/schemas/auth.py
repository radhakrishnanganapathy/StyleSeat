import uuid
from pydantic import BaseModel, EmailStr, Field
from models.user import UserRole

class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=50, description="Email or Username")
    password: str = Field(..., min_length=6)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    user_type: str  # "INTERNAL" or "CLIENT"

class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: EmailStr
    role: UserRole
    is_active: bool
    salon_id: uuid.UUID | None = None
    shop_id: uuid.UUID | None = None

    class Config:
        from_attributes = True
