from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core.database import get_session
from app.models.notification import Notification
from app.models.support_ticket import SupportTicket, TicketResponse
from app.models.user import User


async def _notify_staff(
    session: AsyncSession,
    title: str,
    body: str,
    ticket_id: int,
    notif_type: str = "ticket_new",
    exclude_user_id: int | None = None,
):
    """Create a notification for every support/admin user."""
    staff = (
        await session.execute(select(User).where(User.role.in_(["admin", "support"])))
    ).scalars().all()
    for u in staff:
        if u.id == exclude_user_id:
            continue
        session.add(Notification(user_id=u.id, type=notif_type, title=title, body=body, ticket_id=ticket_id))


async def _notify_user(session: AsyncSession, user_id: int, notif_type: str, title: str, body: str, ticket_id: int):
    """Create a notification for a specific user."""
    session.add(Notification(user_id=user_id, type=notif_type, title=title, body=body, ticket_id=ticket_id))

router = APIRouter(prefix="/support", tags=["support"])

VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}
VALID_CATEGORIES = {"bug", "feature", "question", "billing", "security", "integration"}
VALID_PRIORITIES = {"low", "medium", "high", "urgent"}


def _is_staff(user: User) -> bool:
    return user.role in ("admin", "support")


async def require_staff(current_user: User = Depends(get_current_user)) -> User:
    if not _is_staff(current_user):
        raise HTTPException(status_code=403, detail="Support staff access required")
    return current_user


# ── Schemas ───────────────────────────────────────────────────────────────────

class TicketCreate(BaseModel):
    name: str
    email: str
    subject: str
    category: str
    priority: str
    description: str


class TicketResponseCreate(BaseModel):
    message: str


class StatusUpdate(BaseModel):
    status: str


class TicketResponseRead(BaseModel):
    id: int
    responder_name: str
    message: str
    is_staff: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TicketRead(BaseModel):
    id: int
    user_id: int | None
    name: str
    email: str
    subject: str
    category: str
    priority: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime
    response_count: int = 0
    responses: list[TicketResponseRead] = []

    model_config = {"from_attributes": True}


# ── Create ticket (any authenticated user) ────────────────────────────────────

@router.post("/tickets", response_model=TicketRead)
async def create_ticket(
    data: TicketCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if data.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=422, detail="Invalid category")
    if data.priority not in VALID_PRIORITIES:
        raise HTTPException(status_code=422, detail="Invalid priority")
    if not data.subject.strip():
        raise HTTPException(status_code=422, detail="Subject is required")
    if not data.description.strip():
        raise HTTPException(status_code=422, detail="Description is required")

    ticket = SupportTicket(
        user_id=current_user.id,
        name=data.name.strip(),
        email=data.email.strip(),
        subject=data.subject.strip(),
        category=data.category,
        priority=data.priority,
        description=data.description.strip(),
        status="open",
    )
    session.add(ticket)
    await session.flush()  # get ticket.id before notifications

    await _notify_staff(
        session,
        title=f"New ticket: {data.subject[:80]}",
        body=f"From {data.name} · {data.category} · {data.priority} priority",
        ticket_id=ticket.id,
        exclude_user_id=current_user.id,
    )

    await session.commit()
    await session.refresh(ticket)

    result = TicketRead.model_validate(ticket)
    result.response_count = 0
    result.responses = []
    return result


# ── My tickets (any authenticated user) ──────────────────────────────────────

