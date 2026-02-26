from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core.database import get_session
from app.models.user import User
from app.schemas.guardrail import GuardrailCreate, GuardrailRead, GuardrailUpdate
from app.services import guardrail_service
from app.services.event_service import log_event
from app.services.scanner_engine import invalidate_cache

router = APIRouter(prefix="/guardrails", tags=["guardrails"])


@router.get("", response_model=list[GuardrailRead])
async def list_guardrails(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    return await guardrail_service.list_guardrails(session)


@router.post("", response_model=GuardrailRead, status_code=status.HTTP_201_CREATED)
async def create_guardrail(
    data: GuardrailCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    guardrail = await guardrail_service.create_guardrail(session, data)
    await log_event(session, event_type="guardrail.created",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="guardrail", target_id=guardrail.id, target_name=guardrail.name,
        details={"scanner_type": guardrail.scanner_type, "direction": guardrail.direction})
    await session.commit()
    invalidate_cache()
    return guardrail


@router.put("/{guardrail_id}", response_model=GuardrailRead)
async def update_guardrail(
    guardrail_id: int,
    data: GuardrailUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    guardrail = await guardrail_service.update_guardrail(session, guardrail_id, data)
    if not guardrail:
        raise HTTPException(status_code=404, detail="Guardrail not found")
    await log_event(session, event_type="guardrail.updated",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="guardrail", target_id=guardrail.id, target_name=guardrail.name,
        details={"scanner_type": guardrail.scanner_type, "direction": guardrail.direction,
                 "is_active": guardrail.is_active})
    await session.commit()
    invalidate_cache()
    return guardrail


@router.delete("/{guardrail_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_guardrail(
    guardrail_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    # Fetch name before deleting
    from sqlalchemy import select
    from app.models.guardrail import GuardrailConfig
    g = (await session.execute(select(GuardrailConfig).where(GuardrailConfig.id == guardrail_id))).scalar_one_or_none()
    deleted = await guardrail_service.delete_guardrail(session, guardrail_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Guardrail not found")
    if g:
        await log_event(session, event_type="guardrail.deleted",
            actor_id=current_user.id, actor_username=current_user.username,
            target_type="guardrail", target_id=guardrail_id, target_name=g.name,
            details={"scanner_type": g.scanner_type, "direction": g.direction})
        await session.commit()
    invalidate_cache()


@router.patch("/{guardrail_id}/toggle", response_model=GuardrailRead)
async def toggle_guardrail(
    guardrail_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    guardrail = await guardrail_service.toggle_guardrail(session, guardrail_id)
    if not guardrail:
        raise HTTPException(status_code=404, detail="Guardrail not found")
    await log_event(session, event_type="guardrail.toggled",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="guardrail", target_id=guardrail.id, target_name=guardrail.name,
        details={"is_active": guardrail.is_active, "scanner_type": guardrail.scanner_type,
                 "direction": guardrail.direction})
    await session.commit()
    invalidate_cache()
    return guardrail
