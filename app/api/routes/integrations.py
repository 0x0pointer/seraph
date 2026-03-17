"""
Gateway integration adapters.

Three integration patterns, from simplest to most powerful:

1. UNIVERSAL HOOK  —  POST /hook
2. TRANSPARENT PROXY  —  POST /proxy
3. LITELLM CUSTOM GUARDRAIL  —  pre_call / post_call / during_call
"""

from typing import Annotated, Any
import logging

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.auth import verify_api_key
from app.core.config import get_config
from app.services import scanner_engine
from app.services import audit_logger

ApiKey = Annotated[str | None, Depends(verify_api_key)]

router = APIRouter(prefix="/integrations", tags=["integrations"])


# ── Payload schemas ────────────────────────────────────────────────────────────

class LiteLLMMessage(BaseModel):
    role: str
    content: str


class LiteLLMPreCallRequest(BaseModel):
    messages: list[LiteLLMMessage]
    model: str | None = None
    call_type: str | None = None


class LiteLLMPostCallRequest(BaseModel):
    messages: list[LiteLLMMessage]
    model: str | None = None
    call_type: str | None = None
    response: dict | None = None


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
    text: str,
) -> dict:
    """Shared logic for scanning a user input through Seraph."""
    ip = request.client.host if request.client else None

    is_valid, sanitized, results, violations, on_fail_actions, reask_context, fix_applied = (
        await scanner_engine.run_input_scan(text)
    )

    monitored = [k for k, v in on_fail_actions.items() if v == "monitored"]

    await audit_logger.log_scan(
        direction="input",
        is_valid=is_valid,
        scanner_results=results,
        violations=violations + monitored,
        on_fail_actions=on_fail_actions,
        text_length=len(text),
        fix_applied=fix_applied,
        ip_address=ip,
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
    }


async def _run_output(
    request: Request,
    assistant_text: str,
    prompt_text: str,
) -> dict:
    """Shared logic for scanning an LLM output through Seraph."""
    ip = request.client.host if request.client else None

    is_valid, sanitized, results, violations, on_fail_actions, reask_context, fix_applied = (
        await scanner_engine.run_output_scan(prompt_text, assistant_text)
    )

    monitored = [k for k, v in on_fail_actions.items() if v == "monitored"]

    await audit_logger.log_scan(
        direction="output",
        is_valid=is_valid,
        scanner_results=results,
        violations=violations + monitored,
        on_fail_actions=on_fail_actions,
        text_length=len(assistant_text),
        fix_applied=fix_applied,
        ip_address=ip,
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
    }


# ── LiteLLM endpoints ──────────────────────────────────────────────────────────

@router.post("/litellm/pre_call")
async def litellm_pre_call(
    request: Request,
    data: LiteLLMPreCallRequest,
    _api_key: ApiKey,
):
    text = _last_user_message(data.messages)
    if not text:
        return {"status": "allowed", "detail": "No user message to scan"}
    return await _run_input(request, text)


@router.post("/litellm/post_call")
async def litellm_post_call(
    request: Request,
    data: LiteLLMPostCallRequest,
    _api_key: ApiKey,
):
    assistant_text = _assistant_reply(data.response)
    if not assistant_text:
        return {"status": "allowed", "detail": "No assistant response to scan"}
    prompt_text = _last_user_message(data.messages)
    return await _run_output(request, assistant_text, prompt_text)


@router.post("/litellm/during_call")
async def litellm_during_call(
    request: Request,
    data: LiteLLMPreCallRequest,
    _api_key: ApiKey,
):
    text = _last_user_message(data.messages)
    if not text:
        return {"status": "allowed", "detail": "No user message to scan"}
    return await _run_input(request, text)


# ── Universal Hook ─────────────────────────────────────────────────────────────

class HookRequest(BaseModel):
    text: str
    direction: str = "input"
    prompt: str | None = None


@router.post("/hook")
async def universal_hook(
    request: Request,
    data: HookRequest,
    _api_key: ApiKey,
):
    """
    Universal guardrail hook — works with ANY gateway.
    """
    if data.direction == "output":
        if not data.text:
            return {"status": "allowed", "detail": "No output text to scan"}
        return await _run_output(request, data.text, data.prompt or "")

    if not data.text:
        return {"status": "allowed", "detail": "No input text to scan"}
    return await _run_input(request, data.text)


# ── Transparent Proxy ──────────────────────────────────────────────────────────

_PROXY_CLIENT = httpx.AsyncClient(timeout=120.0)

_HOP_HEADERS = {
    "host", "content-length", "transfer-encoding", "connection",
    "x-upstream-url", "x-upstream-auth",
    "authorization",
}


@router.post("/proxy")
@router.post("/proxy/{path:path}")
async def transparent_proxy(
    request: Request,
    _api_key: ApiKey,
    x_upstream_url: Annotated[str | None, Header(alias="X-Upstream-URL")] = None,
    x_upstream_auth: Annotated[str | None, Header(alias="X-Upstream-Auth")] = None,
    path: str = "",
):
    """
    Transparent OpenAI-compatible reverse proxy.
    """
    config = get_config()
    upstream_base = x_upstream_url or config.upstream

    if not upstream_base:
        raise HTTPException(
            status_code=400,
            detail=(
                "No upstream URL configured. "
                "Set 'upstream' in config.yaml or pass X-Upstream-URL header."
            ),
        )

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    messages: list[dict] = body.get("messages") or []

    # ── Step 1: Input scan ────────────────────────────────────────────────────
    class _Msg:
        def __init__(self, role: str, content: str):
            self.role = role
            self.content = content

    user_text = _last_user_message([_Msg(m.get("role", ""), m.get("content", "")) for m in messages])

    if user_text:
        scan_result = await _run_input(request, user_text)
        if scan_result.get("fix_applied") and scan_result.get("sanitized_text") != user_text:
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    messages[i] = {**messages[i], "content": scan_result["sanitized_text"]}
                    break
            body = {**body, "messages": messages}

    # ── Step 2: Forward to upstream ───────────────────────────────────────────
    upstream_path = path.lstrip("/")
    forward_url = f"{upstream_base.rstrip('/')}/{upstream_path}" if upstream_path else upstream_base.rstrip("/")

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
        out_result = await _run_output(request, assistant_text, user_text)
        if out_result.get("fix_applied") and out_result.get("sanitized_text") != assistant_text:
            upstream_body["choices"][0]["message"]["content"] = out_result["sanitized_text"]

    return JSONResponse(content=upstream_body, status_code=200)
