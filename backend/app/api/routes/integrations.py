"""
Gateway integration adapters.

Three integration patterns, from simplest to most powerful:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. UNIVERSAL HOOK  —  POST /api/integrations/hook
   Works with ANY gateway that can make an HTTP callback (Nginx, Traefik,
   Envoy, AWS API GW, Apigee, Tyk, custom middleware).

   Request:
     Authorization: Bearer ts_conn_<key>
     {"text": "...", "direction": "input|output", "prompt": "..."}

   Response:
     200  → {"status": "allowed", "sanitized_text": "..."}
     400  → {"error": "guardrail_violation", "detail": "..."}   ← block

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. TRANSPARENT PROXY  —  POST /api/integrations/proxy
   OpenAI-compatible reverse proxy. Zero client-side changes — just point
   your base_url at Seraph. Seraph scans both directions and forwards
   to the real LLM upstream.

   Extra headers:
     X-Upstream-URL:  https://api.openai.com    (where to forward)
     X-Upstream-Auth: Bearer sk-...             (upstream credentials)

   Works with:  OpenAI SDK, LangChain, anything using an OpenAI-compat API.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. LITELLM CUSTOM GUARDRAIL  —  pre_call / post_call / during_call
   LiteLLM-native hook endpoints (see bottom of this file).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Gateway config examples live in: gateway-examples/
  nginx.conf     traefik.yml     envoy.yaml     aws-lambda.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from typing import Any
import logging

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.api.routes.scan import (
    _enforce_spend_limit,
    _get_guardrail_overrides,
    _update_connection_metrics,
)
from app.core.database import get_session
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
    Shared logic for scanning a user input through Seraph.
    Returns a dict with scan metadata on success; raises HTTP 400 on block.
    """
    ip   = request.client.host if request.client else None
    conn = getattr(request.state, "api_connection", None)

    if conn is not None:
        _enforce_spend_limit(conn)

    allowed_ids, threshold_overrides = await _get_guardrail_overrides(session, conn)

    is_valid, sanitized, results, violations, on_fail_actions, reask_context, fix_applied = (
        await scanner_engine.run_input_scan(
            session, text,
            allowed_types=None,
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
    Shared logic for scanning an LLM output through Seraph.
    Returns a dict with scan metadata on success; raises HTTP 400 on block.
    """
    ip   = request.client.host if request.client else None
    conn = getattr(request.state, "api_connection", None)

    if conn is not None:
        _enforce_spend_limit(conn)

    allowed_ids, threshold_overrides = await _get_guardrail_overrides(session, conn)

    is_valid, sanitized, results, violations, on_fail_actions, reask_context, fix_applied = (
        await scanner_engine.run_output_scan(
            session, prompt_text, assistant_text,
            allowed_types=None,
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
    Scans the last user message through Seraph's input scanners.

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
    to the caller. Scans the assistant reply through Seraph's output scanners.

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
    scan the last user message. Seraph does not stream scan chunks.
    """
    text = _last_user_message(data.messages)
    if not text:
        return {"status": "allowed", "detail": "No user message to scan"}

    return await _run_input(request, session, current_user, text)


# ── Universal Hook ─────────────────────────────────────────────────────────────

class HookRequest(BaseModel):
    text: str
    direction: str = "input"   # "input" | "output"
    prompt: str | None = None  # original user prompt (required for output scans)


@router.post("/hook")
async def universal_hook(
    request: Request,
    data: HookRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Universal guardrail hook — works with ANY gateway.

    The simplest possible integration: one endpoint, minimal payload.
    Call it from Nginx (auth_request), Traefik (forwardAuth), Envoy
    (ext_authz), AWS API Gateway (Lambda authorizer), Apigee, Tyk,
    custom middleware — anything that can make an HTTP POST.

    Request body:
        {"text": "...", "direction": "input|output", "prompt": "..."}

    Response:
        200  {"status": "allowed", "sanitized_text": "..."}
        400  {"error": "guardrail_violation", "detail": "..."}   <- gateway should block

    See gateway-examples/ for ready-to-use configs for Nginx, Traefik, Envoy.
    """
    if data.direction == "output":
        if not data.text:
            return {"status": "allowed", "detail": "No output text to scan"}
        return await _run_output(request, session, current_user, data.text, data.prompt or "")

    # Default: input scan
    if not data.text:
        return {"status": "allowed", "detail": "No input text to scan"}
    return await _run_input(request, session, current_user, data.text)


# ── Transparent Proxy ──────────────────────────────────────────────────────────

_PROXY_CLIENT = httpx.AsyncClient(timeout=120.0)

# Headers we strip before forwarding to upstream
_HOP_HEADERS = {
    "host", "content-length", "transfer-encoding", "connection",
    "x-upstream-url", "x-upstream-auth",
    "authorization",  # replaced with X-Upstream-Auth value
}


@router.post("/proxy")
@router.post("/proxy/{path:path}")
async def transparent_proxy(
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    x_upstream_url: str | None = Header(default=None, alias="X-Upstream-URL"),
    x_upstream_auth: str | None = Header(default=None, alias="X-Upstream-Auth"),
    path: str = "",
):
    """
    Transparent OpenAI-compatible reverse proxy.

    Zero client-side changes — just change your base_url:

        # Before
        client = OpenAI(base_url="https://api.openai.com/v1")

        # After — Seraph scans every request/response transparently
        client = OpenAI(
            base_url="http://seraph:8000/api/integrations/proxy/v1",
            default_headers={
                "Authorization":  "Bearer ts_conn_<key>",
                "X-Upstream-URL": "https://api.openai.com",
                "X-Upstream-Auth": "Bearer sk-...",
            }
        )

    Flow:
        1. Scan input  → block/fix if needed
        2. Forward to upstream LLM
        3. Scan output → block/fix if needed
        4. Return response (identical shape to upstream)
    """
    if not x_upstream_url:
        raise HTTPException(
            status_code=400,
            detail=(
                "X-Upstream-URL header is required. "
                "Set it to your LLM provider base URL, e.g. https://api.openai.com"
            ),
        )

    # ── Parse request body ────────────────────────────────────────────────────
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    messages: list[dict] = body.get("messages") or []

    # ── Step 1: Input scan ────────────────────────────────────────────────────
    # Build lightweight message objects for the existing helper
    class _Msg:
        def __init__(self, role: str, content: str):
            self.role = role
            self.content = content

    user_text = _last_user_message([_Msg(m.get("role", ""), m.get("content", "")) for m in messages])

    if user_text:
        scan_result = await _run_input(request, session, current_user, user_text)
        # Replace message with sanitized text if a fix was applied
        if scan_result.get("fix_applied") and scan_result.get("sanitized_text") != user_text:
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    messages[i] = {**messages[i], "content": scan_result["sanitized_text"]}
                    break
            body = {**body, "messages": messages}

    # ── Step 2: Forward to upstream ───────────────────────────────────────────
    upstream_path = path.lstrip("/")
    forward_url   = f"{x_upstream_url.rstrip('/')}/{upstream_path}" if upstream_path else x_upstream_url.rstrip("/")

    forward_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_HEADERS
    }
    if x_upstream_auth:
        forward_headers["Authorization"] = x_upstream_auth

    try:
        upstream_resp = await _PROXY_CLIENT.post(forward_url, json=body, headers=forward_headers)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream LLM unreachable: {exc}")

    if upstream_resp.status_code != 200:
        try:
            err_body = upstream_resp.json()
        except Exception:
            err_body = {"error": upstream_resp.text}
        return JSONResponse(content=err_body, status_code=upstream_resp.status_code)

    # ── Step 3: Output scan ───────────────────────────────────────────────────
    try:
        upstream_body: dict[str, Any] = upstream_resp.json()
    except Exception:
        return JSONResponse(content={"error": "Non-JSON upstream response"}, status_code=502)

    choices = upstream_body.get("choices") or []
    assistant_text = ""
    if choices:
        assistant_text = (choices[0].get("message") or {}).get("content") or ""

    if assistant_text:
        out_result = await _run_output(request, session, current_user, assistant_text, user_text)
        # Replace with sanitized content if a fix was applied
        if out_result.get("fix_applied") and out_result.get("sanitized_text") != assistant_text:
            upstream_body["choices"][0]["message"]["content"] = out_result["sanitized_text"]

    return JSONResponse(content=upstream_body, status_code=200)
