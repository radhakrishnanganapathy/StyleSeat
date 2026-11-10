import uuid
from datetime import datetime, date, time
from pydantic import BaseModel, EmailStr, Field
from models.client import (
    TargetGender, StaffRole, AttendanceStatus,
    BookingType, BookingStatus, PaymentMethod, PaymentStatus,
    MessageSenderType, DeliveryStatus
)


# ==========================================
# 1. CATALOG & SERVICES SCHEMAS
# ==========================================

class ServiceCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    category: str = Field(default="General", max_length=50)
    duration_minutes: int = Field(default=30, ge=5, le=300)
    price: float = Field(default=0.0, ge=0.0)
    target_gender: TargetGender = TargetGender.UNISEX


class ServiceUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=300)
    price: float | None = Field(default=None, ge=0.0)
    target_gender: TargetGender | None = None
    is_active: bool | None = None


class ServiceResponse(BaseModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    name: str
    category: str
    duration_minutes: int
    price: float
    target_gender: TargetGender
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class BusinessHoursUpdate(BaseModel):
    opening_time: time
    closing_time: time
    slot_interval_minutes: int = Field(default=30, ge=10, le=120)
    weekly_off_day: int | None = Field(default=None, ge=0, le=6)


class BusinessHoursResponse(BaseModel):
    branch_id: uuid.UUID
    opening_time: time
    closing_time: time
    slot_interval_minutes: int
    weekly_off_day: int | None

    class Config:
        from_attributes = True


# ==========================================
# 2. STAFF & ATTENDANCE SCHEMAS
# ==========================================

class StaffCreate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    phone: str = Field(..., min_length=8, max_length=20)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=6)
    role: StaffRole = StaffRole.STYLIST
    default_lunch_start: time | None = time(13, 0)
    default_lunch_end: time | None = time(14, 0)
    commission_rate: float = Field(default=0.0, ge=0.0, le=100.0)


class StaffUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    role: StaffRole | None = None
    is_active: bool | None = None
    default_lunch_start: time | None = None
    default_lunch_end: time | None = None
    commission_rate: float | None = None


class AttendanceResponse(BaseModel):
    id: uuid.UUID
    work_date: date
    clock_in_at: datetime | None
    clock_out_at: datetime | None
    current_status: AttendanceStatus
    break_start_at: datetime | None

    class Config:
        from_attributes = True


class StaffResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    branch_id: uuid.UUID
    full_name: str
    phone: str
    role: StaffRole
    is_active: bool
    default_lunch_start: time | None
    default_lunch_end: time | None
    commission_rate: float
    current_status: AttendanceStatus = AttendanceStatus.AVAILABLE

    class Config:
        from_attributes = True


class CashHandoverCreate(BaseModel):
    staff_id: uuid.UUID
    cash_collected: float = Field(..., ge=0.0)
    cash_handed_over: float = Field(..., ge=0.0)
    notes: str | None = None


