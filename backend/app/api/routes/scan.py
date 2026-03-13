import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core.database import get_session
from app.models.user import User
from app.schemas.scan import ScanRequest, ScanResponse, GuardRequest, GuardResponse, DetectorResult
from app.models.connection_guardrail import ConnectionGuardrail
from app.services import audit_service, scanner_engine

router = APIRouter(prefix="/scan", tags=["scan"])


from fastapi import HTTPException


def _is_same_month(dt: datetime | None, now: datetime) -> bool:
    return dt is not None and dt.year == now.year and dt.month == now.month


def _enforce_spend_limit(conn) -> None:
    """Raise HTTP 402 if the connection's hard monthly spend cap has been reached."""
    if conn.max_monthly_spend is None:
        return
    now = datetime.now(timezone.utc)
    if _is_same_month(conn.month_started_at, now) and conn.month_spend >= conn.max_monthly_spend:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Connection '{conn.name}' has reached its monthly spend limit of "
                f"${conn.max_monthly_spend:.2f} "
                f"(current: ${conn.month_spend:.4f}). "
                "Reset the monthly counter or increase the limit to continue."
            ),
        )


async def _update_connection_metrics(
    session: AsyncSession,
    conn,
    is_valid: bool,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> tuple[int | None, int | None, float | None]:
    """
    Increment request/violation counters and (if pricing configured) spend counters.
    Returns (input_tokens, output_tokens, token_cost) for the audit log.
    """
    conn.total_requests += 1
    if not is_valid:
        conn.total_violations += 1
    now = datetime.now(timezone.utc)
    conn.last_active_at = now

    if conn.alert_enabled and conn.alert_threshold is not None and conn.total_requests > 0:
        rate = (conn.total_violations / conn.total_requests) * 100
        if rate >= conn.alert_threshold:
            conn.status = "blocked"

    # Spend tracking
    audit_input = audit_output = audit_cost = None
    has_pricing = (conn.cost_per_input_token or 0) > 0 or (conn.cost_per_output_token or 0) > 0
    if has_pricing and input_tokens is not None:
        out_tok = output_tokens or 0
        # Monthly reset
        if not _is_same_month(conn.month_started_at, now):
            conn.month_input_tokens = 0
            conn.month_output_tokens = 0
            conn.month_spend = 0.0
            conn.month_started_at = now

        cost = input_tokens * (conn.cost_per_input_token or 0) + out_tok * (conn.cost_per_output_token or 0)
        conn.month_input_tokens = (conn.month_input_tokens or 0) + input_tokens
        conn.month_output_tokens = (conn.month_output_tokens or 0) + out_tok
        conn.month_spend = (conn.month_spend or 0.0) + cost
        audit_input, audit_output, audit_cost = input_tokens, out_tok, cost

    session.add(conn)
    await session.commit()
    return audit_input, audit_output, audit_cost


async def _get_guardrail_overrides(
    session: AsyncSession, conn
) -> tuple[set[int] | None, dict[int, float]]:
    """Return (allowed_guardrail_ids, threshold_overrides) for the connection."""
    if conn is None or not conn.use_custom_guardrails:
        return None, {}
    from sqlalchemy import select as _select
    rows = (
        await session.execute(
            _select(ConnectionGuardrail).where(ConnectionGuardrail.connection_id == conn.id)
        )
    ).scalars().all()
    ids = {r.guardrail_id for r in rows}
    overrides = {r.guardrail_id: r.threshold_override for r in rows if r.threshold_override is not None}
    return ids, overrides


@router.post("/prompt", response_model=ScanResponse)
async def scan_prompt(
    request: Request,
    data: ScanRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ip = request.client.host if request.client else None
    conn = getattr(request.state, "api_connection", None)

    if conn is not None:
        _enforce_spend_limit(conn)

    allowed_ids, threshold_overrides = await _get_guardrail_overrides(session, conn)

    is_valid, sanitized, results, violations, on_fail_actions, reask_context, fix_applied = (
        await scanner_engine.run_input_scan(
            session, data.text,
            allowed_guardrail_ids=allowed_ids, threshold_overrides=threshold_overrides,
        )
    )

    # Resolve token counts for cost tracking
    input_tok = data.input_tokens if data.input_tokens is not None else len(data.text) // 4
    output_tok = data.output_tokens if data.output_tokens is not None else 0

    audit_input = audit_output = audit_cost = None
    if conn is not None:
        audit_input, audit_output, audit_cost = await _update_connection_metrics(
            session, conn, is_valid, input_tok, output_tok
        )

    # Include monitored (non-blocking) violations in the audit trail
    monitored = [k for k, v in on_fail_actions.items() if v == "monitored"]
    all_violations_for_audit = violations + monitored

    log = await audit_service.create_audit_log(
        session,
        direction="input",
        raw_text=data.text,
        sanitized_text=sanitized,
        is_valid=is_valid,
        scanner_results=results,
        violation_scanners=all_violations_for_audit,
        ip_address=ip,
        user_id=current_user.id,
        org_id=current_user.org_id,
        team_id=current_user.team_id,
        connection_id=conn.id if conn else None,
        connection_name=conn.name if conn else None,
        connection_environment=conn.environment if conn else None,
        input_tokens=audit_input,
        output_tokens=audit_output,
        token_cost=audit_cost,
        on_fail_actions=on_fail_actions,
        fix_applied=fix_applied,
        reask_context=reask_context,
    )

    return ScanResponse(
        is_valid=is_valid,
        sanitized_text=sanitized,
        scanner_results=results,
        violation_scanners=violations,
        audit_log_id=log.id,
        on_fail_actions=on_fail_actions,
        monitored_scanners=monitored,
        reask_context=reask_context,
        fix_applied=fix_applied,
    )


@router.post("/output", response_model=ScanResponse)
async def scan_output(
    request: Request,
    data: ScanRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ip = request.client.host if request.client else None
    conn = getattr(request.state, "api_connection", None)
    prompt = data.prompt or ""

    if conn is not None:
        _enforce_spend_limit(conn)

    allowed_ids, threshold_overrides = await _get_guardrail_overrides(session, conn)

    is_valid, sanitized, results, violations, on_fail_actions, reask_context, fix_applied = (
        await scanner_engine.run_output_scan(
            session, prompt, data.text,
            allowed_guardrail_ids=allowed_ids, threshold_overrides=threshold_overrides,
        )
    )

    # Resolve token counts for cost tracking
    input_tok = data.input_tokens if data.input_tokens is not None else len(data.text) // 4
    output_tok = data.output_tokens if data.output_tokens is not None else 0

    audit_input = audit_output = audit_cost = None
    if conn is not None:
        audit_input, audit_output, audit_cost = await _update_connection_metrics(
            session, conn, is_valid, input_tok, output_tok
        )

    monitored = [k for k, v in on_fail_actions.items() if v == "monitored"]
    all_violations_for_audit = violations + monitored

    log = await audit_service.create_audit_log(
        session,
        direction="output",
        raw_text=data.text,
        sanitized_text=sanitized,
        is_valid=is_valid,
        scanner_results=results,
        violation_scanners=all_violations_for_audit,
        ip_address=ip,
        user_id=current_user.id,
        org_id=current_user.org_id,
        team_id=current_user.team_id,
        connection_id=conn.id if conn else None,
        connection_name=conn.name if conn else None,
        connection_environment=conn.environment if conn else None,
        input_tokens=audit_input,
        output_tokens=audit_output,
        token_cost=audit_cost,
        on_fail_actions=on_fail_actions,
        fix_applied=fix_applied,
        reask_context=reask_context,
    )

    return ScanResponse(
        is_valid=is_valid,
        sanitized_text=sanitized,
        scanner_results=results,
        violation_scanners=violations,
        audit_log_id=log.id,
        on_fail_actions=on_fail_actions,
        monitored_scanners=monitored,
        reask_context=reask_context,
        fix_applied=fix_applied,
    )


@router.post("/guard", response_model=GuardResponse)
async def scan_guard(
    request: Request,
    data: GuardRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ip   = request.client.host if request.client else None
    conn = getattr(request.state, "api_connection", None)

    if conn is not None:
        _enforce_spend_limit(conn)

    allowed_ids, threshold_overrides = await _get_guardrail_overrides(session, conn)

    messages_dicts = [{"role": m.role, "content": m.content} for m in data.messages]
    flagged, results, violations = await scanner_engine.run_guard_scan(
        session, messages_dicts,
        allowed_guardrail_ids=allowed_ids,
        threshold_overrides=threshold_overrides,
    )

    total_chars = sum(len(m.content) for m in data.messages)
    input_tok = total_chars // 4
    audit_input = audit_output = audit_cost = None
    if conn is not None:
        audit_input, audit_output, audit_cost = await _update_connection_metrics(
            session, conn, not flagged, input_tok, 0
        )

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
        user_id=current_user.id,
        org_id=current_user.org_id,
        team_id=current_user.team_id,
        connection_id=conn.id if conn else None,
        connection_name=conn.name if conn else None,
        connection_environment=conn.environment if conn else None,
        input_tokens=audit_input,
        output_tokens=audit_output,
        token_cost=audit_cost,
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
