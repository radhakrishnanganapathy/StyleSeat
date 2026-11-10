import uuid
from datetime import datetime, date, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from core.database import get_db
from core.dependencies import get_current_client_user, get_active_branch_id
from models.user import User, UserRole
from models.client import (
    Booking, BookingItem, Service, StaffProfile, StaffAttendance,
    AttendanceStatus, BookingStatus, PaymentRecord, PaymentStatus,
    BranchOperation
)
from schemas.client import (
    TodayStatsResponse, UpcomingQueueItem,
    RevenueChartResponse, RevenueChartDataPoint,
    OperationBreakRequest, OperationHolidayRequest
)

router = APIRouter(prefix="/client/dashboard", tags=["Client - Dashboard & Analytics"])


async def _get_or_create_operation(branch_id: uuid.UUID, target_date: date, db: AsyncSession) -> BranchOperation:
    res = await db.execute(
        select(BranchOperation).where(
            BranchOperation.branch_id == branch_id,
            BranchOperation.target_date == target_date
        )
    )
    op = res.scalar_one_or_none()
    if not op:
        op = BranchOperation(
            branch_id=branch_id,
            target_date=target_date,
            is_shop_open=True,
            is_on_break=False,
            is_holiday=False
        )
        db.add(op)
        await db.flush()
    return op


# ==========================================
# 1. TODAY'S REAL-TIME KPIS
# ==========================================

