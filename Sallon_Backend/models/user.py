import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Enum, Boolean, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    SHOP_ADMIN = "shop_admin"
    USER = "user"
    STAFF = "staff"

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, default=UserRole.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Salon and Branch association
    salon_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("salons.id"), nullable=True)
    shop_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Invitation fields
    invite_token: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    invite_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
