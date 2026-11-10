import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import get_db
from core.dependencies import get_current_client_user, get_active_branch_id
from models.user import User, UserRole
from models.client import (
    Booking, BookingItem, Service, StaffProfile,
    BookingStatus, PaymentRecord, PaymentStatus
)
from schemas.client import (
    TaskItemResponse, TaskCancelRequest, PaymentCollectRequest,
    TaskReassignRequest, TaskRescheduleRequest
)

router = APIRouter(prefix="/client/tasks", tags=["Client - Task Board & Chairs"])


@router.get("/board", response_model=list[TaskItemResponse])
async def get_task_board(
    staff_filter_id: uuid.UUID | None = None,
    status_filter: BookingStatus | None = None,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    # If logged in user is a STYLIST, restrict board to their own assigned chair
    logged_in_staff = None
    if current_user.role == UserRole.STAFF:
        staff_res = await db.execute(
            select(StaffProfile).where(StaffProfile.user_id == current_user.id, StaffProfile.branch_id == branch_id)
        )
        logged_in_staff = staff_res.scalar_one_or_none()
        if logged_in_staff:
            staff_filter_id = logged_in_staff.id

    query = (
        select(BookingItem)
        .join(Booking, BookingItem.booking_id == Booking.id)
        .options(
            selectinload(BookingItem.booking).selectinload(Booking.payment),
            selectinload(BookingItem.service),
            selectinload(BookingItem.assigned_staff)
        )
        .where(Booking.branch_id == branch_id)
    )

    if staff_filter_id:
        query = query.where(BookingItem.assigned_staff_id == staff_filter_id)

    if status_filter:
        query = query.where(Booking.status == status_filter)
    else:
        # Default active board shows WAITING and IN_PROGRESS tasks
        query = query.where(Booking.status.in_([BookingStatus.WAITING, BookingStatus.IN_PROGRESS]))

    query = query.order_by(Booking.token_number.asc())
    items = (await db.execute(query)).scalars().all()

    response = []
    for item in items:
        b = item.booking
        pay = b.payment
        res = TaskItemResponse(
            booking_item_id=item.id,
            booking_id=b.id,
            booking_number=b.booking_number,
            token_number=b.token_number,
            customer_name=b.customer_name,
            customer_phone=b.customer_phone,
            service_id=item.service_id,
            service_name=item.service.name if item.service else "Service",
            duration_minutes=item.service.duration_minutes if item.service else 30,
            item_price=item.item_price,
            assigned_staff_id=item.assigned_staff_id,
            assigned_staff_name=item.assigned_staff.full_name if item.assigned_staff else "Unassigned",
            booking_status=b.status,
            service_started_at=item.service_started_at,
            service_completed_at=item.service_completed_at,
            actual_duration_minutes=item.actual_duration_minutes,
            payment_status=pay.payment_status if pay else PaymentStatus.PENDING,
            payment_method=pay.payment_method if pay else None
        )
        response.append(res)

    return response


@router.post("/{booking_item_id}/start")
async def start_service(
    booking_item_id: uuid.UUID,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    query = (
        select(BookingItem)
        .join(Booking)
        .where(BookingItem.id == booking_item_id, Booking.branch_id == branch_id)
    )
    item = (await db.execute(query)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task item not found")

    now = datetime.now(timezone.utc)
    item.service_started_at = now

    # Update parent booking status to IN_PROGRESS
    booking_res = await db.execute(select(Booking).where(Booking.id == item.booking_id))
    booking = booking_res.scalar_one_or_none()
    if booking:
        booking.status = BookingStatus.IN_PROGRESS

    await db.commit()
    return {
        "message": f"Service started at {now.strftime('%H:%M:%S')}",
        "booking_item_id": item.id,
        "service_started_at": item.service_started_at,
        "status": BookingStatus.IN_PROGRESS
    }


@router.post("/{booking_item_id}/complete")
async def complete_service(
    booking_item_id: uuid.UUID,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    query = (
        select(BookingItem)
        .join(Booking)
        .where(BookingItem.id == booking_item_id, Booking.branch_id == branch_id)
    )
    item = (await db.execute(query)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task item not found")

    now = datetime.now(timezone.utc)
    item.service_completed_at = now

    # Compute actual duration in minutes
    if item.service_started_at:
        delta = now - item.service_started_at
        item.actual_duration_minutes = max(1, int(delta.total_seconds() / 60))

    # Check if all items in this booking are completed
    all_items_res = await db.execute(
        select(BookingItem).where(BookingItem.booking_id == item.booking_id)
    )
    all_items = all_items_res.scalars().all()
    all_done = all(it.service_completed_at is not None for it in all_items)

    booking_res = await db.execute(select(Booking).where(Booking.id == item.booking_id))
    booking = booking_res.scalar_one_or_none()
    if booking and all_done:
        booking.status = BookingStatus.COMPLETED

    await db.commit()
    return {
        "message": "Service completed successfully. Please prompt for payment.",
        "booking_item_id": item.id,
        "actual_duration_minutes": item.actual_duration_minutes,
        "booking_status": booking.status if booking else BookingStatus.COMPLETED,
        "all_items_completed": all_done
    }


@router.post("/{booking_id}/cancel")
async def cancel_booking_task(
    booking_id: uuid.UUID,
    payload: TaskCancelRequest,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Booking).where(Booking.id == booking_id, Booking.branch_id == branch_id))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    booking.status = BookingStatus.CANCELLED
    booking.cancellation_reason = payload.cancellation_reason
    await db.commit()
    return {"message": "Booking has been cancelled / dropped", "reason": payload.cancellation_reason}


@router.post("/{booking_id}/collect-payment")
async def collect_payment(
    booking_id: uuid.UUID,
    payload: PaymentCollectRequest,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Booking).where(Booking.id == booking_id, Booking.branch_id == branch_id))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    # Find staff collecting payment
    staff_res = await db.execute(
        select(StaffProfile).where(StaffProfile.user_id == current_user.id, StaffProfile.branch_id == branch_id)
    )
    staff = staff_res.scalar_one_or_none()

    pay_res = await db.execute(select(PaymentRecord).where(PaymentRecord.booking_id == booking_id))
    payment = pay_res.scalar_one_or_none()

    pay_status = PaymentStatus.PAID if payload.is_paid else PaymentStatus.PENDING

    if not payment:
        payment = PaymentRecord(
            booking_id=booking.id,
            collected_by_staff_id=staff.id if staff else None,
            amount=payload.amount,
            payment_method=payload.payment_method,
            payment_status=pay_status,
            paid_at=datetime.now(timezone.utc)
        )
        db.add(payment)
    else:
        payment.amount = payload.amount
        payment.payment_method = payload.payment_method
        payment.payment_status = pay_status
        payment.collected_by_staff_id = staff.id if staff else payment.collected_by_staff_id

    await db.commit()
    return {
        "message": "Payment recorded successfully",
        "booking_id": booking.id,
        "amount": payment.amount,
        "payment_method": payment.payment_method,
        "payment_status": payment.payment_status
    }


@router.patch("/{booking_item_id}/reassign")
async def reassign_task(
    booking_item_id: uuid.UUID,
    payload: TaskReassignRequest,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    query = (
        select(BookingItem)
        .join(Booking)
        .where(BookingItem.id == booking_item_id, Booking.branch_id == branch_id)
    )
    item = (await db.execute(query)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task item not found")

    # Verify target staff exists in this branch
    staff_res = await db.execute(
        select(StaffProfile).where(StaffProfile.id == payload.new_staff_id, StaffProfile.branch_id == branch_id)
    )
    new_staff = staff_res.scalar_one_or_none()
    if not new_staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target staff not found in this branch")

    item.assigned_staff_id = new_staff.id
    await db.commit()
    return {"message": f"Task reassigned to {new_staff.full_name}", "assigned_staff_id": new_staff.id}


@router.patch("/{booking_id}/reschedule")
async def reschedule_booking(
    booking_id: uuid.UUID,
    payload: TaskRescheduleRequest,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Booking).where(Booking.id == booking_id, Booking.branch_id == branch_id))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    booking.slot_start_time = payload.new_start_time
    if payload.new_end_time:
        booking.slot_end_time = payload.new_end_time
    await db.commit()
    return {"message": "Booking rescheduled successfully", "slot_start_time": booking.slot_start_time}
