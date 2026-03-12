from datetime import datetime, timezone
from sqlalchemy import String, Boolean, JSON, DateTime, Text, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # input | output
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    sanitized_text: Mapped[str] = mapped_column(Text, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    scanner_results: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    violation_scanners: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Who triggered this scan (used for per-user / per-team / per-org scoping)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    org_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    team_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Which API connection triggered this scan (nullable = personal token / JWT)
    connection_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    connection_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    connection_environment: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Token cost tracking (populated when connection has pricing configured)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Guardrails AI-inspired action metadata
    # on_fail_actions: {"ScannerName": "blocked"|"fixed"|"monitored"|"reask"}
    on_fail_actions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # fix_applied: True when at least one scanner sanitized the text instead of blocking
    fix_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")
    # reask_context: list of correction instructions returned when a reask-action scanner fires
    reask_context: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
