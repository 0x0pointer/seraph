from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.api.routes.admin import require_admin
from app.core.database import get_session
from app.models.announcement import Announcement
from app.models.user import User

router = APIRouter(prefix="/announcements", tags=["announcements"])

VALID_TYPES = {"announcement", "news"}


class AnnouncementCreate(BaseModel):
    title: str
    body: str | None = None
    type: str = "announcement"


class AnnouncementUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    type: str | None = None


class AnnouncementRead(BaseModel):
    id: int
    title: str
    body: str | None
    type: str
    created_by_id: int
    created_by_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[AnnouncementRead])
async def list_announcements(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    rows = (
        await session.execute(
            select(Announcement).order_by(Announcement.created_at.desc())
        )
    ).scalars().all()
    return [AnnouncementRead.model_validate(r) for r in rows]


@router.post("", response_model=AnnouncementRead, status_code=201)
async def create_announcement(
    data: AnnouncementCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    if not data.title.strip():
        raise HTTPException(status_code=422, detail="Title is required")
    if data.type not in VALID_TYPES:
        raise HTTPException(status_code=422, detail="Type must be 'announcement' or 'news'")

    ann = Announcement(
        title=data.title.strip(),
        body=data.body.strip() if data.body else None,
        type=data.type,
        created_by_id=current_user.id,
        created_by_name=current_user.full_name or current_user.username,
        is_active=True,
    )
    session.add(ann)
    await session.commit()
    await session.refresh(ann)
    return AnnouncementRead.model_validate(ann)


@router.put("/{ann_id}", response_model=AnnouncementRead)
async def update_announcement(
    ann_id: int,
    data: AnnouncementUpdate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    ann = (
        await session.execute(select(Announcement).where(Announcement.id == ann_id))
    ).scalar_one_or_none()
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found")

    if data.title is not None:
        ann.title = data.title.strip()
    if data.body is not None:
        ann.body = data.body.strip() or None
    if data.type is not None:
        if data.type not in VALID_TYPES:
            raise HTTPException(status_code=422, detail="Invalid type")
        ann.type = data.type
    ann.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(ann)
    return AnnouncementRead.model_validate(ann)


@router.patch("/{ann_id}/toggle", response_model=AnnouncementRead)
async def toggle_announcement(
    ann_id: int,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    ann = (
        await session.execute(select(Announcement).where(Announcement.id == ann_id))
    ).scalar_one_or_none()
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found")

    ann.is_active = not ann.is_active
    ann.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(ann)
    return AnnouncementRead.model_validate(ann)


@router.delete("/{ann_id}", status_code=204)
async def delete_announcement(
    ann_id: int,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    ann = (
        await session.execute(select(Announcement).where(Announcement.id == ann_id))
    ).scalar_one_or_none()
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found")
    await session.delete(ann)
    await session.commit()
