"""
Transparent LLM proxy — the sole integration pattern.

Seraph sits between your app and the LLM provider, scanning every request
and response.  Point your client at Seraph instead of the LLM and it handles
input scanning, forwarding, output scanning, and response delivery.
"""

from typing import Annotated, Any
import logging
import time

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.auth import verify_api_key
from app.core.config import get_config
from app.services import scanner_engine
from app.services import audit_logger
from app.services.stream_scanner import StreamScanner

ApiKey = Annotated[str | None, Depends(verify_api_key)]

router = APIRouter(tags=["proxy"])

logger = logging.getLogger(__name__)


# ── HTTP client & constants ──────────────────────────────────────────────────

_PROXY_CLIENT = httpx.AsyncClient(timeout=120.0)

_HOP_HEADERS = {
    "host", "content-length", "transfer-encoding", "connection",
    "accept-encoding",
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
    """Extract assistant content from an upstream response body."""
    choices = body.get("choices")
    if choices and isinstance(choices, list):
        try:
            return (choices[0].get("message") or {}).get("content") or ""
        except Exception:
            return ""
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
    choices = body.get("choices")
    if choices and isinstance(choices, list):
        body["choices"][0]["message"]["content"] = sanitized
        return body
    content = body.get("content")
    if content and isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                block["text"] = sanitized
                break
        return body
    return body


# ── Metadata extraction ──────────────────────────────────────────────────────

def _extract_all_messages(body: dict) -> list[dict]:
    """Extract all messages from the request body as audit segments."""
    segments = []
    messages = body.get("messages")
    if messages and isinstance(messages, list):
        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "unknown")
            content = msg.get("content")
            if content is None:
                continue
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = " ".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            else:
                continue
            if text.strip():
                segments.append({"role": role, "source": f"messages[{i}]", "text": text})
    # Tool/function definitions
    for key in ("tools", "functions"):
        items = body.get(key)
        if items and isinstance(items, list):
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                fn = item.get("function", item) if key == "tools" else item
                desc = fn.get("description", "")
                name = fn.get("name", "")
                if desc:
                    segments.append({
                        "role": "tool_definition",
                        "source": f"{key}[{i}].description",
                        "text": f"{name}: {desc}" if name else desc,
                    })
    return segments


def _extract_request_metadata(body: dict, path: str) -> dict:
    """Extract request-level metadata for audit logging."""
    meta: dict[str, Any] = {"request_path": f"/{path}"}

    # Model name
    model = body.get("model")
    if model:
        meta["model"] = model

    # Message count
    messages = body.get("messages")
    if messages and isinstance(messages, list):
        meta["message_count"] = len(messages)
        # Count by role
        role_counts: dict[str, int] = {}
        for msg in messages:
            r = msg.get("role", "unknown")
            role_counts[r] = role_counts.get(r, 0) + 1
        meta["role_counts"] = role_counts

    # Streaming flag
    if body.get("stream"):
        meta["streaming"] = True

    # Tool/function count
    tools = body.get("tools") or body.get("functions")
    if tools and isinstance(tools, list):
        meta["tool_count"] = len(tools)

    return meta


def _extract_response_metadata(upstream_body: dict, upstream_status: int, duration_ms: float) -> dict:
    """Extract response-level metadata for audit logging."""
    meta: dict[str, Any] = {
        "upstream_status": upstream_status,
        "duration_ms": round(duration_ms, 1),
    }

    # Token usage (OpenAI format)
    usage = upstream_body.get("usage")
    if usage and isinstance(usage, dict):
        meta["prompt_tokens"] = usage.get("prompt_tokens", 0)
        meta["completion_tokens"] = usage.get("completion_tokens", 0)
        meta["total_tokens"] = usage.get("total_tokens", 0)

    # Anthropic usage format
    if not usage:
        anth_usage = upstream_body.get("usage")
        if anth_usage and isinstance(anth_usage, dict):
            meta["prompt_tokens"] = anth_usage.get("input_tokens", 0)
            meta["completion_tokens"] = anth_usage.get("output_tokens", 0)

    # Tool calls from response
    tool_calls = _extract_tool_calls(upstream_body)
    if tool_calls:
        meta["tool_calls"] = tool_calls

    # Finish reason
    choices = upstream_body.get("choices")
    if choices and isinstance(choices, list) and len(choices) > 0:
        fr = choices[0].get("finish_reason")
        if fr:
            meta["finish_reason"] = fr

    # Stop reason (Anthropic)
    stop_reason = upstream_body.get("stop_reason")
    if stop_reason:
        meta["finish_reason"] = stop_reason

    return meta


def _extract_tool_calls(body: dict) -> list[dict]:
    """Extract tool calls from an LLM response for audit logging."""
    tool_calls = []

    # OpenAI: choices[0].message.tool_calls
    choices = body.get("choices")
    if choices and isinstance(choices, list):
        msg = (choices[0] or {}).get("message", {})
        if isinstance(msg, dict):
            tcs = msg.get("tool_calls")
            if tcs and isinstance(tcs, list):
                for tc in tcs:
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get("function", {})
                    tool_calls.append({
                        "name": fn.get("name", "unknown"),
                        "arguments": fn.get("arguments", ""),
                    })

    # Anthropic: content[].type == "tool_use"
    content = body.get("content")
    if content and isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_calls.append({
                    "name": block.get("name", "unknown"),
                    "arguments": str(block.get("input", "")),
                })

    return tool_calls


# ── Scan helpers ─────────────────────────────────────────────────────────────

