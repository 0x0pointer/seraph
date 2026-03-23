"""Tests for app/services/text_extractor.py — deep text segment extraction."""
import pytest
from app.services.text_extractor import (
    TextSegment,
    extract_request_segments,
    extract_response_segments,
    apply_segment_fix,
    _parse_source_path,
)


class TestExtractRequestSegments:
    def test_openai_simple(self):
        body = {"messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"},
        ]}
        segments = extract_request_segments(body)
        assert len(segments) == 2
        assert segments[0].role == "system"
        assert segments[0].text == "You are helpful."
        assert segments[1].role == "user"
        assert segments[1].text == "Hello!"

    def test_anthropic_content_blocks(self):
        body = {"messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "Hello from"},
                {"type": "image", "source": {"data": "..."}},
                {"type": "text", "text": "Anthropic!"},
            ]},
        ]}
        segments = extract_request_segments(body)
        texts = [s.text for s in segments]
        assert "Hello from" in texts
        assert "Anthropic!" in texts

    def test_anthropic_top_level_system_string(self):
        body = {
            "system": "You are Claude.",
            "messages": [{"role": "user", "content": "Hi"}],
        }
        segments = extract_request_segments(body)
        roles = [s.role for s in segments]
        assert "system" in roles
        system_seg = [s for s in segments if s.source == "system"][0]
        assert system_seg.text == "You are Claude."

    def test_anthropic_top_level_system_list(self):
        body = {
            "system": [
                {"type": "text", "text": "You are Claude."},
                {"type": "text", "text": "Be helpful."},
            ],
            "messages": [{"role": "user", "content": "Hi"}],
        }
        segments = extract_request_segments(body)
        system_segs = [s for s in segments if s.role == "system"]
        assert len(system_segs) == 2

    def test_tool_results(self):
        body = {"messages": [
            {"role": "user", "content": "search"},
            {"role": "tool", "tool_call_id": "call_1", "content": "Result data here"},
        ]}
        segments = extract_request_segments(body)
        tool_segs = [s for s in segments if s.role == "tool"]
        assert len(tool_segs) == 1
        assert tool_segs[0].text == "Result data here"

    def test_tool_calls_in_assistant(self):
        body = {"messages": [
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {
                    "name": "search", "arguments": '{"q":"test"}',
                }},
            ]},
        ]}
        segments = extract_request_segments(body)
        tc_segs = [s for s in segments if s.role == "tool_call"]
        assert len(tc_segs) == 1
        assert tc_segs[0].text == '{"q":"test"}'

    def test_tool_definitions(self):
        body = {
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search the web for information",
                },
            }],
        }
        segments = extract_request_segments(body)
        td_segs = [s for s in segments if s.role == "tool_definition"]
        assert len(td_segs) == 1
        assert td_segs[0].text == "Search the web for information"

    def test_legacy_functions_format(self):
        body = {
            "messages": [{"role": "user", "content": "hi"}],
            "functions": [{
                "name": "get_weather",
                "description": "Get the current weather",
            }],
        }
        segments = extract_request_segments(body)
        td_segs = [s for s in segments if s.role == "tool_definition"]
        assert len(td_segs) == 1
        assert "weather" in td_segs[0].text.lower()

    def test_empty_body(self):
        assert extract_request_segments({}) == []
        assert extract_request_segments({"messages": []}) == []

    def test_multi_turn_conversation(self):
        body = {"messages": [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]}
        segments = extract_request_segments(body)
        assert len(segments) == 4
        roles = [s.role for s in segments]
        assert roles == ["system", "user", "assistant", "user"]

    def test_content_hash_computed(self):
        body = {"messages": [{"role": "user", "content": "hello"}]}
        segments = extract_request_segments(body)
        assert segments[0].content_hash != ""
        assert len(segments[0].content_hash) == 64  # SHA256 hex

    def test_content_hash_deterministic(self):
        seg1 = TextSegment(text="hello", role="user", source="a")
        seg2 = TextSegment(text="hello", role="user", source="b")
        assert seg1.content_hash == seg2.content_hash

    def test_anthropic_tool_result_nested_content(self):
        body = {"messages": [
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": [
                    {"type": "text", "text": "Tool output here"},
                ]},
            ]},
        ]}
        segments = extract_request_segments(body)
        tool_segs = [s for s in segments if s.role == "tool"]
        assert len(tool_segs) == 1
        assert tool_segs[0].text == "Tool output here"


class TestExtractResponseSegments:
    def test_openai_format(self):
        body = {"choices": [{"message": {"role": "assistant", "content": "Hello!"}}]}
        segments = extract_response_segments(body)
        assert len(segments) == 1
        assert segments[0].role == "assistant"
        assert segments[0].text == "Hello!"

    def test_anthropic_format(self):
        body = {"content": [{"type": "text", "text": "Hello from Claude!"}]}
        segments = extract_response_segments(body)
        assert len(segments) == 1
        assert segments[0].text == "Hello from Claude!"

    def test_openai_tool_calls_in_response(self):
        body = {"choices": [{"message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "search", "arguments": '{"q":"test"}',
            }}],
        }}]}
        segments = extract_response_segments(body)
        tc_segs = [s for s in segments if s.role == "tool_call"]
        assert len(tc_segs) == 1

    def test_empty_response(self):
        assert extract_response_segments({}) == []
        assert extract_response_segments({"choices": []}) == []

    def test_empty_content(self):
        body = {"choices": [{"message": {"role": "assistant", "content": ""}}]}
        assert extract_response_segments(body) == []


class TestApplySegmentFix:
    def test_fix_openai_message_content(self):
        body = {"messages": [{"role": "user", "content": "secret=abc"}]}
        result = apply_segment_fix(body, "messages[0].content", "REDACTED")
        assert result["messages"][0]["content"] == "REDACTED"

    def test_fix_anthropic_content_block(self):
        body = {"messages": [{"role": "user", "content": [
            {"type": "text", "text": "secret"},
        ]}]}
        result = apply_segment_fix(body, "messages[0].content[0]", "REDACTED")
        assert result["messages"][0]["content"][0]["text"] == "REDACTED"

    def test_fix_response_content(self):
        body = {"choices": [{"message": {"content": "bad"}}]}
        result = apply_segment_fix(body, "choices[0].message.content", "good")
        assert result["choices"][0]["message"]["content"] == "good"

    def test_fix_anthropic_response(self):
        body = {"content": [{"type": "text", "text": "bad"}]}
        result = apply_segment_fix(body, "content[0]", "good")
        assert result["content"][0]["text"] == "good"

    def test_invalid_path_returns_unchanged(self):
        body = {"messages": []}
        result = apply_segment_fix(body, "messages[99].content", "x")
        assert result == body


class TestParseSourcePath:
    def test_simple_path(self):
        assert _parse_source_path("messages") == ["messages"]

    def test_dotted_path(self):
        assert _parse_source_path("choices[0].message.content") == [
            "choices", 0, "message", "content"
        ]

    def test_nested_indices(self):
        assert _parse_source_path("messages[2].content[0]") == [
            "messages", 2, "content", 0
        ]

    def test_top_level_key(self):
        assert _parse_source_path("system") == ["system"]
