import asyncio
import uuid
from datetime import datetime, timezone
from sqlalchemy import select

from core.database import engine, async_session_maker
from core.security import get_password_hash
from models.user import Base, User, UserRole
from models.internal_salon import Salon, Branch, SalonStatus
from models.client import (
    Service, StaffProfile, StaffRole,
    Booking, BookingItem, BookingType, BookingStatus,
    BranchOperation, PaymentRecord, PaymentMethod, PaymentStatus
)

async def test_flow():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_maker() as session:
        # 1. Ensure test salon and branch exist
        salon_res = await session.execute(select(Salon).where(Salon.slug == "demo-salon"))
        salon = salon_res.scalar_one_or_none()
        if not salon:
            salon = Salon(
                name="Demo Salon",
                slug="demo-salon",
                contact_email="demo@salon.ai",
                contact_phone="+919876543210",
                status=SalonStatus.ACTIVE
            )
            session.add(salon)
            await session.flush()

        branch_res = await session.execute(select(Branch).where(Branch.salon_id == salon.id))
        branch = branch_res.scalars().first()
        if not branch:
            branch = Branch(
                salon_id=salon.id,
                name="Main Branch",
                address="123 Barber Street",
                phone="+919876543210",
                is_active=True
            )
            session.add(branch)
            await session.flush()

        # 2. Add sample services
        srv_res = await session.execute(select(Service).where(Service.branch_id == branch.id))
        services = srv_res.scalars().all()
        if not services:
            s1 = Service(branch_id=branch.id, name="Haircut", category="Hair", duration_minutes=30, price=250.0)
            s2 = Service(branch_id=branch.id, name="Beard Trim", category="Beard", duration_minutes=20, price=150.0)
            s3 = Service(branch_id=branch.id, name="Facial Glow", category="Skin", duration_minutes=45, price=500.0)
            session.add_all([s1, s2, s3])
            await session.flush()
            services = [s1, s2, s3]

        # 3. Add sample stylist
        staff_res = await session.execute(select(StaffProfile).where(StaffProfile.branch_id == branch.id))
        staff = staff_res.scalars().first()
        if not staff:
            staff = StaffProfile(
                branch_id=branch.id,
                full_name="Alex Stylist",
                phone="+919876543211",
                role=StaffRole.STYLIST,
                is_active=True
            )
            session.add(staff)
            await session.flush()

        # 4. Create sample walk-in booking
        today = datetime.now(timezone.utc).date()
        booking = Booking(
            branch_id=branch.id,
            booking_number=f"BK-{today.strftime('%Y%m%d')}-001",
            token_number=1,
            customer_name="John Doe",
            customer_phone="+919999988888",
            booking_date=today,
            booking_type=BookingType.WALK_IN,
            status=BookingStatus.WAITING,
            total_amount=400.0
        )
        session.add(booking)
        await session.flush()

        item1 = BookingItem(
            booking_id=booking.id,
            service_id=services[0].id,
            assigned_staff_id=staff.id,
            item_price=services[0].price
        )
        item2 = BookingItem(
            booking_id=booking.id,
            service_id=services[1].id,
            assigned_staff_id=staff.id,
            item_price=services[1].price
        )
        session.add_all([item1, item2])

        await session.commit()
        print(f"✅ Test verification passed!")
        print(f"   Salon ID: {salon.id}")
        print(f"   Branch ID: {branch.id}")
        print(f"   Created Booking: {booking.booking_number} (Token #{booking.token_number}) with 2 items")

if __name__ == "__main__":
    asyncio.run(test_flow())
