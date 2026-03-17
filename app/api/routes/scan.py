import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.auth import verify_api_key
from app.schemas.scan import ScanRequest, ScanResponse, GuardRequest, GuardResponse, DetectorResult
from app.services import scanner_engine
from app.services import audit_logger

router = APIRouter(prefix="/scan", tags=["scan"])

ApiKey = Annotated[str | None, Depends(verify_api_key)]


@router.post("/prompt", response_model=ScanResponse)
async def scan_prompt(
    request: Request,
    data: ScanRequest,
    _api_key: ApiKey,
):
    ip = request.client.host if request.client else None

    is_valid, sanitized, results, violations, on_fail_actions, reask_context, fix_applied = (
        await scanner_engine.run_input_scan(data.text)
    )

    monitored = [k for k, v in on_fail_actions.items() if v == "monitored"]
    all_violations_for_audit = violations + monitored

    await audit_logger.log_scan(
        direction="input",
        is_valid=is_valid,
        scanner_results=results,
        violations=all_violations_for_audit,
        on_fail_actions=on_fail_actions,
        text_length=len(data.text),
        fix_applied=fix_applied,
        ip_address=ip,
    )

    return ScanResponse(
        is_valid=is_valid,
        sanitized_text=sanitized,
        scanner_results=results,
        violation_scanners=violations,
        on_fail_actions=on_fail_actions,
        monitored_scanners=monitored,
        reask_context=reask_context,
        fix_applied=fix_applied,
    )


@router.post("/output", response_model=ScanResponse)
async def scan_output(
    request: Request,
    data: ScanRequest,
    _api_key: ApiKey,
):
    ip = request.client.host if request.client else None
    prompt = data.prompt or ""

    is_valid, sanitized, results, violations, on_fail_actions, reask_context, fix_applied = (
        await scanner_engine.run_output_scan(prompt, data.text)
    )

    monitored = [k for k, v in on_fail_actions.items() if v == "monitored"]
    all_violations_for_audit = violations + monitored

    await audit_logger.log_scan(
        direction="output",
        is_valid=is_valid,
        scanner_results=results,
        violations=all_violations_for_audit,
        on_fail_actions=on_fail_actions,
        text_length=len(data.text),
        fix_applied=fix_applied,
        ip_address=ip,
    )

    return ScanResponse(
        is_valid=is_valid,
        sanitized_text=sanitized,
        scanner_results=results,
        violation_scanners=violations,
        on_fail_actions=on_fail_actions,
        monitored_scanners=monitored,
        reask_context=reask_context,
        fix_applied=fix_applied,
    )


@router.post("/guard", response_model=GuardResponse)
async def scan_guard(
    request: Request,
    data: GuardRequest,
    _api_key: ApiKey,
):
    ip = request.client.host if request.client else None

    messages_dicts = [{"role": m.role, "content": m.content} for m in data.messages]
    flagged, results, violations = await scanner_engine.run_guard_scan(messages_dicts)

    total_chars = sum(len(m.content) for m in data.messages)

    await audit_logger.log_scan(
        direction="input",
        is_valid=not flagged,
        scanner_results=results,
        violations=violations,
        text_length=total_chars,
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
    )
