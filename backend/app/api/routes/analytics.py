from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core.database import get_session
from app.models.guardrail import GuardrailConfig
from app.models.user import User
from app.services import audit_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
async def get_summary(
    filter_org_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    admin_filter_org_id = filter_org_id if current_user.role == "admin" else None
    summary = await audit_service.get_summary(
        session,
        role=current_user.role,
        user_id=current_user.id,
        org_id=current_user.org_id,
        team_id=current_user.team_id,
        admin_filter_org_id=admin_filter_org_id,
    )

    active_guardrails_result = await session.execute(
        select(func.count(GuardrailConfig.id)).where(GuardrailConfig.is_active == True)  # noqa: E712
    )
    active_guardrails = active_guardrails_result.scalar_one()

    return {**summary, "active_guardrails": active_guardrails}


@router.get("/trends")
async def get_trends(
    days: int = Query(30, ge=1, le=90),
    filter_org_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    admin_filter_org_id = filter_org_id if current_user.role == "admin" else None
    return await audit_service.get_trends(
        session,
        days=days,
        role=current_user.role,
        user_id=current_user.id,
        org_id=current_user.org_id,
        team_id=current_user.team_id,
        admin_filter_org_id=admin_filter_org_id,
    )


@router.get("/top-violations")
async def get_top_violations(
    limit: int = Query(10, ge=1, le=50),
    filter_org_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    admin_filter_org_id = filter_org_id if current_user.role == "admin" else None
    return await audit_service.get_top_violations(
        session,
        limit=limit,
        role=current_user.role,
        user_id=current_user.id,
        org_id=current_user.org_id,
        team_id=current_user.team_id,
        admin_filter_org_id=admin_filter_org_id,
    )


@router.get("/hourly")
async def get_hourly(
    filter_org_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    admin_filter_org_id = filter_org_id if current_user.role == "admin" else None
    return await audit_service.get_hourly(
        session,
        role=current_user.role,
        user_id=current_user.id,
        org_id=current_user.org_id,
        team_id=current_user.team_id,
        admin_filter_org_id=admin_filter_org_id,
    )
