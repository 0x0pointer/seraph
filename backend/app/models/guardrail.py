from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Integer, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GuardrailConfig(Base):
    __tablename__ = "guardrail_configs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    scanner_type: Mapped[str] = mapped_column(String(100), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # input | output
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # on_fail_action: what to do when this scanner detects a violation.
    # block   — reject the request (default, original behaviour)
    # fix     — use the scanner's sanitized/redacted output instead of blocking
    # monitor — log the violation but let the request through
    # reask   — reject and return structured correction context for LLM retries
    on_fail_action: Mapped[str] = mapped_column(String(20), default="block", nullable=False, server_default="block")
    params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
