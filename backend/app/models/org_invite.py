import secrets
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OrgInvite(Base):
    __tablename__ = "org_invites"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    org_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True,
                                       default=lambda: secrets.token_urlsafe(32))
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    invited_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invited_by_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
