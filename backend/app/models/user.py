from datetime import datetime, timezone
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    api_token: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True, index=True)
    # role: "admin" = superadmin, "org_admin" = org-level admin, "viewer" = regular member
    role: Mapped[str] = mapped_column(String(20), default="viewer", nullable=False)
    org_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    team_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    reset_token: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True, index=True)
    reset_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Plan & usage
    plan: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    month_scan_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    month_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Stripe billing
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subscription_status: Mapped[str] = mapped_column(String(20), nullable=False, default="inactive")
