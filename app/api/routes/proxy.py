"""
Transparent LLM proxy — the sole integration pattern.

Seraph sits between your app and the LLM provider, scanning every request
and response.  Point your client at Seraph instead of the LLM and it handles
input scanning, forwarding, output scanning, and response delivery.
"""

from typing import Annotated, Any
import logging

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.auth import verify_api_key
from app.core.config import get_config
from app.services import scanner_engine
from app.services import audit_logger

ApiKey = Annotated[str | None, Depends(verify_api_key)]

router = APIRouter(tags=["proxy"])

logger = logging.getLogger(__name__)


# ── HTTP client & constants ──────────────────────────────────────────────────

_PROXY_CLIENT = httpx.AsyncClient(timeout=120.0)

_HOP_HEADERS = {
    "host", "content-length", "transfer-encoding", "connection",
    "x-upstream-url", "x-upstream-auth",
    "authorization",
}


# ── Message extraction (provider-agnostic) ───────────────────────────────────

def _detect_api_format(body: dict) -> str:
    """Detect the API format from the request body.

    Returns 'openai', 'anthropic', or 'unknown'.
    """
    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        return "unknown"
    # Find a message with content to inspect
    for msg in messages:
        content = msg.get("content")
        if content is None:
            continue
        if isinstance(content, list):
            return "anthropic"
        if isinstance(content, str):
            return "openai"
    return "unknown"


def _extract_user_text(body: dict) -> str:
    """Extract the last user message text, regardless of API format."""
    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        return ""
    fmt = _detect_api_format(body)
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if fmt == "anthropic" and isinstance(content, list):
            # Anthropic: content is a list of blocks like [{"type": "text", "text": "..."}]
            parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return " ".join(parts)
        if isinstance(content, str):
            return content
    return ""


def _extract_assistant_text(body: dict) -> str:
    """Extract assistant content from an upstream response body.

    Handles both OpenAI format (choices[].message.content) and
    Anthropic format (content[].text).
    """
    # OpenAI format
    choices = body.get("choices")
    if choices and isinstance(choices, list):
        try:
            return (choices[0].get("message") or {}).get("content") or ""
        except Exception:
            return ""
    # Anthropic format
    content = body.get("content")
    if content and isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return " ".join(parts)
    return ""


def _apply_input_fix(body: dict, sanitized: str) -> dict:
    """Replace the last user message with sanitized text in the request body."""
    messages = list(body.get("messages") or [])
    fmt = _detect_api_format(body)
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            if fmt == "anthropic" and isinstance(messages[i].get("content"), list):
                messages[i] = {**messages[i], "content": [{"type": "text", "text": sanitized}]}
            else:
                messages[i] = {**messages[i], "content": sanitized}
            break
    return {**body, "messages": messages}


def _apply_output_fix(body: dict, sanitized: str) -> dict:
    """Replace the assistant content in the upstream response body."""
    # OpenAI format
    choices = body.get("choices")
    if choices and isinstance(choices, list):
        body["choices"][0]["message"]["content"] = sanitized
        return body
    # Anthropic format
    content = body.get("content")
    if content and isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                block["text"] = sanitized
                break
        return body
    return body


# ── Scan helpers ─────────────────────────────────────────────────────────────

async def _run_input(request: Request, text: str) -> dict:
    """Scan user input through Seraph."""
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


async def _run_output(request: Request, assistant_text: str, prompt_text: str) -> dict:
    """Scan LLM output through Seraph."""
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


# ── Upstream forwarding ─────────────────────────────────────────────────────

async def _forward_to_upstream(
    request: Request, forward_url: str, body: dict, x_upstream_auth: str | None,
) -> httpx.Response:
    """Forward request to the upstream LLM and return the response."""
    forward_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_HEADERS
    }
    if x_upstream_auth:
        forward_headers["Authorization"] = x_upstream_auth
    try:
        return await _PROXY_CLIENT.post(forward_url, json=body, headers=forward_headers)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream LLM unreachable: {exc}")


async def _stream_from_upstream(
    request: Request, forward_url: str, body: dict, x_upstream_auth: str | None,
) -> StreamingResponse:
    """Forward a streaming request and pass through SSE chunks."""
    forward_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_HEADERS
    }
    if x_upstream_auth:
        forward_headers["Authorization"] = x_upstream_auth
    try:
        req = _PROXY_CLIENT.build_request("POST", forward_url, json=body, headers=forward_headers)
        upstream_resp = await _PROXY_CLIENT.send(req, stream=True)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream LLM unreachable: {exc}")

    async def _iter():
        try:
            async for chunk in upstream_resp.aiter_bytes():
                yield chunk
        finally:
            await upstream_resp.aclose()

    resp_headers = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() not in ("transfer-encoding", "content-length", "connection")
    }
    return StreamingResponse(
        _iter(),
        status_code=upstream_resp.status_code,
        headers=resp_headers,
    )


