import enum
import uuid
from datetime import datetime, date, time, timezone
from sqlalchemy import String, Boolean, Enum, ForeignKey, Integer, Numeric, DateTime, Date, Time, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.user import Base


# ==========================================
# ENUMS
# ==========================================

class TargetGender(str, enum.Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    UNISEX = "UNISEX"
    KIDS = "KIDS"


class StaffRole(str, enum.Enum):
    SHOP_ADMIN = "SHOP_ADMIN"
    STYLIST = "STYLIST"


class AttendanceStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    ON_BREAK = "ON_BREAK"
    LUNCH = "LUNCH"
    ON_LEAVE = "ON_LEAVE"


class BookingType(str, enum.Enum):
    WHATSAPP = "WHATSAPP"
    WALK_IN = "WALK_IN"
    PHONE = "PHONE"


class BookingStatus(str, enum.Enum):
    WAITING = "WAITING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentMethod(str, enum.Enum):
    CASH = "CASH"
    CARD = "CARD"
    UPI_QR = "UPI_QR"
    LATER_PAY = "LATER_PAY"


class PaymentStatus(str, enum.Enum):
    PAID = "PAID"
    PENDING = "PENDING"


class MessageSenderType(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    BOT = "BOT"
    ADMIN = "ADMIN"


class DeliveryStatus(str, enum.Enum):
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"
    FAILED = "FAILED"


# ==========================================
# 1. CATALOG & SERVICE MODELS
# ==========================================

class Service(Base):
    __tablename__ = "services"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="General", nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    target_gender: Mapped[TargetGender] = mapped_column(Enum(TargetGender), default=TargetGender.UNISEX, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ==========================================
# 2. STAFF & ATTENDANCE MODELS
# ==========================================

class StaffProfile(Base):
    __tablename__ = "staff_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    role: Mapped[StaffRole] = mapped_column(Enum(StaffRole), default=StaffRole.STYLIST, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_lunch_start: Mapped[time | None] = mapped_column(Time, default=time(13, 0), nullable=True)
    default_lunch_end: Mapped[time | None] = mapped_column(Time, default=time(14, 0), nullable=True)
    commission_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    attendances: Mapped[list["StaffAttendance"]] = relationship("StaffAttendance", back_populates="staff", cascade="all, delete-orphan")


class StaffAttendance(Base):
    __tablename__ = "staff_attendances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    staff_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("staff_profiles.id"), nullable=False, index=True)
    work_date: Mapped[date] = mapped_column(Date, default=lambda: datetime.now(timezone.utc).date(), nullable=False, index=True)
    clock_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clock_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_status: Mapped[AttendanceStatus] = mapped_column(Enum(AttendanceStatus), default=AttendanceStatus.AVAILABLE, nullable=False)
    break_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    staff: Mapped["StaffProfile"] = relationship("StaffProfile", back_populates="attendances")


class CashHandover(Base):
    __tablename__ = "cash_handovers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False, index=True)
    staff_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("staff_profiles.id"), nullable=False)
    cash_collected: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    cash_handed_over: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    handover_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ==========================================
# 3. BOOKINGS & PAYMENTS
# ==========================================

class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False, index=True)
    booking_number: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    token_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    booking_date: Mapped[date] = mapped_column(Date, default=lambda: datetime.now(timezone.utc).date(), nullable=False, index=True)
    slot_start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    slot_end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    booking_type: Mapped[BookingType] = mapped_column(Enum(BookingType), default=BookingType.WALK_IN, nullable=False)
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.WAITING, nullable=False, index=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    items: Mapped[list["BookingItem"]] = relationship("BookingItem", back_populates="booking", cascade="all, delete-orphan")
    payment: Mapped["PaymentRecord | None"] = relationship("PaymentRecord", back_populates="booking", uselist=False, cascade="all, delete-orphan")


class BookingItem(Base):
    __tablename__ = "booking_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bookings.id"), nullable=False, index=True)
    service_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("services.id"), nullable=False)
    assigned_staff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("staff_profiles.id"), nullable=True, index=True)
    service_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    service_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_price: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)

    booking: Mapped["Booking"] = relationship("Booking", back_populates="items")
    service: Mapped["Service"] = relationship("Service")
    assigned_staff: Mapped["StaffProfile | None"] = relationship("StaffProfile")


class PaymentRecord(Base):
    __tablename__ = "payment_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bookings.id"), nullable=False, unique=True)
    collected_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("staff_profiles.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(Enum(PaymentMethod), default=PaymentMethod.CASH, nullable=False)
    payment_status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.PAID, nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    booking: Mapped["Booking"] = relationship("Booking", back_populates="payment")


# ==========================================
# 4. BRANCH OPERATIONS (OPEN/CLOSE, BREAKS, HOLIDAYS)
# ==========================================

class BranchOperation(Base):
    __tablename__ = "branch_operations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False, index=True)
    target_date: Mapped[date] = mapped_column(Date, default=lambda: datetime.now(timezone.utc).date(), nullable=False, index=True)
    is_shop_open: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_on_break: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    break_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    break_expected_return: Mapped[time | None] = mapped_column(Time, nullable=True)
    is_holiday: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    holiday_description: Mapped[str | None] = mapped_column(String(255), nullable=True)


class BranchSchedule(Base):
    __tablename__ = "branch_schedules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False, unique=True)
    opening_time: Mapped[time] = mapped_column(Time, default=time(9, 0), nullable=False)
    closing_time: Mapped[time] = mapped_column(Time, default=time(21, 0), nullable=False)
    slot_interval_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    weekly_off_day: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0=Monday, 6=Sunday


# ==========================================
# 5. MESSAGING & DIRECT WHATSAPP LIVE CHAT
# ==========================================

class WhatsAppConversation(Base):
    __tablename__ = "whatsapp_conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False, index=True)
    customer_phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    customer_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_message_preview: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unread_count_admin: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_ai_bot_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ai_bot_paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["WhatsAppMessage"]] = relationship("WhatsAppMessage", back_populates="conversation", cascade="all, delete-orphan")


class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("whatsapp_conversations.id"), nullable=False, index=True)
    sender_type: Mapped[MessageSenderType] = mapped_column(Enum(MessageSenderType), nullable=False)
    sender_staff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("staff_profiles.id"), nullable=True)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    media_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    meta_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delivery_status: Mapped[DeliveryStatus] = mapped_column(Enum(DeliveryStatus), default=DeliveryStatus.SENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    conversation: Mapped["WhatsAppConversation"] = relationship("WhatsAppConversation", back_populates="messages")


class CannedResponse(Base):
    __tablename__ = "canned_responses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