@router.get("/my-tickets", response_model=list[TicketRead])
async def get_my_tickets(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    rows = (
        await session.execute(
            select(SupportTicket)
            .where(SupportTicket.user_id == current_user.id)
            .order_by(SupportTicket.created_at.desc())
        )
    ).scalars().all()

    results = []
    for t in rows:
        resp_count = (
            await session.execute(
                select(func.count()).where(TicketResponse.ticket_id == t.id)
            )
        ).scalar() or 0
        item = TicketRead.model_validate(t)
        item.response_count = resp_count
        item.responses = []
        results.append(item)
    return results


# ── List all tickets (staff only) ────────────────────────────────────────────

@router.get("/tickets", response_model=list[TicketRead])
async def list_tickets(
    status: str | None = Query(None),
    priority: str | None = Query(None),
    category: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
):
    q = select(SupportTicket).order_by(SupportTicket.created_at.desc())
    if status:
        q = q.where(SupportTicket.status == status)
    if priority:
        q = q.where(SupportTicket.priority == priority)
    if category:
        q = q.where(SupportTicket.category == category)
    if search:
        like = f"%{search}%"
        q = q.where(
            SupportTicket.subject.ilike(like) |
            SupportTicket.email.ilike(like) |
            SupportTicket.name.ilike(like)
        )
    q = q.offset(offset).limit(limit)
    rows = (await session.execute(q)).scalars().all()

    results = []
    for t in rows:
        resp_count = (
            await session.execute(
                select(func.count()).where(TicketResponse.ticket_id == t.id)
            )
        ).scalar() or 0
        item = TicketRead.model_validate(t)
        item.response_count = resp_count
        item.responses = []
        results.append(item)
    return results


# ── Ticket stats (staff only) ─────────────────────────────────────────────────

@router.get("/stats")
async def ticket_stats(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
):
    totals = {}
    for s in ("open", "in_progress", "resolved", "closed"):
        totals[s] = (
            await session.execute(
                select(func.count()).where(SupportTicket.status == s)
            )
        ).scalar() or 0
    totals["total"] = sum(totals.values())
    return totals


# ── Get single ticket with responses ─────────────────────────────────────────

@router.get("/tickets/{ticket_id}", response_model=TicketRead)
async def get_ticket(
    ticket_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ticket = (
        await session.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ).scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Owner or staff can view
    if not _is_staff(current_user) and ticket.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    responses_rows = (
        await session.execute(
            select(TicketResponse)
            .where(TicketResponse.ticket_id == ticket_id)
            .order_by(TicketResponse.created_at.asc())
        )
    ).scalars().all()

    item = TicketRead.model_validate(ticket)
    item.responses = [TicketResponseRead.model_validate(r) for r in responses_rows]
    item.response_count = len(item.responses)
    return item


# ── Add response ──────────────────────────────────────────────────────────────

@router.post("/tickets/{ticket_id}/responses", response_model=TicketResponseRead)
async def add_response(
    ticket_id: int,
    data: TicketResponseCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ticket = (
        await session.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ).scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    is_staff_user = _is_staff(current_user)
    if not is_staff_user and ticket.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    if not data.message.strip():
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    response = TicketResponse(
        ticket_id=ticket_id,
        responder_id=current_user.id,
        responder_name=current_user.full_name or current_user.username,
        message=data.message.strip(),
        is_staff=is_staff_user,
    )
    session.add(response)

    # Auto-advance status
    if is_staff_user and ticket.status == "open":
        ticket.status = "in_progress"
    ticket.updated_at = datetime.now(timezone.utc)

    # Fire notifications
    if is_staff_user:
        # Staff replied → notify the ticket owner
        if ticket.user_id and ticket.user_id != current_user.id:
            await _notify_user(
                session,
                user_id=ticket.user_id,
                notif_type="ticket_response",
                title=f"Support replied to: {ticket.subject[:80]}",
                body=data.message[:160],
                ticket_id=ticket.id,
            )
    else:
        # User added a follow-up → notify all staff
        await _notify_staff(
            session,
            title=f"Follow-up on: {ticket.subject[:80]}",
            body=f"From {current_user.full_name or current_user.username}: {data.message[:120]}",
            ticket_id=ticket.id,
            notif_type="ticket_followup",
            exclude_user_id=current_user.id,
        )

    await session.commit()
    await session.refresh(response)
    return TicketResponseRead.model_validate(response)


# ── Update ticket status (staff only) ────────────────────────────────────────

@router.patch("/tickets/{ticket_id}/status")
async def update_status(
    ticket_id: int,
    data: StatusUpdate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
):
    if data.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Status must be one of: {VALID_STATUSES}")

    ticket = (
        await session.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ).scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.status = data.status
    ticket.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return {"id": ticket_id, "status": data.status}