async def _run_input(
    request: Request, text: str,
    body: dict | None = None, request_meta: dict | None = None,
) -> dict:
    """Scan user input through Seraph."""
    ip = request.client.host if request.client else None
    scan_start = time.monotonic()

    is_valid, sanitized, results, violations, on_fail_actions, reask_context, fix_applied = (
        await scanner_engine.run_input_scan(text)
    )

    scan_ms = (time.monotonic() - scan_start) * 1000
    monitored = [k for k, v in on_fail_actions.items() if v == "monitored"]

    # Extract all message segments for audit trail
    segments = _extract_all_messages(body) if body else [{"role": "user", "source": "text", "text": text}]

    # Build metadata
    meta = dict(request_meta) if request_meta else {}
    meta["scan_duration_ms"] = round(scan_ms, 1)

    await audit_logger.log_scan(
        direction="input",
        is_valid=is_valid,
        scanner_results=results,
        violations=violations + monitored,
        on_fail_actions=on_fail_actions,
        text_length=len(text),
        fix_applied=fix_applied,
        ip_address=ip,
        segments=segments,
        metadata=meta,
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
    request: Request, assistant_text: str, prompt_text: str,
    upstream_body: dict | None = None, response_meta: dict | None = None,
) -> dict:
    """Scan LLM output through Seraph."""
    ip = request.client.host if request.client else None
    scan_start = time.monotonic()

    is_valid, sanitized, results, violations, on_fail_actions, reask_context, fix_applied = (
        await scanner_engine.run_output_scan(prompt_text, assistant_text)
    )

    scan_ms = (time.monotonic() - scan_start) * 1000
    monitored = [k for k, v in on_fail_actions.items() if v == "monitored"]

    # Build metadata with response info
    meta = dict(response_meta) if response_meta else {}
    meta["scan_duration_ms"] = round(scan_ms, 1)

    await audit_logger.log_scan(
        direction="output",
        is_valid=is_valid,
        scanner_results=results,
        violations=violations + monitored,
        on_fail_actions=on_fail_actions,
        text_length=len(assistant_text),
        fix_applied=fix_applied,
        ip_address=ip,
        segments=[{"role": "assistant", "source": "response", "text": assistant_text}],
        metadata=meta,
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
    stream_scanner: StreamScanner | None = None,
) -> StreamingResponse:
    """Forward a streaming request, optionally scanning the output."""
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

    async def _raw_iter():
        try:
            async for chunk in upstream_resp.aiter_bytes():
                yield chunk
        finally:
            await upstream_resp.aclose()

    # Wrap with scanner if provided
    if stream_scanner:
        output_iter = stream_scanner.wrap_stream(_raw_iter())
    else:
        output_iter = _raw_iter()

    async def _safe_iter():
        async for chunk in output_iter:
            yield chunk

    resp_headers = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() not in ("transfer-encoding", "content-length", "connection")
    }
    return StreamingResponse(
        _safe_iter(),
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


def _resolve_upstream_auth(config, header_auth: str | None) -> str | None:
    """Resolve upstream auth: config key takes priority, header is override."""
    if config.upstream_api_key:
        return f"Bearer {config.upstream_api_key}"
    return header_auth


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


def _relay_upstream_error(upstream_resp: httpx.Response) -> JSONResponse:
    """Convert a non-200 upstream response into a JSONResponse."""
    try:
        err_body = upstream_resp.json()
    except Exception:
        err_body = {"error": upstream_resp.text}
    return JSONResponse(content=err_body, status_code=upstream_resp.status_code)


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
    upstream_auth = _resolve_upstream_auth(config, x_upstream_auth)
    forward_url = _build_forward_url(upstream_base, path)

    if request.method != "POST":
        return await _passthrough_non_post(request, forward_url, upstream_auth)

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    # Extract request-level metadata
    request_meta = _extract_request_metadata(body, path)

    # Input scan
    user_text = _extract_user_text(body)
    if user_text:
        scan_result = await _run_input(request, user_text, body=body, request_meta=request_meta)
        if scan_result.get("fix_applied") and scan_result.get("sanitized_text") != user_text:
            body = _apply_input_fix(body, scan_result["sanitized_text"])

    if body.get("stream") is True:
        scan_mode = config.streaming.output_scan_mode
        logger.info("Streaming request — output scan mode: %s", scan_mode)
        ip = request.client.host if request.client else None
        segments = _extract_all_messages(body) if body else []
        stream_scanner = StreamScanner(
            mode=scan_mode,
            request_segments=segments,
            buffer_timeout=config.streaming.buffer_timeout_seconds,
            ip_address=ip,
            request_meta=request_meta,
        )
        return await _stream_from_upstream(
            request, forward_url, body, upstream_auth, stream_scanner=stream_scanner,
        )

    # Forward to upstream and time it
    upstream_start = time.monotonic()
    upstream_resp = await _forward_to_upstream(request, forward_url, body, upstream_auth)
    upstream_ms = (time.monotonic() - upstream_start) * 1000

    if upstream_resp.status_code != 200:
        return _relay_upstream_error(upstream_resp)

    try:
        upstream_body: dict[str, Any] = upstream_resp.json()
    except Exception:
        return JSONResponse(content={"error": "Non-JSON upstream response"}, status_code=502)

    # Extract response metadata
    response_meta = _extract_response_metadata(upstream_body, upstream_resp.status_code, upstream_ms)
    response_meta["request_path"] = f"/{path}"
    response_meta["model"] = body.get("model", "")

    # Output scan
    assistant_text = _extract_assistant_text(upstream_body)
    if assistant_text:
        out_result = await _run_output(
            request, assistant_text, user_text,
            upstream_body=upstream_body, response_meta=response_meta,
        )
        if out_result.get("fix_applied") and out_result.get("sanitized_text") != assistant_text:
            upstream_body = _apply_output_fix(upstream_body, out_result["sanitized_text"])

    return JSONResponse(content=upstream_body, status_code=200)