class CashHandoverResponse(BaseModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    staff_id: uuid.UUID
    cash_collected: float
    cash_handed_over: float
    notes: str | None
    handover_at: datetime

    class Config:
        from_attributes = True


class StaffSummaryResponse(BaseModel):
    staff_id: uuid.UUID
    staff_name: str
    today_waiting_tasks: int
    today_completed_tasks: int
    today_total_tasks: int
    today_cash_collected: float
    today_digital_collected: float
    today_total_revenue: float


# ==========================================
# 3. TASK BOARD SCHEMAS
# ==========================================

class TaskItemResponse(BaseModel):
    booking_item_id: uuid.UUID
    booking_id: uuid.UUID
    booking_number: str
    token_number: int
    customer_name: str
    customer_phone: str
    service_id: uuid.UUID
    service_name: str
    duration_minutes: int
    item_price: float
    assigned_staff_id: uuid.UUID | None
    assigned_staff_name: str | None
    booking_status: BookingStatus
    service_started_at: datetime | None
    service_completed_at: datetime | None
    actual_duration_minutes: int | None
    payment_status: PaymentStatus
    payment_method: PaymentMethod | None


class TaskCancelRequest(BaseModel):
    cancellation_reason: str = Field(..., min_length=3, max_length=255)


class PaymentCollectRequest(BaseModel):
    payment_method: PaymentMethod = PaymentMethod.CASH
    amount: float = Field(..., ge=0.0)
    is_paid: bool = True


class TaskReassignRequest(BaseModel):
    new_staff_id: uuid.UUID


class TaskRescheduleRequest(BaseModel):
    new_start_time: time
    new_end_time: time | None = None


# ==========================================
# 4. BOOKING & WALK-IN SCHEMAS
# ==========================================

class WalkInItemInput(BaseModel):
    service_id: uuid.UUID
    assigned_staff_id: uuid.UUID | None = None


class WalkInBookingCreate(BaseModel):
    customer_name: str = Field(..., min_length=2, max_length=100)
    customer_phone: str = Field(..., min_length=8, max_length=20)
    items: list[WalkInItemInput] = Field(..., min_items=1)
    slot_start_time: time | None = None


class BookingItemDetail(BaseModel):
    id: uuid.UUID
    service_id: uuid.UUID
    service_name: str
    item_price: float
    assigned_staff_id: uuid.UUID | None
    assigned_staff_name: str | None
    service_started_at: datetime | None
    service_completed_at: datetime | None

    class Config:
        from_attributes = True


class BookingResponse(BaseModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    booking_number: str
    token_number: int
    customer_name: str
    customer_phone: str
    booking_date: date
    slot_start_time: time | None
    slot_end_time: time | None
    booking_type: BookingType
    status: BookingStatus
    total_amount: float
    service_count: int
    services_summary: str
    payment_status: PaymentStatus = PaymentStatus.PENDING
    payment_method: PaymentMethod | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class BookingDetailResponse(BookingResponse):
    items: list[BookingItemDetail] = []


# ==========================================
# 5. DASHBOARD & ANALYTICS SCHEMAS
# ==========================================

class TodayStatsResponse(BaseModel):
    today_queue: int
    total_bookings_today: int
    total_revenue_today: float
    total_completed_today: int
    staff_available_count: int
    staff_total_count: int
    is_shop_open: bool
    is_on_break: bool
    is_holiday: bool


class UpcomingQueueItem(BaseModel):
    booking_id: uuid.UUID
    booking_number: str
    token_number: int
    customer_name: str
    customer_phone: str
    services_summary: str
    slot_time: time | None
    assigned_staff_name: str | None
    status: BookingStatus


class RevenueChartDataPoint(BaseModel):
    date_label: str
    revenue: float
    booking_count: int
    is_forecast: bool = False


class RevenueChartResponse(BaseModel):
    timeframe: str
    data_points: list[RevenueChartDataPoint]
    total_period_revenue: float
    total_period_bookings: int
    previous_period_revenue: float
    previous_period_bookings: int
    growth_rate_percentage: float


class OperationBreakRequest(BaseModel):
    is_on_break: bool
    break_reason: str | None = "Short staff break"
    break_duration_minutes: int | None = 30


class OperationHolidayRequest(BaseModel):
    target_date: date
    is_holiday: bool
    holiday_description: str | None = "Public Holiday / Closed"


# ==========================================
# 6. DIRECT WHATSAPP MESSAGING SCHEMAS
# ==========================================

class SendMessageRequest(BaseModel):
    customer_phone: str = Field(..., min_length=8, max_length=20)
    customer_name: str | None = None
    message_text: str = Field(..., min_length=1)
    media_url: str | None = None


class MessageResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_type: MessageSenderType
    sender_staff_name: str | None = None
    message_text: str
    media_url: str | None
    delivery_status: DeliveryStatus
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    customer_phone: str
    customer_name: str | None
    last_message_at: datetime
    last_message_preview: str | None
    unread_count_admin: int
    is_ai_bot_active: bool
    ai_bot_paused_until: datetime | None

    class Config:
        from_attributes = True


class CannedResponseCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=100)
    message_text: str = Field(..., min_length=2)


class CannedResponseItem(BaseModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    title: str
    message_text: str

    class Config:
        from_attributes = True
