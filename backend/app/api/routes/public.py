"""
Public (unauthenticated) routes — used by the marketing playground.
Rate limiting is intentionally left to infra (nginx / CDN).
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import uuid

from app.core.database import get_session
from app.models.platform_setting import PlatformSetting
from app.schemas.scan import ScanRequest, ScanResponse, GuardRequest, GuardResponse, DetectorResult
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


@router.post("/guard", response_model=GuardResponse)
async def public_guard(
    request: Request,
    data: GuardRequest,
    session: AsyncSession = Depends(get_session),
):
    ip = request.client.host if request.client else None
    messages_dicts = [{"role": m.role, "content": m.content} for m in data.messages]
    flagged, results, violations = await scanner_engine.run_guard_scan(session, messages_dicts)

    raw_text = "\n".join(f"[{m.role.upper()}]: {m.content}" for m in data.messages)
    log = await audit_service.create_audit_log(
        session,
        direction="input",
        raw_text=raw_text,
        sanitized_text=raw_text,
        is_valid=not flagged,
        scanner_results=results,
        violation_scanners=violations,
        ip_address=ip,
    )

    breakdown = None
    if data.breakdown:
        breakdown = [
            DetectorResult(detector=name, flagged=(name in violations), score=score)
            for name, score in sorted(results.items(), key=lambda x: x[1], reverse=True)
        ]

    return GuardResponse(
        flagged=flagged,
        metadata={"request_uuid": str(uuid.uuid4())},
        breakdown=breakdown,
        scanner_results=results,
        violation_scanners=violations,
        audit_log_id=log.id,
    )
