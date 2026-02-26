from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_event import SystemEvent


async def log_event(
    session: AsyncSession,
    *,
    event_type: str,
    actor_id: int | None = None,
    actor_username: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    target_name: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Append a system event to the current session. Caller is responsible for commit."""
    session.add(SystemEvent(
        event_type=event_type,
        actor_id=actor_id,
        actor_username=actor_username,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        details=details or {},
        ip_address=ip_address,
    ))
