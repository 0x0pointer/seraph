from sqlalchemy import Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ConnectionGuardrail(Base):
    __tablename__ = "connection_guardrails"
    __table_args__ = (UniqueConstraint("connection_id", "guardrail_id", name="uq_conn_guardrail"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("api_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    guardrail_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("guardrail_configs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    threshold_override: Mapped[float | None] = mapped_column(Float, nullable=True)
