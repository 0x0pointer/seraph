"""
Tests targeting coverage gaps across the codebase.
Covers uncovered lines in proxy.py, text_extractor.py, stream_scanner.py,
scanner_engine.py, and audit_logger.py.
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_run = lambda coro: asyncio.run(coro)


# ── text_extractor.py coverage gaps ──────────────────────────────────────────

class TestTextExtractorEdgeCases:
    def test_non_dict_message_skipped(self):
        from app.services.text_extractor import extract_request_segments
        body = {"messages": ["not a dict", {"role": "user", "content": "hi"}]}
        segs = extract_request_segments(body)
        assert len(segs) == 1
        assert segs[0].role == "user"

    def test_message_with_non_string_non_list_content_skipped(self):
        from app.services.text_extractor import extract_request_segments
        body = {"messages": [{"role": "user", "content": 42}]}
        assert extract_request_segments(body) == []

    def test_empty_tool_calls_list(self):
        from app.services.text_extractor import extract_request_segments
        body = {"messages": [{"role": "assistant", "content": "ok", "tool_calls": []}]}
        segs = extract_request_segments(body)
        assert len(segs) == 1  # just the assistant content

    def test_tool_call_with_empty_arguments(self):
        from app.services.text_extractor import extract_request_segments
        body = {"messages": [{"role": "assistant", "content": None, "tool_calls": [
            {"function": {"name": "test", "arguments": ""}},
        ]}]}
        segs = extract_request_segments(body)
        tc = [s for s in segs if s.role == "tool_call"]
        assert len(tc) == 0  # empty args skipped

    def test_tool_call_non_dict_skipped(self):
        from app.services.text_extractor import extract_request_segments
        body = {"messages": [{"role": "assistant", "content": None, "tool_calls": ["not_dict"]}]}
        segs = extract_request_segments(body)
        assert len(segs) == 0

    def test_tool_definitions_non_dict_tool_skipped(self):
        from app.services.text_extractor import extract_request_segments
        body = {"messages": [{"role": "user", "content": "hi"}], "tools": ["not_dict"]}
        segs = extract_request_segments(body)
        td = [s for s in segs if s.role == "tool_definition"]
        assert len(td) == 0

    def test_tool_definitions_empty_description_skipped(self):
        from app.services.text_extractor import extract_request_segments
        body = {"messages": [{"role": "user", "content": "hi"}], "tools": [
            {"type": "function", "function": {"name": "test", "description": ""}},
        ]}
        segs = extract_request_segments(body)
        td = [s for s in segs if s.role == "tool_definition"]
        assert len(td) == 0

    def test_legacy_functions_non_dict_skipped(self):
        from app.services.text_extractor import extract_request_segments
        body = {"messages": [{"role": "user", "content": "hi"}], "functions": [42]}
        segs = extract_request_segments(body)
        td = [s for s in segs if s.role == "tool_definition"]
        assert len(td) == 0

    def test_anthropic_response_tool_use_block(self):
        from app.services.text_extractor import extract_response_segments
        body = {"content": [
            {"type": "text", "text": "Let me search."},
            {"type": "tool_use", "name": "search", "input": '{"q":"test"}'},
        ]}
        segs = extract_response_segments(body)
        assert len(segs) == 2
        tc = [s for s in segs if s.role == "tool_call"]
        assert len(tc) == 1
        assert tc[0].text == '{"q":"test"}'

    def test_anthropic_response_non_dict_block_skipped(self):
        from app.services.text_extractor import extract_response_segments
        body = {"content": ["not_dict", {"type": "text", "text": "hi"}]}
        segs = extract_response_segments(body)
        assert len(segs) == 1

    def test_openai_response_non_dict_choice_skipped(self):
        from app.services.text_extractor import extract_response_segments
        body = {"choices": ["not_dict"]}
        assert extract_response_segments(body) == []

    def test_openai_response_non_dict_message_skipped(self):
        from app.services.text_extractor import extract_response_segments
        body = {"choices": [{"message": "not_dict"}]}
        assert extract_response_segments(body) == []

    def test_text_from_content_block_tool_use_non_string_input(self):
        from app.services.text_extractor import _text_from_content_block
        assert _text_from_content_block({"type": "tool_use", "input": {"key": "val"}}) == ""

    def test_text_from_content_block_unknown_type(self):
        from app.services.text_extractor import _text_from_content_block
        assert _text_from_content_block({"type": "image", "data": "..."}) == ""

    def test_text_from_content_block_non_dict(self):
        from app.services.text_extractor import _text_from_content_block
        assert _text_from_content_block(42) == ""

    def test_apply_segment_fix_string_at_index(self):
        from app.services.text_extractor import apply_segment_fix
        body = {"items": ["old_text", "other"]}
        result = apply_segment_fix(body, "items[0]", "new_text")
        assert result["items"][0] == "new_text"

    def test_apply_segment_fix_list_content_at_key(self):
        from app.services.text_extractor import apply_segment_fix
        body = {"content": [{"type": "text", "text": "old"}]}
        result = apply_segment_fix(body, "content", "new")
        assert result["content"][0]["text"] == "new"

    def test_apply_segment_fix_no_text_block_in_list(self):
        from app.services.text_extractor import apply_segment_fix
        body = {"content": [{"type": "image", "data": "x"}]}
        result = apply_segment_fix(body, "content", "new")
        assert result["content"][0]["type"] == "image"  # unchanged

    def test_apply_segment_fix_index_out_of_range(self):
        from app.services.text_extractor import apply_segment_fix
        body = {"items": ["a"]}
        result = apply_segment_fix(body, "items[5]", "x")
        assert result["items"] == ["a"]  # unchanged

    def test_apply_segment_fix_non_list_at_index(self):
        from app.services.text_extractor import apply_segment_fix
        body = {"item": "string_val"}
        result = apply_segment_fix(body, "item[0]", "x")
        assert result == body

    def test_system_prompt_empty_string_skipped(self):
        from app.services.text_extractor import extract_request_segments
        body = {"system": "  ", "messages": [{"role": "user", "content": "hi"}]}
        segs = extract_request_segments(body)
        system_segs = [s for s in segs if s.source == "system"]
        assert len(system_segs) == 0


# ── stream_scanner.py coverage gaps ──────────────────────────────────────────

class TestStreamScannerEdgeCases:
    def test_unknown_mode_falls_back_to_passthrough(self):
        from app.services.stream_scanner import StreamScanner
        scanner = StreamScanner(mode="unknown_mode")
        chunks = [b"chunk1"]
        result = _run(self._collect(scanner, chunks))
        assert result == chunks

    def test_incremental_final_scan_violation(self):
        """Final scan at end of stream catches remaining text."""
        from app.services.stream_scanner import StreamScanner
        scanner = StreamScanner(mode="incremental")
        # Small chunks that don't trigger mid-stream scan, but final scan blocks
        chunks = [b'data: {"choices":[{"delta":{"content":"bad"}}]}\n\n']

        with patch(
            "app.services.scanner_engine.run_output_scan",
            new_callable=AsyncMock,
            return_value={
                "raw_text": "bad", "direction": "output", "prompt_context": "",
                "scanner_results": {"T": 0.9}, "violations": ["T"],
                "on_fail_actions": {"T": "blocked"}, "sanitized_text": "bad",
                "blocked": True, "block_reason": "blocked", "nemo_risk_score": 0.9,
            },
        ):
            result = _run(self._collect(scanner, chunks))

        decoded = b"".join(result).decode()
        assert "guardrail_violation" in decoded

    def test_incremental_no_final_scan_when_already_scanned(self):
        """When all text was already scanned incrementally, no final scan."""
        from app.services.stream_scanner import StreamScanner
        scanner = StreamScanner(mode="incremental")
        # Enough text to trigger incremental scan
        chunks = [
            b'data: {"choices":[{"delta":{"content":"' + b"x" * 250 + b'"}}]}\n\n',
        ]

        with patch(
            "app.services.scanner_engine.run_output_scan",
            new_callable=AsyncMock,
            return_value={
                "raw_text": "", "direction": "output", "prompt_context": "",
                "scanner_results": {}, "violations": [], "on_fail_actions": {},
                "sanitized_text": "", "blocked": False, "block_reason": None,
                "nemo_risk_score": 0.0,
            },
        ) as mock_scan:
            result = _run(self._collect(scanner, chunks))

        # Only called once (incremental), not twice (no final)
        assert mock_scan.call_count == 1

    def test_extract_tool_calls_from_stream(self):
        from app.services.stream_scanner import _extract_tool_calls_from_stream
        chunks = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"search"}}]}}]}\n\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"q\\":"}}]}}]}\n\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"test\\"}"}}]}}]}\n\n',
        ]
        result = _extract_tool_calls_from_stream(chunks)
        assert len(result) == 1
        assert result[0]["name"] == "search"
        assert result[0]["arguments"] == '{"q":"test"}'

    def test_extract_tool_calls_empty_name_skipped(self):
        from app.services.stream_scanner import _extract_tool_calls_from_stream
        chunks = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"x"}}]}}]}\n\n',
        ]
        result = _extract_tool_calls_from_stream(chunks)
        assert len(result) == 0  # no name = skipped

    def test_prompt_text_from_dict_segments(self):
        from app.services.stream_scanner import StreamScanner
        segments = [
            {"role": "system", "text": "sys", "source": "s"},
            {"role": "user", "text": "hello", "source": "u"},
        ]
        scanner = StreamScanner(mode="buffer", request_segments=segments)
        assert scanner.prompt_text == "hello"

    def test_buffer_mode_audit_log_called(self):
        from app.services.stream_scanner import StreamScanner
        scanner = StreamScanner(mode="buffer", ip_address="1.2.3.4", request_meta={"model": "gpt-4"})
        chunks = [b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n', b'data: [DONE]\n\n']

        with (
            patch("app.services.scanner_engine.run_output_scan", new_callable=AsyncMock,
                  return_value={
                      "raw_text": "hi", "direction": "output", "prompt_context": "",
                      "scanner_results": {}, "violations": [], "on_fail_actions": {},
                      "sanitized_text": "hi", "blocked": False, "block_reason": None,
                      "nemo_risk_score": 0.0,
                  }),
            patch("app.services.audit_logger.log_scan", new_callable=AsyncMock) as mock_log,
        ):
            _run(self._collect(scanner, chunks))

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["direction"] == "output"
        assert call_kwargs["ip_address"] == "1.2.3.4"

    async def _collect(self, scanner, chunks):
        async def mock_iter():
            for c in chunks:
                yield c
        result = []
        async for chunk in scanner.wrap_stream(mock_iter()):
            result.append(chunk)
        return result


# ── proxy.py coverage gaps ───────────────────────────────────────────────────

class TestProxyMetadataExtraction:
    def test_extract_request_metadata(self):
        from app.api.routes.proxy import _extract_request_metadata
        body = {
            "model": "gpt-4",
            "messages": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ],
            "stream": True,
            "tools": [{"type": "function", "function": {"name": "t"}}],
        }
        meta = _extract_request_metadata(body, "v1/chat/completions")
        assert meta["model"] == "gpt-4"
        assert meta["message_count"] == 2
        assert meta["role_counts"] == {"system": 1, "user": 1}
        assert meta["streaming"] is True
        assert meta["tool_count"] == 1
        assert meta["request_path"] == "/v1/chat/completions"

    def test_extract_request_metadata_minimal(self):
        from app.api.routes.proxy import _extract_request_metadata
        meta = _extract_request_metadata({}, "v1/test")
        assert meta["request_path"] == "/v1/test"
        assert "model" not in meta
        assert "streaming" not in meta

    def test_extract_response_metadata_with_usage(self):
        from app.api.routes.proxy import _extract_response_metadata
        body = {
            "choices": [{"finish_reason": "stop", "message": {"content": "hi"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }
        meta = _extract_response_metadata(body, 200, 1234.5)
        assert meta["upstream_status"] == 200
        assert meta["duration_ms"] == 1234.5
        assert meta["prompt_tokens"] == 100
        assert meta["completion_tokens"] == 50
        assert meta["total_tokens"] == 150
        assert meta["finish_reason"] == "stop"

    def test_extract_response_metadata_anthropic_stop_reason(self):
        from app.api.routes.proxy import _extract_response_metadata
        body = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "hi"}]}
        meta = _extract_response_metadata(body, 200, 500.0)
        assert meta["finish_reason"] == "end_turn"

    def test_extract_tool_calls_openai(self):
        from app.api.routes.proxy import _extract_tool_calls
        body = {"choices": [{"message": {
            "tool_calls": [{"function": {"name": "search", "arguments": '{"q":"x"}'}}],
        }}]}
        result = _extract_tool_calls(body)
        assert len(result) == 1
        assert result[0]["name"] == "search"

    def test_extract_tool_calls_anthropic(self):
        from app.api.routes.proxy import _extract_tool_calls
        body = {"content": [{"type": "tool_use", "name": "calc", "input": "2+2"}]}
        result = _extract_tool_calls(body)
        assert len(result) == 1
        assert result[0]["name"] == "calc"

    def test_extract_tool_calls_empty(self):
        from app.api.routes.proxy import _extract_tool_calls
        assert _extract_tool_calls({}) == []
        assert _extract_tool_calls({"choices": [{"message": {}}]}) == []

    def test_extract_tool_definition_segments(self):
        from app.api.routes.proxy import _extract_tool_definition_segments
        body = {
            "tools": [{"function": {"name": "a", "description": "A tool"}}],
            "functions": [{"name": "b", "description": "B tool"}],
        }
        segs: list = []
        _extract_tool_definition_segments(body, segs)
        assert len(segs) == 2

    def test_extract_message_segments_empty(self):
        from app.api.routes.proxy import _extract_message_segments
        segs: list = []
        _extract_message_segments({}, segs)
        assert segs == []
        _extract_message_segments({"messages": "not_list"}, segs)
        assert segs == []


# ── audit_logger.py coverage gaps ────────────────────────────────────────────

class TestAuditLoggerHelpers:
    def test_serialize_segments_with_dicts(self):
        from app.services.audit_logger import _serialize_segments
        result = _serialize_segments([{"role": "user", "source": "a", "text": "hi"}])
        parsed = json.loads(result)
        assert parsed[0]["role"] == "user"

    def test_serialize_segments_with_objects(self):
        from app.services.text_extractor import TextSegment
        from app.services.audit_logger import _serialize_segments
        seg = TextSegment(text="hello", role="user", source="test")
        result = _serialize_segments([seg])
        parsed = json.loads(result)
        assert parsed[0]["text"] == "hello"

    def test_serialize_segments_none(self):
        from app.services.audit_logger import _serialize_segments
        assert _serialize_segments(None) is None
        assert _serialize_segments([]) is None

    def test_build_record(self):
        from app.services.audit_logger import _build_record
        record = _build_record(
            "2026-01-01", "input", True, {"S": 0.1}, [], None,
            10, False, "1.2.3.4", '[]', {"model": "gpt-4"},
        )
        assert record["direction"] == "input"
        assert record["ip_address"] == "1.2.3.4"
        assert record["metadata"]["model"] == "gpt-4"

    def test_build_record_no_optionals(self):
        from app.services.audit_logger import _build_record
        record = _build_record(
            "2026-01-01", "input", True, {}, [], None,
            0, False, None, None, None,
        )
        assert "ip_address" not in record
        assert "segments" not in record
        assert "metadata" not in record

    def test_json_dumps_handles_numpy_float(self):
        from app.services.audit_logger import _json_dumps
        import struct
        # Simulate a numpy-like float that's not a regular Python float
        class FakeFloat:
            def __float__(self):
                return 0.5
        result = _json_dumps({"score": FakeFloat()})
        assert "0.5" in result