# ── Proxy helpers ────────────────────────────────────────────────────────────

def _resolve_upstream(config, header_url: str | None) -> str:
    upstream_base = header_url or config.upstream
    if not upstream_base:
        raise HTTPException(
            status_code=400,
            detail="No upstream URL configured. Set 'upstream' in config.yaml or pass X-Upstream-URL header.",
        )
    return upstream_base


def _build_forward_url(upstream_base: str, path: str) -> str:
    upstream_path = path.lstrip("/")
    if upstream_path:
        return f"{upstream_base.rstrip('/')}/{upstream_path}"
    return upstream_base.rstrip("/")


async def _passthrough_non_post(
    request: Request, forward_url: str, x_upstream_auth: str | None,
) -> JSONResponse:
    """Forward non-POST requests without scanning."""
    forward_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_HEADERS
    }
    if x_upstream_auth:
        forward_headers["Authorization"] = x_upstream_auth
    try:
        upstream_resp = await _PROXY_CLIENT.request(
            request.method, forward_url, headers=forward_headers,
        )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream LLM unreachable: {exc}")
    try:
        return JSONResponse(content=upstream_resp.json(), status_code=upstream_resp.status_code)
    except Exception:
        return JSONResponse(content={"error": upstream_resp.text}, status_code=upstream_resp.status_code)


async def _scan_input_and_fix(request: Request, body: dict) -> tuple[dict, str]:
    """Run input scan and apply fixes if needed. Returns (body, user_text)."""
    user_text = _extract_user_text(body)
    if user_text:
        scan_result = await _run_input(request, user_text)
        if scan_result.get("fix_applied") and scan_result.get("sanitized_text") != user_text:
            body = _apply_input_fix(body, scan_result["sanitized_text"])
    return body, user_text


def _relay_upstream_error(upstream_resp: httpx.Response) -> JSONResponse:
    """Convert a non-200 upstream response into a JSONResponse."""
    try:
        err_body = upstream_resp.json()
    except Exception:
        err_body = {"error": upstream_resp.text}
    return JSONResponse(content=err_body, status_code=upstream_resp.status_code)


async def _scan_output_and_fix(
    request: Request, upstream_body: dict, user_text: str,
) -> dict:
    """Run output scan and apply fixes if needed."""
    assistant_text = _extract_assistant_text(upstream_body)
    if assistant_text:
        out_result = await _run_output(request, assistant_text, user_text)
        if out_result.get("fix_applied") and out_result.get("sanitized_text") != assistant_text:
            upstream_body = _apply_output_fix(upstream_body, out_result["sanitized_text"])
    return upstream_body


# ── Proxy route ──────────────────────────────────────────────────────────────

@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    responses={400: {"description": "Bad request"}, 502: {"description": "Upstream error"}},
)
async def transparent_proxy(
    request: Request,
    _api_key: ApiKey,
    x_upstream_url: Annotated[str | None, Header(alias="X-Upstream-URL")] = None,
    x_upstream_auth: Annotated[str | None, Header(alias="X-Upstream-Auth")] = None,
    path: str = "",
):
    """
    Transparent LLM proxy. Scans input, forwards to upstream, scans output.
    Works with any LLM provider and any client.
    """
    config = get_config()
    upstream_base = _resolve_upstream(config, x_upstream_url)
    forward_url = _build_forward_url(upstream_base, path)

    if request.method != "POST":
        return await _passthrough_non_post(request, forward_url, x_upstream_auth)

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    body, user_text = await _scan_input_and_fix(request, body)

    if body.get("stream") is True:
        logger.info("Streaming request — output scanning skipped")
        return await _stream_from_upstream(request, forward_url, body, x_upstream_auth)

    upstream_resp = await _forward_to_upstream(request, forward_url, body, x_upstream_auth)

    if upstream_resp.status_code != 200:
        return _relay_upstream_error(upstream_resp)

    try:
        upstream_body: dict[str, Any] = upstream_resp.json()
    except Exception:
        return JSONResponse(content={"error": "Non-JSON upstream response"}, status_code=502)

    upstream_body = await _scan_output_and_fix(request, upstream_body, user_text)
    return JSONResponse(content=upstream_body, status_code=200)
