"""Tests for app/services/stream_scanner.py — streaming output scanning."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch

from app.services.stream_scanner import StreamScanner, _extract_delta_text
from app.services.text_extractor import TextSegment


_run = lambda coro: asyncio.get_event_loop().run_until_complete(coro)


def _clean_scan_result(text=""):
    return (True, text, {}, [], {}, None, False)


def _blocked_scan_result(text=""):
    return (False, text, {"Toxicity": 0.95}, ["Toxicity"], {"Toxicity": "blocked"}, None, False)


async def _collect_stream(scanner, chunks):
    """Helper to run wrap_stream and collect output."""
    async def mock_iter():
        for c in chunks:
            yield c

    result = []
    async for chunk in scanner.wrap_stream(mock_iter()):
        result.append(chunk)
    return result


class TestExtractDeltaText:
    def test_openai_delta(self):
        chunk = b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        assert _extract_delta_text(chunk) == "Hello"

    def test_anthropic_delta(self):
        chunk = b'data: {"type":"content_block_delta","delta":{"text":"Hi"}}\n\n'
        assert _extract_delta_text(chunk) == "Hi"

    def test_done_marker(self):
        assert _extract_delta_text(b"data: [DONE]\n\n") == ""

    def test_non_sse_data(self):
        assert _extract_delta_text(b"not sse data") == ""

    def test_multiple_lines(self):
        chunk = (
            b'data: {"choices":[{"delta":{"content":"A"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"B"}}]}\n\n'
        )
        assert _extract_delta_text(chunk) == "AB"

    def test_empty_delta(self):
        chunk = b'data: {"choices":[{"delta":{}}]}\n\n'
        assert _extract_delta_text(chunk) == ""


class TestPassthroughMode:
    def test_chunks_pass_through(self):
        scanner = StreamScanner(mode="passthrough")
        chunks = [b"chunk1", b"chunk2", b"chunk3"]
        result = _run(_collect_stream(scanner, chunks))
        assert result == chunks


class TestBufferMode:
    def test_clean_output_replayed(self):
        scanner = StreamScanner(mode="buffer")
        chunks = [
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
            b'data: [DONE]\n\n',
        ]

        with patch(
            "app.services.scanner_engine.run_output_scan",
            new_callable=AsyncMock,
            return_value=_clean_scan_result("Hello"),
        ):
            result = _run(_collect_stream(scanner, chunks))

        assert result == chunks

    def test_blocked_output_returns_error(self):
        scanner = StreamScanner(mode="buffer")
        chunks = [
            b'data: {"choices":[{"delta":{"content":"toxic stuff"}}]}\n\n',
            b'data: [DONE]\n\n',
        ]

        with patch(
            "app.services.scanner_engine.run_output_scan",
            new_callable=AsyncMock,
            return_value=_blocked_scan_result("toxic stuff"),
        ):
            result = _run(_collect_stream(scanner, chunks))

        # Should get error event + DONE, not the original chunks
        assert len(result) == 2
        error_data = json.loads(result[0].decode().split("data: ")[1])
        assert "error" in error_data
        assert "guardrail" in error_data["error"]["type"]

    def test_empty_output_not_scanned(self):
        scanner = StreamScanner(mode="buffer")
        chunks = [b"data: [DONE]\n\n"]

        with patch(
            "app.services.scanner_engine.run_output_scan",
            new_callable=AsyncMock,
        ) as mock_scan:
            result = _run(_collect_stream(scanner, chunks))

        # Empty text should not trigger scan
        mock_scan.assert_not_called()
        assert result == chunks


class TestIncrementalMode:
    def test_clean_output_streams_through(self):
        scanner = StreamScanner(mode="incremental")
        # Generate enough text to trigger a scan
        chunks = [
            b'data: {"choices":[{"delta":{"content":"' + b"x" * 250 + b'"}}]}\n\n',
            b'data: [DONE]\n\n',
        ]

        with patch(
            "app.services.scanner_engine.run_output_scan",
            new_callable=AsyncMock,
            return_value=_clean_scan_result(),
        ):
            result = _run(_collect_stream(scanner, chunks))

        assert len(result) == 2

    def test_violation_terminates_stream(self):
        scanner = StreamScanner(mode="incremental")
        chunks = [
            b'data: {"choices":[{"delta":{"content":"' + b"toxic" * 100 + b'"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"more text"}}]}\n\n',
        ]

        with patch(
            "app.services.scanner_engine.run_output_scan",
            new_callable=AsyncMock,
            return_value=_blocked_scan_result(),
        ):
            result = _run(_collect_stream(scanner, chunks))

        # Should have error + DONE
        decoded = b"".join(result).decode()
        assert "guardrail_violation" in decoded


class TestStreamScannerPromptText:
    def test_prompt_text_from_segments(self):
        segments = [
            TextSegment(text="system prompt", role="system", source="s"),
            TextSegment(text="user question", role="user", source="u"),
        ]
        scanner = StreamScanner(mode="buffer", request_segments=segments)
        assert scanner.prompt_text == "user question"

    def test_no_segments(self):
        scanner = StreamScanner(mode="buffer")
        assert scanner.prompt_text == ""
