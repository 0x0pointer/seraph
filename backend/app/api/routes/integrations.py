"""
Gateway integration adapters — LiteLLM custom guardrail hooks.

Provides compatibility endpoints for third-party LLM gateways so they can
call SKF Guard using their native guardrail protocol, without any code
changes on the SKF Guard scanner side.

──────────────────────────────────────────────────────────────────────────────
LiteLLM config (drop-in):

    guardrails:
      - guardrail_name: "skf-guard-input"
        litellm_params:
          guardrail: custom
          mode: "pre_call"
          guardrail_endpoint: "http://skf-guard:8000/api/integrations/litellm/pre_call"

      - guardrail_name: "skf-guard-output"
        litellm_params:
          guardrail: custom
          mode: "post_call"
          guardrail_endpoint: "http://skf-guard:8000/api/integrations/litellm/post_call"

    Authentication: set the SKF Guard connection key in LiteLLM's environment:
      LITELLM_SKF_GUARD_KEY=ts_conn_<your_key>

    Then reference it in the guardrail params:
      default_headers: {"Authorization": "Bearer ${LITELLM_SKF_GUARD_KEY}"}

──────────────────────────────────────────────────────────────────────────────
Response contract (what LiteLLM expects):
  - HTTP 200  → request/response is allowed through
  - HTTP 4xx  → blocked; LiteLLM surfaces the `detail` field as the error
──────────────────────────────────────────────────────────────────────────────
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.api.routes.scan import (
    _enforce_plan_and_count,
    _enforce_spend_limit,
    _get_guardrail_overrides,
    _update_connection_metrics,
)
from app.core.database import get_session
from app.core.plan_limits import get_effective_plan, get_limits
from app.models.user import User
from app.services import audit_service, scanner_engine

router = APIRouter(prefix="/integrations", tags=["integrations"])


# ── Payload schemas ────────────────────────────────────────────────────────────

class LiteLLMMessage(BaseModel):
    role: str
    content: str


class LiteLLMPreCallRequest(BaseModel):
    """Payload LiteLLM sends to a custom guardrail in pre_call mode."""
    messages: list[LiteLLMMessage]
    model: str | None = None
    call_type: str | None = None


class LiteLLMPostCallRequest(BaseModel):
    """Payload LiteLLM sends to a custom guardrail in post_call mode."""
    messages: list[LiteLLMMessage]
    model: str | None = None
    call_type: str | None = None
    response: dict | None = None   # Full LiteLLM ModelResponse object


# ── Private helpers ────────────────────────────────────────────────────────────

def _last_user_message(messages: list[LiteLLMMessage]) -> str:
    """Return the content of the last user-role message, or empty string."""
    for msg in reversed(messages):
        if msg.role == "user":
            return msg.content
    return ""


def _assistant_reply(response: dict | None) -> str:
    """Extract assistant content from a LiteLLM ModelResponse dict."""
    if not response:
        return ""
    try:
        choices = response.get("choices") or []
        if choices:
            return (choices[0].get("message") or {}).get("content") or ""
    except Exception:
        pass
    return ""


async def _run_input(
    request: Request,
    session: AsyncSession,
    current_user: User,
    text: str,
) -> dict:
    """
    Shared logic for scanning a user input through SKF Guard.
    Returns a dict with scan metadata on success; raises HTTP 400 on block.
    """
    ip   = request.client.host if request.client else None
    conn = getattr(request.state, "api_connection", None)
    now  = datetime.now(timezone.utc)

    if conn is not None:
        _enforce_spend_limit(conn)

    effective_plan = await _enforce_plan_and_count(current_user, session, now)
    limits         = get_limits(effective_plan)
    allowed_input  = None if current_user.role == "admin" else limits["input_scanners"]
    allowed_ids, threshold_overrides = await _get_guardrail_overrides(session, conn)

    is_valid, sanitized, results, violations, on_fail_actions, reask_context, fix_applied = (
        await scanner_engine.run_input_scan(
            session, text,
            allowed_types=allowed_input,
            allowed_guardrail_ids=allowed_ids,
            threshold_overrides=threshold_overrides,
        )
    )

    input_tok = len(text) // 4
    audit_input = audit_output = audit_cost = None
    if conn is not None:
        audit_input, audit_output, audit_cost = await _update_connection_metrics(
            session, conn, is_valid, input_tok, 0
        )

    monitored = [k for k, v in on_fail_actions.items() if v == "monitored"]
    log = await audit_service.create_audit_log(
        session,
        direction="input",
        raw_text=text,
        sanitized_text=sanitized,
        is_valid=is_valid,
        scanner_results=results,
        violation_scanners=violations + monitored,
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

    if not is_valid:
        detail = (
            reask_context[0] if reask_context
            else f"Request blocked by guardrail(s): {', '.join(violations)}"
        )
        raise HTTPException(status_code=400, detail=detail)

    return {
        "status": "allowed",
        "sanitized_text": sanitized,
        "fix_applied": fix_applied,
        "monitored_scanners": monitored,
        "audit_log_id": log.id,
    }


async def _run_output(
    request: Request,
    session: AsyncSession,
    current_user: User,
    assistant_text: str,
    prompt_text: str,
) -> dict:
    """
    Shared logic for scanning an LLM output through SKF Guard.
    Returns a dict with scan metadata on success; raises HTTP 400 on block.
    """
    ip   = request.client.host if request.client else None
    conn = getattr(request.state, "api_connection", None)
    now  = datetime.now(timezone.utc)

    if conn is not None:
        _enforce_spend_limit(conn)

    effective_plan = await _enforce_plan_and_count(current_user, session, now)
    limits         = get_limits(effective_plan)
    allowed_output = None if current_user.role == "admin" else limits["output_scanners"]
    allowed_ids, threshold_overrides = await _get_guardrail_overrides(session, conn)

    is_valid, sanitized, results, violations, on_fail_actions, reask_context, fix_applied = (
        await scanner_engine.run_output_scan(
            session, prompt_text, assistant_text,
            allowed_types=allowed_output,
            allowed_guardrail_ids=allowed_ids,
            threshold_overrides=threshold_overrides,
        )
    )

    output_tok = len(assistant_text) // 4
    audit_input = audit_output = audit_cost = None
    if conn is not None:
        audit_input, audit_output, audit_cost = await _update_connection_metrics(
            session, conn, is_valid, 0, output_tok
        )

    monitored = [k for k, v in on_fail_actions.items() if v == "monitored"]
    log = await audit_service.create_audit_log(
        session,
        direction="output",
        raw_text=assistant_text,
        sanitized_text=sanitized,
        is_valid=is_valid,
        scanner_results=results,
        violation_scanners=violations + monitored,
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

    if not is_valid:
        detail = (
            reask_context[0] if reask_context
            else f"Response blocked by guardrail(s): {', '.join(violations)}"
        )
        raise HTTPException(status_code=400, detail=detail)

    return {
        "status": "allowed",
        "sanitized_text": sanitized,
        "fix_applied": fix_applied,
        "monitored_scanners": monitored,
        "audit_log_id": log.id,
    }


# ── LiteLLM endpoints ──────────────────────────────────────────────────────────

@router.post("/litellm/pre_call")
async def litellm_pre_call(
    request: Request,
    data: LiteLLMPreCallRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    LiteLLM custom guardrail — pre_call hook.

    Called by LiteLLM before forwarding the prompt to the LLM.
    Scans the last user message through SKF Guard's input scanners.

    HTTP 200  → allowed (optionally sanitized_text contains the clean version)
    HTTP 400  → blocked (LiteLLM surfaces the detail as the error to the caller)
    """
    text = _last_user_message(data.messages)
    if not text:
        return {"status": "allowed", "detail": "No user message to scan"}

    return await _run_input(request, session, current_user, text)


@router.post("/litellm/post_call")
async def litellm_post_call(
    request: Request,
    data: LiteLLMPostCallRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    LiteLLM custom guardrail — post_call hook.

    Called by LiteLLM after receiving the LLM response, before returning it
    to the caller. Scans the assistant reply through SKF Guard's output scanners.

    HTTP 200  → allowed
    HTTP 400  → blocked (LiteLLM will surface this as an error to the caller)
    """
    assistant_text = _assistant_reply(data.response)
    if not assistant_text:
        return {"status": "allowed", "detail": "No assistant response to scan"}

    prompt_text = _last_user_message(data.messages)
    return await _run_output(request, session, current_user, assistant_text, prompt_text)


@router.post("/litellm/during_call")
async def litellm_during_call(
    request: Request,
    data: LiteLLMPreCallRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    LiteLLM custom guardrail — during_call hook (streaming).

    LiteLLM calls this mid-stream. We treat it identically to pre_call —
    scan the last user message. SKF Guard does not stream scan chunks.
    """
    text = _last_user_message(data.messages)
    if not text:
        return {"status": "allowed", "detail": "No user message to scan"}

    return await _run_input(request, session, current_user, text)
