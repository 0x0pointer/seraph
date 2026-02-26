from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, update, func, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core.database import get_session
from app.models.announcement import Announcement, AnnouncementRead as AnnRead
from app.models.notification import Notification
from app.models.user import User

router = APIRouter(prefix="/notifications", tags=["notifications"])


class UnifiedNotif(BaseModel):
    """Single item in the notification feed — either a personal notification or a broadcast announcement."""
    id: int
    source: str        # "notification" | "announcement"
    type: str          # ticket_new | ticket_response | ticket_followup | announcement | news
    title: str
    body: str | None = None
    ticket_id: int | None = None
    is_read: bool
    created_at: datetime


# ── Unread count (personal + announcements) ───────────────────────────────────

@router.get("/unread-count")
async def unread_count(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    personal = (
        await session.execute(
            select(func.count()).where(
                Notification.user_id == current_user.id,
                Notification.is_read == False,  # noqa: E712
            )
        )
    ).scalar() or 0

    # Active announcements this user hasn't read
    read_ann_ids = (
        await session.execute(
            select(AnnRead.announcement_id).where(AnnRead.user_id == current_user.id)
        )
    ).scalars().all()

    ann_unread = (
        await session.execute(
            select(func.count()).where(
                Announcement.is_active == True,  # noqa: E712
                Announcement.id.not_in(read_ann_ids) if read_ann_ids else True,
            )
        )
    ).scalar() or 0

    return {"count": personal + ann_unread}


# ── Unified notification list ─────────────────────────────────────────────────

@router.get("", response_model=list[UnifiedNotif])
async def list_notifications(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    # Personal notifications
    personal_rows = (
        await session.execute(
            select(Notification)
            .where(Notification.user_id == current_user.id)
            .order_by(Notification.created_at.desc())
            .limit(30)
        )
    ).scalars().all()

    personal = [
        UnifiedNotif(
            id=n.id,
            source="notification",
            type=n.type,
            title=n.title,
            body=n.body,
            ticket_id=n.ticket_id,
            is_read=n.is_read,
            created_at=n.created_at,
        )
        for n in personal_rows
    ]

    # Active announcements
    ann_rows = (
        await session.execute(
            select(Announcement).where(Announcement.is_active == True).order_by(Announcement.created_at.desc())  # noqa: E712
        )
    ).scalars().all()

    read_ann_ids = set(
        (
            await session.execute(
                select(AnnRead.announcement_id).where(AnnRead.user_id == current_user.id)
            )
        ).scalars().all()
    )

    announcements = [
        UnifiedNotif(
            id=a.id,
            source="announcement",
            type=a.type,
            title=a.title,
            body=a.body,
            ticket_id=None,
            is_read=a.id in read_ann_ids,
            created_at=a.created_at,
        )
        for a in ann_rows
    ]

    # Merge: unread first, then newest
    combined = personal + announcements
    combined.sort(key=lambda n: (n.is_read, -n.created_at.timestamp()))
    return combined[:40]


# ── Mark personal notification read ──────────────────────────────────────────

@router.patch("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    await session.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == current_user.id)
        .values(is_read=True)
    )
    await session.commit()
    return {"ok": True}


# ── Mark announcement read ────────────────────────────────────────────────────

@router.patch("/announcements/{ann_id}/read")
async def mark_announcement_read(
    ann_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    existing = (
        await session.execute(
            select(AnnRead).where(
                AnnRead.announcement_id == ann_id,
                AnnRead.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()

    if not existing:
        session.add(AnnRead(announcement_id=ann_id, user_id=current_user.id))
        await session.commit()
    return {"ok": True}


# ── Mark ALL read (personal + all active announcements) ───────────────────────

@router.patch("/read-all/mark")
async def mark_all_read(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    # Personal
    await session.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read == False)  # noqa: E712
        .values(is_read=True)
    )

    # Announcements: insert read records for all active ones not yet read
    ann_ids = (
        await session.execute(
            select(Announcement.id).where(Announcement.is_active == True)  # noqa: E712
        )
    ).scalars().all()

    already_read = set(
        (
            await session.execute(
                select(AnnRead.announcement_id).where(AnnRead.user_id == current_user.id)
            )
        ).scalars().all()
    )

    for ann_id in ann_ids:
        if ann_id not in already_read:
            session.add(AnnRead(announcement_id=ann_id, user_id=current_user.id))

    await session.commit()
    return {"ok": True}
