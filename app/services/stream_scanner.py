"""
Streaming output scanner — scans SSE response streams from LLM providers.

Three modes:
  - passthrough: No output scanning, chunks pass through immediately (legacy).
  - buffer: Buffer all chunks, reassemble full response, scan, then flush or block.
  - incremental: Scan periodically as tokens accumulate, terminate early on violation.

Handles SSE parsing for both OpenAI and Anthropic streaming formats.
"""
from __future__ import annotations

import json
import logging
import time
from typing import AsyncIterator

from app.services import scanner_engine
from app.services import audit_logger

logger = logging.getLogger(__name__)

# Minimum accumulated tokens before an incremental scan fires.
_INCREMENTAL_SCAN_THRESHOLD = 200


class StreamScanner:
    """Wraps an upstream SSE stream with output scanning and audit logging."""

    def __init__(
        self,
        mode: str,
        request_segments: list | None = None,
        buffer_timeout: float = 30.0,
        ip_address: str | None = None,
        request_meta: dict | None = None,
    ) -> None:
        self.mode = mode
        self.prompt_text = ""
        if request_segments:
            self.prompt_text = " ".join(
                (s.text if hasattr(s, 'text') else s.get("text", ""))
                for s in request_segments
                if (s.role if hasattr(s, 'role') else s.get("role")) == "user"
            )
        self.buffer_timeout = buffer_timeout
        self.ip_address = ip_address
        self.request_meta = request_meta or {}

    async def wrap_stream(
        self, upstream_iter: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        """Wrap the upstream SSE byte iterator with scanning logic."""
        if self.mode == "passthrough":
            async for chunk in upstream_iter:
                yield chunk
            return

        if self.mode == "buffer":
            async for chunk in self._buffer_and_scan(upstream_iter):
                yield chunk
            return

        if self.mode == "incremental":
            async for chunk in self._incremental_scan(upstream_iter):
                yield chunk
            return

        # Unknown mode — fall back to passthrough
        logger.warning("Unknown streaming scan mode '%s', falling back to passthrough", self.mode)
        async for chunk in upstream_iter:
            yield chunk

    async def _buffer_and_scan(
        self, upstream_iter: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        """Buffer all chunks, scan the complete response, then replay or block."""
        buffered_chunks: list[bytes] = []
        accumulated_text = ""
        upstream_start = time.monotonic()

        async for chunk in upstream_iter:
            buffered_chunks.append(chunk)
            accumulated_text += _extract_delta_text(chunk)

        upstream_ms = (time.monotonic() - upstream_start) * 1000

        # Extract tool calls from buffered SSE data
        tool_calls = _extract_tool_calls_from_stream(buffered_chunks)

        # Scan the full accumulated response
        if accumulated_text.strip():
            scan_start = time.monotonic()
            is_valid, sanitized, results, violations, actions, reask, fix_applied = (
                await scanner_engine.run_output_scan(self.prompt_text, accumulated_text)
            )
            scan_ms = (time.monotonic() - scan_start) * 1000

            # Build metadata for audit
            meta = dict(self.request_meta)
            meta["scan_duration_ms"] = round(scan_ms, 1)
            meta["stream_duration_ms"] = round(upstream_ms, 1)
            if tool_calls:
                meta["tool_calls"] = tool_calls

            # Log to audit
            await audit_logger.log_scan(
                direction="output",
                is_valid=is_valid,
                scanner_results=results,
                violations=violations,
                on_fail_actions=actions,
                text_length=len(accumulated_text),
                fix_applied=fix_applied,
                ip_address=self.ip_address,
                segments=[{"role": "assistant", "source": "streamed_response", "text": accumulated_text}],
                metadata=meta,
            )

            if not is_valid:
                detail = (
                    reask[0] if reask
                    else f"Response blocked by guardrail(s): {', '.join(violations)}"
                )
                logger.warning("Streaming output blocked: %s", detail)
                error_payload = json.dumps({"error": {"message": detail, "type": "guardrail_violation"}})
                yield f"data: {error_payload}\n\n".encode()
                yield b"data: [DONE]\n\n"
                return

        # Scan passed — replay all buffered chunks
        for chunk in buffered_chunks:
            yield chunk

    async def _incremental_scan(
        self, upstream_iter: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        """Scan periodically as tokens accumulate; terminate early on violation."""
        pending_chunks: list[bytes] = []
        accumulated_text = ""
        last_scanned_len = 0

        async for chunk in upstream_iter:
            pending_chunks.append(chunk)
            accumulated_text += _extract_delta_text(chunk)

            new_text_len = len(accumulated_text) - last_scanned_len
            if new_text_len >= _INCREMENTAL_SCAN_THRESHOLD:
                scan_ok = await self._check_accumulated(accumulated_text)
                if not scan_ok:
                    error_payload = json.dumps({
                        "error": {
                            "message": "Response terminated: guardrail violation detected",
                            "type": "guardrail_violation",
                        }
                    })
                    yield f"data: {error_payload}\n\n".encode()
                    yield b"data: [DONE]\n\n"
                    return
                last_scanned_len = len(accumulated_text)

            for pc in pending_chunks:
                yield pc
            pending_chunks.clear()

        # Final scan
        if len(accumulated_text) > last_scanned_len and accumulated_text.strip():
            scan_ok = await self._check_accumulated(accumulated_text)
            if not scan_ok:
                error_payload = json.dumps({
                    "error": {
                        "message": "Response terminated: guardrail violation detected",
                        "type": "guardrail_violation",
                    }
                })
                yield f"data: {error_payload}\n\n".encode()
                yield b"data: [DONE]\n\n"
                return

        for pc in pending_chunks:
            yield pc

    async def _check_accumulated(self, text: str) -> bool:
        """Run output scan on accumulated text. Returns True if valid."""
        is_valid, *_ = await scanner_engine.run_output_scan(self.prompt_text, text)
        return is_valid


def _extract_delta_text(chunk: bytes) -> str:
    """Extract text content from an SSE chunk (OpenAI or Anthropic format)."""
    text_parts: list[str] = []
    try:
        decoded = chunk.decode("utf-8", errors="replace")
    except Exception:
        return ""

    for line in decoded.split("\n"):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            continue
        try:
            data = json.loads(data_str)
        except (json.JSONDecodeError, ValueError):
            continue

        # OpenAI streaming: choices[0].delta.content
        choices = data.get("choices")
        if choices and isinstance(choices, list):
            delta = (choices[0] or {}).get("delta", {})
            if isinstance(delta, dict):
                content = delta.get("content", "")
                if content:
                    text_parts.append(content)
            continue

        # Anthropic streaming: delta.text
        delta = data.get("delta")
        if isinstance(delta, dict):
            text = delta.get("text", "")
            if text:
                text_parts.append(text)

    return "".join(text_parts)


def _extract_tool_calls_from_stream(chunks: list[bytes]) -> list[dict]:
    """Extract tool calls from buffered SSE chunks."""
    tool_calls: list[dict] = []
    # Track tool call assembly from streaming deltas
    tc_map: dict[int, dict] = {}

    for chunk in chunks:
        try:
            decoded = chunk.decode("utf-8", errors="replace")
        except Exception:
            continue

        for line in decoded.split("\n"):
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                continue
            try:
                data = json.loads(data_str)
            except (json.JSONDecodeError, ValueError):
                continue

            choices = data.get("choices")
            if not choices or not isinstance(choices, list):
                continue
            delta = (choices[0] or {}).get("delta", {})
            if not isinstance(delta, dict):
                continue

            # Tool call deltas
            tcs = delta.get("tool_calls")
            if tcs and isinstance(tcs, list):
                for tc in tcs:
                    idx = tc.get("index", 0)
                    if idx not in tc_map:
                        tc_map[idx] = {"name": "", "arguments": ""}
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        tc_map[idx]["name"] = fn["name"]
                    if fn.get("arguments"):
                        tc_map[idx]["arguments"] += fn["arguments"]

    for idx in sorted(tc_map.keys()):
        if tc_map[idx]["name"]:
            tool_calls.append(tc_map[idx])

    return tool_calls