@router.get("/stats/today", response_model=TodayStatsResponse)
async def get_today_stats(
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    today = datetime.now(timezone.utc).date()

    # 1. Today's Queue (WAITING)
    queue_count = await db.scalar(
        select(func.count(Booking.id)).where(
            Booking.branch_id == branch_id,
            Booking.booking_date == today,
            Booking.status == BookingStatus.WAITING
        )
    ) or 0

    # 2. Total Bookings Today
    total_bookings = await db.scalar(
        select(func.count(Booking.id)).where(
            Booking.branch_id == branch_id,
            Booking.booking_date == today
        )
    ) or 0

    # 3. Total Completed Today
    total_completed = await db.scalar(
        select(func.count(Booking.id)).where(
            Booking.branch_id == branch_id,
            Booking.booking_date == today,
            Booking.status == BookingStatus.COMPLETED
        )
    ) or 0

    # 4. Total Revenue Today (PAID payments)
    revenue_query = (
        select(func.coalesce(func.sum(PaymentRecord.amount), 0.0))
        .join(Booking, PaymentRecord.booking_id == Booking.id)
        .where(
            Booking.branch_id == branch_id,
            Booking.booking_date == today,
            PaymentRecord.payment_status == PaymentStatus.PAID
        )
    )
    total_revenue = await db.scalar(revenue_query) or 0.0

    # 5. Staff Availability (e.g. 2 / 3 available)
    staff_total = await db.scalar(
        select(func.count(StaffProfile.id)).where(
            StaffProfile.branch_id == branch_id,
            StaffProfile.is_active == True
        )
    ) or 0

    available_query = (
        select(func.count(StaffAttendance.id))
        .join(StaffProfile, StaffAttendance.staff_id == StaffProfile.id)
        .where(
            StaffProfile.branch_id == branch_id,
            StaffAttendance.work_date == today,
            StaffAttendance.current_status == AttendanceStatus.AVAILABLE,
            StaffAttendance.clock_out_at.is_(None)
        )
    )
    staff_available = await db.scalar(available_query) or 0

    # 6. Branch Operation States
    op = await _get_or_create_operation(branch_id, today, db)

    return TodayStatsResponse(
        today_queue=queue_count,
        total_bookings_today=total_bookings,
        total_revenue_today=float(total_revenue),
        total_completed_today=total_completed,
        staff_available_count=staff_available,
        staff_total_count=staff_total,
        is_shop_open=op.is_shop_open,
        is_on_break=op.is_on_break,
        is_holiday=op.is_holiday
    )


# ==========================================
# 2. UPCOMING QUEUE LIST (NEXT 5 CUSTOMERS)
# ==========================================

@router.get("/upcoming-queue", response_model=list[UpcomingQueueItem])
async def get_upcoming_queue(
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    today = datetime.now(timezone.utc).date()
    query = (
        select(Booking)
        .options(
            selectinload(Booking.items).selectinload(BookingItem.service),
            selectinload(Booking.items).selectinload(BookingItem.assigned_staff)
        )
        .where(
            Booking.branch_id == branch_id,
            Booking.booking_date == today,
            Booking.status.in_([BookingStatus.WAITING, BookingStatus.IN_PROGRESS])
        )
        .order_by(Booking.token_number.asc())
        .limit(5)
    )
    bookings = (await db.execute(query)).scalars().all()

    response = []
    for b in bookings:
        service_names = [it.service.name for it in b.items if it.service]
        assigned_names = list({it.assigned_staff.full_name for it in b.items if it.assigned_staff})
        staff_str = ", ".join(assigned_names) if assigned_names else "Auto-Assign"

        response.append(
            UpcomingQueueItem(
                booking_id=b.id,
                booking_number=b.booking_number,
                token_number=b.token_number,
                customer_name=b.customer_name,
                customer_phone=b.customer_phone,
                services_summary=", ".join(service_names) if service_names else "General",
                slot_time=b.slot_start_time,
                assigned_staff_name=staff_str,
                status=b.status
            )
        )

    return response


# ==========================================
# 3. DUAL Y-AXIS LINE CHART ANALYTICS
# ==========================================

@router.get("/analytics/revenue-chart", response_model=RevenueChartResponse)
async def get_revenue_chart(
    timeframe: str = Query("7_days", pattern="^(7_days|14_days|1_month|1_year|all)$"),
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    today = datetime.now(timezone.utc).date()

    days_map = {
        "7_days": 7,
        "14_days": 14,
        "1_month": 30,
        "1_year": 365,
        "all": 365
    }
    days = days_map.get(timeframe, 7)
    start_date = today - timedelta(days=days - 1)
    prev_start_date = start_date - timedelta(days=days)

    # 1. Fetch current period bookings and payments
    query = (
        select(
            Booking.booking_date,
            func.count(Booking.id).label("booking_count"),
            func.coalesce(func.sum(PaymentRecord.amount), 0.0).label("revenue")
        )
        .outerjoin(PaymentRecord, and_(PaymentRecord.booking_id == Booking.id, PaymentRecord.payment_status == PaymentStatus.PAID))
        .where(
            Booking.branch_id == branch_id,
            Booking.booking_date >= start_date,
            Booking.booking_date <= today
        )
        .group_by(Booking.booking_date)
    )
    records = (await db.execute(query)).all()
    data_by_date = {row.booking_date: (float(row.revenue), int(row.booking_count)) for row in records}

    # Build dense chronological data points
    data_points = []
    total_rev = 0.0
    total_bk = 0

    curr = start_date
    while curr <= today:
        rev, bk = data_by_date.get(curr, (0.0, 0))
        total_rev += rev
        total_bk += bk
        data_points.append(
            RevenueChartDataPoint(
                date_label=curr.strftime("%b %d"),
                revenue=rev,
                booking_count=bk,
                is_forecast=False
            )
        )
        curr += timedelta(days=1)

    # Simple moving average forecast for next 2 days
    avg_rev = total_rev / days if days > 0 else 0.0
    avg_bk = max(1, int(total_bk / days)) if days > 0 else 1
    for i in range(1, 3):
        forecast_date = today + timedelta(days=i)
        data_points.append(
            RevenueChartDataPoint(
                date_label=forecast_date.strftime("%b %d (Est)"),
                revenue=round(avg_rev * (1.05 ** i), 2),
                booking_count=avg_bk,
                is_forecast=True
            )
        )

    # 2. Fetch previous period metrics for comparison
    prev_query = (
        select(
            func.count(Booking.id).label("booking_count"),
            func.coalesce(func.sum(PaymentRecord.amount), 0.0).label("revenue")
        )
        .outerjoin(PaymentRecord, and_(PaymentRecord.booking_id == Booking.id, PaymentRecord.payment_status == PaymentStatus.PAID))
        .where(
            Booking.branch_id == branch_id,
            Booking.booking_date >= prev_start_date,
            Booking.booking_date < start_date
        )
    )
    prev_row = (await db.execute(prev_query)).one()
    prev_rev = float(prev_row.revenue) or 0.0
    prev_bk = int(prev_row.booking_count) or 0

    growth = 0.0
    if prev_rev > 0:
        growth = round(((total_rev - prev_rev) / prev_rev) * 100, 2)

    return RevenueChartResponse(
        timeframe=timeframe,
        data_points=data_points,
        total_period_revenue=round(total_rev, 2),
        total_period_bookings=total_bk,
        previous_period_revenue=round(prev_rev, 2),
        previous_period_bookings=prev_bk,
        growth_rate_percentage=growth
    )


# ==========================================
# 4. SHOP OPERATIONS CONTROLS
# ==========================================

@router.post("/operations/toggle-open")
async def toggle_shop_open(
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    today = datetime.now(timezone.utc).date()
    op = await _get_or_create_operation(branch_id, today, db)
    op.is_shop_open = not op.is_shop_open
    await db.commit()
    state = "OPEN" if op.is_shop_open else "CLOSED"
    return {"message": f"Shop is now {state}", "is_shop_open": op.is_shop_open}


@router.post("/operations/break")
async def toggle_shop_break(
    payload: OperationBreakRequest,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    today = datetime.now(timezone.utc).date()
    op = await _get_or_create_operation(branch_id, today, db)
    op.is_on_break = payload.is_on_break
    op.break_reason = payload.break_reason

    if payload.is_on_break and payload.break_duration_minutes:
        now = datetime.now(timezone.utc)
        return_dt = now + timedelta(minutes=payload.break_duration_minutes)
        op.break_expected_return = return_dt.time()
    else:
        op.break_expected_return = None

    await db.commit()
    return {
        "message": "Shop break updated",
        "is_on_break": op.is_on_break,
        "break_reason": op.break_reason,
        "break_expected_return": op.break_expected_return
    }


@router.post("/operations/holiday")
async def set_shop_holiday(
    payload: OperationHolidayRequest,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    op = await _get_or_create_operation(branch_id, payload.target_date, db)
    op.is_holiday = payload.is_holiday
    op.holiday_description = payload.holiday_description
    if payload.is_holiday:
        op.is_shop_open = False  # Auto-close on holiday

    await db.commit()
    return {
        "message": f"Holiday status for {payload.target_date} set to {payload.is_holiday}",
        "target_date": payload.target_date,
        "is_holiday": op.is_holiday,
        "description": op.holiday_description
    }
