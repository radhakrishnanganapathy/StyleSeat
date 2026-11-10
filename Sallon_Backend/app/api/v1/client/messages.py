import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import get_db
from core.dependencies import get_current_client_user, get_active_branch_id
from models.user import User
from models.client import (
    WhatsAppConversation, WhatsAppMessage, CannedResponse,
    StaffProfile, MessageSenderType, DeliveryStatus
)
from schemas.client import (
    SendMessageRequest, MessageResponse, ConversationResponse,
    CannedResponseCreate, CannedResponseItem
)

router = APIRouter(prefix="/client/messages", tags=["Client - Direct WhatsApp Messaging"])


# ==========================================
# 1. CONVERSATIONS & CHAT THREADS
# ==========================================

@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    query = (
        select(WhatsAppConversation)
        .where(WhatsAppConversation.branch_id == branch_id)
        .order_by(WhatsAppConversation.last_message_at.desc())
    )
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/conversations/{conversation_id}", response_model=list[MessageResponse])
async def get_conversation_messages(
    conversation_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify conversation belongs to branch
    conv_res = await db.execute(
        select(WhatsAppConversation).where(
            WhatsAppConversation.id == conversation_id,
            WhatsAppConversation.branch_id == branch_id
        )
    )
    conv = conv_res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # Mark unread count as 0
    conv.unread_count_admin = 0
    await db.commit()

    query = (
        select(WhatsAppMessage)
        .where(WhatsAppMessage.conversation_id == conversation_id)
        .order_by(WhatsAppMessage.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    messages = (await db.execute(query)).scalars().all()
    return messages


# ==========================================
# 2. SEND DIRECT WHATSAPP MESSAGE (WITH AI HANDOVER)
# ==========================================

@router.post("/send", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_whatsapp_message(
    payload: SendMessageRequest,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    now = datetime.now(timezone.utc)

    # 1. Find or create conversation for this customer phone
    conv_res = await db.execute(
        select(WhatsAppConversation).where(
            WhatsAppConversation.branch_id == branch_id,
            WhatsAppConversation.customer_phone == payload.customer_phone
        )
    )
    conv = conv_res.scalar_one_or_none()

    if not conv:
        conv = WhatsAppConversation(
            branch_id=branch_id,
            customer_phone=payload.customer_phone,
            customer_name=payload.customer_name,
            last_message_at=now,
            last_message_preview=payload.message_text[:100],
            unread_count_admin=0,
            is_ai_bot_active=False,
            ai_bot_paused_until=now + timedelta(minutes=30)  # AI Handover
        )
        db.add(conv)
        await db.flush()
    else:
        conv.last_message_at = now
        conv.last_message_preview = payload.message_text[:100]
        if payload.customer_name and not conv.customer_name:
            conv.customer_name = payload.customer_name
        # Human agent intervened: Auto-pause AI bot for 30 minutes
        conv.is_ai_bot_active = False
        conv.ai_bot_paused_until = now + timedelta(minutes=30)

    # 2. Find sender staff profile
    staff_res = await db.execute(
        select(StaffProfile).where(StaffProfile.user_id == current_user.id, StaffProfile.branch_id == branch_id)
    )
    staff = staff_res.scalar_one_or_none()

    # 3. Create outbound WhatsApp message
    msg = WhatsAppMessage(
        conversation_id=conv.id,
        sender_type=MessageSenderType.ADMIN,
        sender_staff_id=staff.id if staff else None,
        message_text=payload.message_text,
        media_url=payload.media_url,
        delivery_status=DeliveryStatus.SENT,
        created_at=now
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    # Note: In production with live Meta API, this also calls Meta Cloud API /messages
    return msg


@router.post("/conversations/{conversation_id}/toggle-ai")
async def toggle_ai_bot(
    conversation_id: uuid.UUID,
    enable_ai: bool,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    conv_res = await db.execute(
        select(WhatsAppConversation).where(
            WhatsAppConversation.id == conversation_id,
            WhatsAppConversation.branch_id == branch_id
        )
    )
    conv = conv_res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    conv.is_ai_bot_active = enable_ai
    if enable_ai:
        conv.ai_bot_paused_until = None
    else:
        conv.ai_bot_paused_until = datetime.now(timezone.utc) + timedelta(hours=24)

    await db.commit()
    status_str = "ACTIVE" if enable_ai else "PAUSED"
    return {"message": f"AI Bot is now {status_str} for {conv.customer_phone}", "is_ai_bot_active": conv.is_ai_bot_active}


# ==========================================
# 3. CANNED QUICK RESPONSES
# ==========================================

@router.get("/canned-responses", response_model=list[CannedResponseItem])
async def list_canned_responses(
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(CannedResponse).where(CannedResponse.branch_id == branch_id)
    )
    responses = result.scalars().all()

    # Pre-seed default templates if empty
    if not responses:
        defaults = [
            CannedResponse(branch_id=branch_id, title="Chair Ready", message_text="💈 Your chair is ready! Please proceed inside."),
            CannedResponse(branch_id=branch_id, title="15 Min Delay", message_text="⏱️ We are running approximately 15 minutes behind schedule. Thank you for your patience!"),
            CannedResponse(branch_id=branch_id, title="Haircut Reference", message_text="✂️ Please share a reference photo of the hairstyle you would like."),
            CannedResponse(branch_id=branch_id, title="Location Pin", message_text="📍 Here is our salon location: https://maps.google.com")
        ]
        db.add_all(defaults)
        await db.commit()
        result = await db.execute(select(CannedResponse).where(CannedResponse.branch_id == branch_id))
        responses = result.scalars().all()

    return responses


@router.post("/canned-responses", response_model=CannedResponseItem, status_code=status.HTTP_201_CREATED)
async def create_canned_response(
    payload: CannedResponseCreate,
    branch_id: uuid.UUID = Depends(get_active_branch_id),
    current_user: User = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db)
):
    item = CannedResponse(
        branch_id=branch_id,
        title=payload.title,
        message_text=payload.message_text
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item
