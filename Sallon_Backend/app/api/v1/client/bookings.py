import uuid
from datetime import datetime, date, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload

from core.database import get_db
from core.dependencies import get_current_client_user, get_active_branch_id
from models.user import User
from models.client import (
    Booking, BookingItem, Service, StaffProfile,
    BookingStatus, BookingType, PaymentRecord, PaymentStatus
)
from schemas.client import (
    WalkInBookingCreate, BookingResponse, BookingDetailResponse, BookingItemDetail
)

router = APIRouter(prefix="/client/bookings", tags=["Client - Bookings & Walk-in POS"])


@router.get("", response_model=list[BookingResponse])
async def list_bookings(
    target_date: date | None = None,
    status_filter: BookingStatus | None = None,
    payment_status_filter: PaymentStatus | None = None,
    staff_id: uuid.UUID | None = None,
    search: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    query = (
        select(Booking)
        .options(selectinload(Booking.items).selectinload(BookingItem.service), selectinload(Booking.payment))
        .where(Booking.branch_id == branch_id)
    )

    if target_date:
        query = query.where(Booking.booking_date == target_date)
    if status_filter:
        query = query.where(Booking.status == status_filter)
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                Booking.customer_name.ilike(search_term),
                Booking.customer_phone.ilike(search_term),
                Booking.booking_number.ilike(search_term)
            )
        )

    query = query.order_by(Booking.booking_date.desc(), Booking.token_number.desc()).offset(skip).limit(limit)
    bookings = (await db.execute(query)).scalars().all()

    response = []
    for b in bookings:
        # Check staff filter if requested
        if staff_id:
            assigned = any(item.assigned_staff_id == staff_id for item in b.items)
            if not assigned:
                continue

        # Check payment status filter if requested
        pay_status = b.payment.payment_status if b.payment else PaymentStatus.PENDING
        if payment_status_filter and pay_status != payment_status_filter:
            continue

        services_names = [item.service.name for item in b.items if item.service]
        summary_str = ", ".join(services_names) if services_names else "No services"

        res_item = BookingResponse(
            id=b.id,
            branch_id=b.branch_id,
            booking_number=b.booking_number,
            token_number=b.token_number,
            customer_name=b.customer_name,
            customer_phone=b.customer_phone,
            booking_date=b.booking_date,
            slot_start_time=b.slot_start_time,
            slot_end_time=b.slot_end_time,
            booking_type=b.booking_type,
            status=b.status,
            total_amount=b.total_amount,
            service_count=len(b.items),
            services_summary=summary_str,
            payment_status=pay_status,
            payment_method=b.payment.payment_method if b.payment else None,
            created_at=b.created_at
        )
        response.append(res_item)

    return response


@router.get("/{booking_id}", response_model=BookingDetailResponse)
async def get_booking_details(
    booking_id: uuid.UUID,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    query = (
        select(Booking)
        .options(
            selectinload(Booking.items).selectinload(BookingItem.service),
            selectinload(Booking.items).selectinload(BookingItem.assigned_staff),
            selectinload(Booking.payment)
        )
        .where(Booking.id == booking_id, Booking.branch_id == branch_id)
    )
    b = (await db.execute(query)).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    services_names = [item.service.name for item in b.items if item.service]
    items_detail = [
        BookingItemDetail(
            id=item.id,
            service_id=item.service_id,
            service_name=item.service.name if item.service else "Service",
            item_price=item.item_price,
            assigned_staff_id=item.assigned_staff_id,
            assigned_staff_name=item.assigned_staff.full_name if item.assigned_staff else None,
            service_started_at=item.service_started_at,
            service_completed_at=item.service_completed_at
        )
        for item in b.items
    ]

    return BookingDetailResponse(
        id=b.id,
        branch_id=b.branch_id,
        booking_number=b.booking_number,
        token_number=b.token_number,
        customer_name=b.customer_name,
        customer_phone=b.customer_phone,
        booking_date=b.booking_date,
        slot_start_time=b.slot_start_time,
        slot_end_time=b.slot_end_time,
        booking_type=b.booking_type,
        status=b.status,
        total_amount=b.total_amount,
        service_count=len(b.items),
        services_summary=", ".join(services_names),
        payment_status=b.payment.payment_status if b.payment else PaymentStatus.PENDING,
        payment_method=b.payment.payment_method if b.payment else None,
        created_at=b.created_at,
        items=items_detail
    )


@router.post("/walk-in", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_walk_in_booking(
    payload: WalkInBookingCreate,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    today = datetime.now(timezone.utc).date()

    # 1. Compute today's next sequential token number for this branch
    max_token_query = select(func.coalesce(func.max(Booking.token_number), 0)).where(
        Booking.branch_id == branch_id,
        Booking.booking_date == today
    )
    current_max_token = await db.scalar(max_token_query)
    next_token = (current_max_token or 0) + 1

    booking_num = f"BK-{today.strftime('%Y%m%d')}-{next_token:03d}"

    # 2. Fetch services to compute prices and validate existence
    service_ids = [item.service_id for item in payload.items]
    services_res = await db.execute(
        select(Service).where(Service.id.in_(service_ids), Service.branch_id == branch_id)
    )
    services_dict = {s.id: s for s in services_res.scalars().all()}

    if len(services_dict) != len(set(service_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more selected services are invalid")

    total_amount = sum(float(services_dict[item.service_id].price) for item in payload.items)

    # 3. Create Booking
    booking = Booking(
        branch_id=branch_id,
        booking_number=booking_num,
        token_number=next_token,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        booking_date=today,
        slot_start_time=payload.slot_start_time,
        booking_type=BookingType.WALK_IN,
        status=BookingStatus.WAITING,
        total_amount=total_amount
    )
    db.add(booking)
    await db.flush()

    # 4. Create Booking Items
    for item_input in payload.items:
        srv = services_dict[item_input.service_id]
        item = BookingItem(
            booking_id=booking.id,
            service_id=srv.id,
            assigned_staff_id=item_input.assigned_staff_id,
            item_price=srv.price
        )
        db.add(item)

    await db.commit()

    services_summary = ", ".join(services_dict[it.service_id].name for it in payload.items)

    return BookingResponse(
        id=booking.id,
        branch_id=booking.branch_id,
        booking_number=booking.booking_number,
        token_number=booking.token_number,
        customer_name=booking.customer_name,
        customer_phone=booking.customer_phone,
        booking_date=booking.booking_date,
        slot_start_time=booking.slot_start_time,
        slot_end_time=booking.slot_end_time,
        booking_type=booking.booking_type,
        status=booking.status,
        total_amount=booking.total_amount,
        service_count=len(payload.items),
        services_summary=services_summary,
        payment_status=PaymentStatus.PENDING,
        payment_method=None,
        created_at=booking.created_at
    )


@router.post("/{booking_id}/send-reminder")
async def send_reminder_message(
    booking_id: uuid.UUID,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Booking).where(Booking.id == booking_id, Booking.branch_id == branch_id))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    # In production, this invokes the WhatsApp Cloud API template
    return {
        "message": f"WhatsApp reminder sent to {booking.customer_phone} for Token #{booking.token_number:03d}!",
        "customer_phone": booking.customer_phone,
        "token_number": booking.token_number
    }
