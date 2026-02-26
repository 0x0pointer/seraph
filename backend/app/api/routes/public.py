"""
Public (unauthenticated) routes — used by the marketing playground.
Rate limiting is intentionally left to infra (nginx / CDN).
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.platform_setting import PlatformSetting
from app.schemas.scan import ScanRequest, ScanResponse
from app.services import audit_service, scanner_engine

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/platform-info")
async def platform_info(session: AsyncSession = Depends(get_session)):
    """Return public platform metadata (e.g., company name, chatbot status)."""
    result = await session.execute(
        select(PlatformSetting).where(PlatformSetting.key.in_(["company_name", "chatbot_enabled"]))
    )
    rows = {row.key: row.value for row in result.scalars().all()}
    return {
        "company_name": rows.get("company_name", ""),
        "chatbot_enabled": rows.get("chatbot_enabled", "true") != "false",
    }


@router.post("/scan", response_model=ScanResponse)
async def public_scan(
    request: Request,
    data: ScanRequest,
    session: AsyncSession = Depends(get_session),
):
    """Run an input scan without requiring authentication (marketing demo)."""
    ip = request.client.host if request.client else None
    is_valid, sanitized, results, violations = await scanner_engine.run_input_scan(
        session, data.text
    )
    log = await audit_service.create_audit_log(
        session,
        direction="input",
        raw_text=data.text,
        sanitized_text=sanitized,
        is_valid=is_valid,
        scanner_results=results,
        violation_scanners=violations,
        ip_address=ip,
    )
    return ScanResponse(
        is_valid=is_valid,
        sanitized_text=sanitized,
        scanner_results=results,
        violation_scanners=violations,
        audit_log_id=log.id,
    )
