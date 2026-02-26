from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ApiConnection(Base):
    __tablename__ = "api_connections"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Ownership: team_id > org_id > personal (user_id only, no org/team)
    org_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    team_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_by_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="production")
    api_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # active | blocked

    # Violation-rate alert — block the connection when violation_rate >= alert_threshold (0–100 %)
    alert_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alert_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0–100
    use_custom_guardrails: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Request counters
    total_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_violations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Per-token pricing ($/token, e.g. GPT-4o input = 0.0000025)
    cost_per_input_token: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_per_output_token: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Monthly spend limits
    monthly_alert_spend: Mapped[float | None] = mapped_column(Float, nullable=True)   # soft — amber banner
    max_monthly_spend: Mapped[float | None] = mapped_column(Float, nullable=True)      # hard — HTTP 402 block

    # Monthly spend counters (reset each calendar month)
    month_spend: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    month_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    month_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    month_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
