import uuid
from datetime import datetime, date, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from core.database import get_db
from core.dependencies import get_current_client_user, get_active_branch_id
from core.security import get_password_hash
from models.user import User, UserRole
from models.client import (
    StaffProfile, StaffAttendance, CashHandover,
    AttendanceStatus, StaffRole, BookingItem, Booking, BookingStatus,
    PaymentRecord, PaymentMethod, PaymentStatus
)
from schemas.client import (
    StaffCreate, StaffUpdate, StaffResponse,
    CashHandoverCreate, CashHandoverResponse, StaffSummaryResponse
)

router = APIRouter(prefix="/client/staff", tags=["Client - Staff & Attendance"])


# ==========================================
# 1. STAFF PROFILES CRUD
# ==========================================

@router.get("", response_model=list[StaffResponse])
async def list_staff(
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    today = datetime.now(timezone.utc).date()
    # Fetch all staff in branch
    staff_result = await db.execute(
        select(StaffProfile).where(StaffProfile.branch_id == branch_id, StaffProfile.is_active == True)
    )
    staff_list = staff_result.scalars().all()

    response = []
    for staff in staff_list:
        # Check today's attendance status
        att_res = await db.execute(
            select(StaffAttendance).where(
                StaffAttendance.staff_id == staff.id,
                StaffAttendance.work_date == today
            )
        )
        att = att_res.scalar_one_or_none()
        current_status = att.current_status if att else AttendanceStatus.AVAILABLE

        item = StaffResponse.model_validate(staff)
        item.current_status = current_status
        response.append(item)

    return response


@router.post("", response_model=StaffResponse, status_code=status.HTTP_201_CREATED)
async def create_staff(
    payload: StaffCreate,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in [UserRole.SHOP_ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only salon managers can add staff")

    created_user_id = None
    # Optional login creation for this staff member
    if payload.email and payload.password:
        existing = await db.execute(select(User).where(User.email == payload.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

        user_role = UserRole.SHOP_ADMIN if payload.role == StaffRole.SHOP_ADMIN else UserRole.STAFF
        user = User(
            username=payload.email.split("@")[0] + f"_{uuid.uuid4().hex[:4]}",
            email=payload.email,
            hashed_password=get_password_hash(payload.password),
            role=user_role,
            is_active=True,
            shop_id=branch_id,
            salon_id=current_user.salon_id
        )
        db.add(user)
        await db.flush()
        created_user_id = user.id

    staff = StaffProfile(
        branch_id=branch_id,
        user_id=created_user_id,
        full_name=payload.full_name,
        phone=payload.phone,
        role=payload.role,
        is_active=True,
        default_lunch_start=payload.default_lunch_start,
        default_lunch_end=payload.default_lunch_end,
        commission_rate=payload.commission_rate
    )
    db.add(staff)
    await db.commit()
    await db.refresh(staff)
    return staff


@router.put("/{staff_id}", response_model=StaffResponse)
async def update_staff(
    staff_id: uuid.UUID,
    payload: StaffUpdate,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in [UserRole.SHOP_ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only salon managers can edit staff")

    result = await db.execute(select(StaffProfile).where(StaffProfile.id == staff_id, StaffProfile.branch_id == branch_id))
    staff = result.scalar_one_or_none()
    if not staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff member not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(staff, field, value)

    await db.commit()
    await db.refresh(staff)
    return staff


@router.delete("/{staff_id}")
async def delete_staff(
    staff_id: uuid.UUID,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in [UserRole.SHOP_ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only salon managers can remove staff")

    result = await db.execute(select(StaffProfile).where(StaffProfile.id == staff_id, StaffProfile.branch_id == branch_id))
    staff = result.scalar_one_or_none()
    if not staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff member not found")

    staff.is_active = False
    await db.commit()
    return {"message": f"Staff member '{staff.full_name}' deactivated successfully"}


# ==========================================
# 2. ATTENDANCE & SHIFT LIFECYCLE
# ==========================================

async def _get_staff_for_user(user: User, branch_id: uuid.UUID, db: AsyncSession) -> StaffProfile:
    result = await db.execute(
        select(StaffProfile).where(StaffProfile.user_id == user.id, StaffProfile.branch_id == branch_id)
    )
    staff = result.scalar_one_or_none()
    if not staff:
        # Fallback for admin if not explicitly linked as staff
        result_first = await db.execute(
            select(StaffProfile).where(StaffProfile.branch_id == branch_id, StaffProfile.is_active == True)
        )
        staff = result_first.scalars().first()
        if not staff:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No staff profile associated with this account")
    return staff


@router.post("/attendance/clock-in")
async def clock_in(
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    staff = await _get_staff_for_user(current_user, branch_id, db)
    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)

    att_res = await db.execute(
        select(StaffAttendance).where(StaffAttendance.staff_id == staff.id, StaffAttendance.work_date == today)
    )
    attendance = att_res.scalar_one_or_none()

    if not attendance:
        attendance = StaffAttendance(
            staff_id=staff.id,
            work_date=today,
            clock_in_at=now,
            current_status=AttendanceStatus.AVAILABLE
        )
        db.add(attendance)
    else:
        attendance.clock_in_at = attendance.clock_in_at or now
        attendance.current_status = AttendanceStatus.AVAILABLE

    await db.commit()
    return {"message": f"Clocked in successfully at {now.strftime('%H:%M')}", "status": attendance.current_status}


@router.post("/attendance/break")
async def take_break(
    is_lunch: bool = False,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    staff = await _get_staff_for_user(current_user, branch_id, db)
    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)

    att_res = await db.execute(
        select(StaffAttendance).where(StaffAttendance.staff_id == staff.id, StaffAttendance.work_date == today)
    )
    attendance = att_res.scalar_one_or_none()

    if not attendance:
        attendance = StaffAttendance(
            staff_id=staff.id,
            work_date=today,
            clock_in_at=now,
            break_start_at=now,
            current_status=AttendanceStatus.LUNCH if is_lunch else AttendanceStatus.ON_BREAK
        )
        db.add(attendance)
    else:
        attendance.break_start_at = now
        attendance.current_status = AttendanceStatus.LUNCH if is_lunch else AttendanceStatus.ON_BREAK

    await db.commit()
    return {"message": f"Break started at {now.strftime('%H:%M')}", "status": attendance.current_status}


@router.post("/attendance/resume")
async def resume_work(
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    staff = await _get_staff_for_user(current_user, branch_id, db)
    today = datetime.now(timezone.utc).date()

    att_res = await db.execute(
        select(StaffAttendance).where(StaffAttendance.staff_id == staff.id, StaffAttendance.work_date == today)
    )
    attendance = att_res.scalar_one_or_none()

    if not attendance:
        attendance = StaffAttendance(
            staff_id=staff.id,
            work_date=today,
            clock_in_at=datetime.now(timezone.utc),
            current_status=AttendanceStatus.AVAILABLE
        )
        db.add(attendance)
    else:
        attendance.current_status = AttendanceStatus.AVAILABLE
        attendance.break_start_at = None

    await db.commit()
    return {"message": "Resumed work. You are now AVAILABLE for appointments.", "status": attendance.current_status}


@router.post("/attendance/clock-out")
async def clock_out(
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    staff = await _get_staff_for_user(current_user, branch_id, db)
    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)

    att_res = await db.execute(
        select(StaffAttendance).where(StaffAttendance.staff_id == staff.id, StaffAttendance.work_date == today)
    )
    attendance = att_res.scalar_one_or_none()

    if not attendance:
        attendance = StaffAttendance(
            staff_id=staff.id,
            work_date=today,
            clock_out_at=now,
            current_status=AttendanceStatus.ON_LEAVE
        )
        db.add(attendance)
    else:
        attendance.clock_out_at = now
        attendance.current_status = AttendanceStatus.ON_LEAVE

    await db.commit()
    return {"message": f"Clocked out successfully at {now.strftime('%H:%M')}", "status": attendance.current_status}


# ==========================================
# 3. CASH HANDOVER & PERSONAL SUMMARY
# ==========================================

@router.post("/cash-handover", response_model=CashHandoverResponse)
async def record_cash_handover(
    payload: CashHandoverCreate,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    handover = CashHandover(
        branch_id=branch_id,
        staff_id=payload.staff_id,
        cash_collected=payload.cash_collected,
        cash_handed_over=payload.cash_handed_over,
        notes=payload.notes,
        handover_at=datetime.now(timezone.utc)
    )
    db.add(handover)
    await db.commit()
    await db.refresh(handover)
    return handover


@router.get("/my-summary", response_model=StaffSummaryResponse)
async def get_my_summary(
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    staff = await _get_staff_for_user(current_user, branch_id, db)
    today = datetime.now(timezone.utc).date()

    # Query tasks assigned to this staff for today
    base_query = (
        select(BookingItem, Booking)
        .join(Booking, BookingItem.booking_id == Booking.id)
        .where(
            BookingItem.assigned_staff_id == staff.id,
            Booking.booking_date == today,
            Booking.branch_id == branch_id
        )
    )
    results = (await db.execute(base_query)).all()

    waiting = sum(1 for item, b in results if b.status == BookingStatus.WAITING)
    completed = sum(1 for item, b in results if b.status == BookingStatus.COMPLETED)
    total = len(results)

    # Calculate revenue collected by this staff member today
    pay_query = select(PaymentRecord).where(
        PaymentRecord.collected_by_staff_id == staff.id,
        PaymentRecord.payment_status == PaymentStatus.PAID,
        func.date(PaymentRecord.paid_at) == today
    )
    payments = (await db.execute(pay_query)).scalars().all()

    cash_coll = sum(p.amount for p in payments if p.payment_method == PaymentMethod.CASH)
    digital_coll = sum(p.amount for p in payments if p.payment_method != PaymentMethod.CASH)

    return StaffSummaryResponse(
        staff_id=staff.id,
        staff_name=staff.full_name,
        today_waiting_tasks=waiting,
        today_completed_tasks=completed,
        today_total_tasks=total,
        today_cash_collected=cash_coll,
        today_digital_collected=digital_coll,
        today_total_revenue=cash_coll + digital_coll
    )
