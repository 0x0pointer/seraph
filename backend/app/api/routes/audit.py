from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core.database import get_session
from app.core.plan_limits import get_effective_plan, get_limits
from app.models.user import User
from app.schemas.audit import AuditLogList
from app.services import audit_service

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditLogList)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    direction: str | None = Query(None),
    is_valid: bool | None = Query(None),
    connection_id: int | None = Query(None),
    filter_org_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    admin_filter_org_id = filter_org_id if current_user.role == "admin" else None
    if current_user.role == "admin":
        max_age_days = None
    else:
        effective_plan = await get_effective_plan(current_user, session)
        max_age_days = get_limits(effective_plan)["audit_days"]
    items, total = await audit_service.list_audit_logs(
        session,
        page=page,
        page_size=page_size,
        direction=direction,
        is_valid=is_valid,
        connection_id=connection_id,
        max_age_days=max_age_days,
        role=current_user.role,
        user_id=current_user.id,
        org_id=current_user.org_id,
        team_id=current_user.team_id,
        admin_filter_org_id=admin_filter_org_id,
    )
    return AuditLogList(items=items, total=total, page=page, page_size=page_size)


@router.get("/abuse", response_model=AuditLogList)
async def list_abuse_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    connection_id: int | None = Query(None),
    filter_org_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    admin_filter_org_id = filter_org_id if current_user.role == "admin" else None
    if current_user.role == "admin":
        max_age_days = None
    else:
        effective_plan = await get_effective_plan(current_user, session)
        max_age_days = get_limits(effective_plan)["audit_days"]
    items, total = await audit_service.list_audit_logs(
        session,
        page=page,
        page_size=page_size,
        violations_only=True,
        connection_id=connection_id,
        max_age_days=max_age_days,
        role=current_user.role,
        user_id=current_user.id,
        org_id=current_user.org_id,
        team_id=current_user.team_id,
        admin_filter_org_id=admin_filter_org_id,
    )
    return AuditLogList(items=items, total=total, page=page, page_size=page_size)
