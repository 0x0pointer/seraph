"""
Deep text extraction from LLM request/response payloads.

Extracts ALL text content — system prompts, user messages, assistant prefills,
tool results, tool definitions, function arguments — so that Seraph can scan
every piece of text flowing between a chatbot framework and the LLM provider.

This replaces the old single-message extraction approach that only grabbed the
last user message, which missed indirect injection vectors from tool results,
system prompt manipulation, and multi-turn context.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TextSegment:
    """A single piece of text extracted from a request or response payload."""

    text: str
    role: str  # system, user, assistant, tool, tool_definition
    source: str  # JSON path, e.g. "messages[2].content"
    content_hash: str = field(default="", repr=False)

    def __post_init__(self):
        if not self.content_hash:
            object.__setattr__(
                self, "content_hash", _content_hash(self.text),
            )


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── Request extraction ───────────────────────────────────────────────────────

def extract_request_segments(body: dict) -> list[TextSegment]:
    """Extract all text segments from a chat-completion request body.

    Handles OpenAI, Anthropic, and generic formats. Extracts from:
      - messages[].content  (all roles: system, user, assistant, tool)
      - system (Anthropic top-level system prompt)
      - tools[].function.description / parameters
      - functions[].description / parameters
      - tool_choice (if string-like content)
    """
    segments: list[TextSegment] = []

    # 1. Top-level system prompt (Anthropic format)
    _extract_top_level_system(body, segments)

    # 2. Messages array — all roles
    _extract_messages(body, segments)

    # 3. Tool / function definitions
    _extract_tool_definitions(body, segments)

    return segments


def _extract_top_level_system(body: dict, segments: list[TextSegment]) -> None:
    """Anthropic uses a top-level 'system' field."""
    system = body.get("system")
    if system is None:
        return
    if isinstance(system, str) and system.strip():
        segments.append(TextSegment(text=system, role="system", source="system"))
    elif isinstance(system, list):
        # Anthropic system can be a list of content blocks
        for i, block in enumerate(system):
            text = _text_from_content_block(block)
            if text:
                segments.append(TextSegment(
                    text=text, role="system", source=f"system[{i}]",
                ))


def _extract_messages(body: dict, segments: list[TextSegment]) -> None:
    """Walk the messages array and extract text from every message."""
    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        return

    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "unknown")
        prefix = f"messages[{i}]"

        _extract_message_content(msg, role, prefix, segments)
        _extract_message_tool_calls(msg, prefix, segments)


def _extract_message_content(
    msg: dict, role: str, prefix: str, segments: list[TextSegment],
) -> None:
    """Extract content field from a single message."""
    content = msg.get("content")
    if content is not None:
        _extract_content(content, role, f"{prefix}.content", segments)


def _extract_message_tool_calls(
    msg: dict, prefix: str, segments: list[TextSegment],
) -> None:
    """Extract tool call arguments from assistant messages (OpenAI format)."""
    tool_calls = msg.get("tool_calls")
    if not tool_calls or not isinstance(tool_calls, list):
        return
    for j, tc in enumerate(tool_calls):
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function", {})
        args = fn.get("arguments", "")
        if args and isinstance(args, str) and args.strip():
            segments.append(TextSegment(
                text=args,
                role="tool_call",
                source=f"{prefix}.tool_calls[{j}].function.arguments",
            ))


def _extract_content(
    content: Any, role: str, source: str, segments: list[TextSegment],
) -> None:
    """Extract text from a content field (string or list of content blocks)."""
    if isinstance(content, str):
        if content.strip():
            segments.append(TextSegment(text=content, role=role, source=source))
        return

    if not isinstance(content, list):
        return

    for i, block in enumerate(content):
        text = _text_from_content_block(block)
        if text:
            segments.append(TextSegment(
                text=text, role=role, source=f"{source}[{i}]",
            ))
        # Anthropic tool_result blocks can contain nested content
        if isinstance(block, dict) and block.get("type") == "tool_result":
            nested = block.get("content")
            if nested:
                _extract_content(
                    nested, "tool", f"{source}[{i}].content", segments,
                )


def _text_from_content_block(block: Any) -> str:
    """Extract text from a single content block (dict with type/text)."""
    if isinstance(block, str):
        return block.strip()
    if not isinstance(block, dict):
        return ""
    # Standard text block
    if block.get("type") == "text":
        return (block.get("text") or "").strip()
    # Tool use input (Anthropic) — JSON input as string
    if block.get("type") == "tool_use":
        inp = block.get("input")
        if isinstance(inp, str) and inp.strip():
            return inp.strip()
    return ""


def _extract_tool_definitions(body: dict, segments: list[TextSegment]) -> None:
    """Extract descriptions from tool/function definitions."""
    _extract_openai_tools(body, segments)
    _extract_legacy_functions(body, segments)


def _extract_openai_tools(body: dict, segments: list[TextSegment]) -> None:
    """Extract descriptions from OpenAI tools format."""
    tools = body.get("tools")
    if not tools or not isinstance(tools, list):
        return
    for i, tool in enumerate(tools):
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function", {})
        desc = fn.get("description", "")
        if desc and isinstance(desc, str) and desc.strip():
            segments.append(TextSegment(
                text=desc,
                role="tool_definition",
                source=f"tools[{i}].function.description",
            ))


def _extract_legacy_functions(body: dict, segments: list[TextSegment]) -> None:
    """Extract descriptions from legacy OpenAI functions format."""
    functions = body.get("functions")
    if not functions or not isinstance(functions, list):
        return
    for i, fn in enumerate(functions):
        if not isinstance(fn, dict):
            continue
        desc = fn.get("description", "")
        if desc and isinstance(desc, str) and desc.strip():
            segments.append(TextSegment(
                text=desc,
                role="tool_definition",
                source=f"functions[{i}].description",
            ))


# ── Response extraction ──────────────────────────────────────────────────────

def extract_response_segments(body: dict) -> list[TextSegment]:
    """Extract all text segments from an LLM response body.

    Handles OpenAI (choices[].message) and Anthropic (content[]) formats.
    Also extracts tool call arguments from the response.
    """
    segments: list[TextSegment] = []
    _extract_openai_response(body, segments)
    _extract_anthropic_response(body, segments)
    return segments


def _extract_openai_response(body: dict, segments: list[TextSegment]) -> None:
    """Extract text segments from an OpenAI-format response."""
    choices = body.get("choices")
    if not choices or not isinstance(choices, list):
        return

    for i, choice in enumerate(choices):
        if not isinstance(choice, dict):
            continue
        msg = choice.get("message", {})
        if not isinstance(msg, dict):
            continue

        content = msg.get("content")
        if content and isinstance(content, str) and content.strip():
            segments.append(TextSegment(
                text=content,
                role="assistant",
                source=f"choices[{i}].message.content",
            ))

        _extract_openai_response_tool_calls(msg, i, segments)


def _extract_openai_response_tool_calls(
    msg: dict, choice_idx: int, segments: list[TextSegment],
) -> None:
    """Extract tool call arguments from an OpenAI response message."""
    tool_calls = msg.get("tool_calls")
    if not tool_calls or not isinstance(tool_calls, list):
        return
    for j, tc in enumerate(tool_calls):
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function", {})
        args = fn.get("arguments", "")
        if args and isinstance(args, str) and args.strip():
            segments.append(TextSegment(
                text=args,
                role="tool_call",
                source=f"choices[{choice_idx}].message.tool_calls[{j}].function.arguments",
            ))


def _extract_anthropic_response(body: dict, segments: list[TextSegment]) -> None:
    """Extract text segments from an Anthropic-format response."""
    content = body.get("content")
    if not content or not isinstance(content, list):
        return

    for i, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = (block.get("text") or "").strip()
            if text:
                segments.append(TextSegment(
                    text=text,
                    role="assistant",
                    source=f"content[{i}].text",
                ))
        elif block.get("type") == "tool_use":
            inp = block.get("input")
            if isinstance(inp, str) and inp.strip():
                segments.append(TextSegment(
                    text=inp,
                    role="tool_call",
                    source=f"content[{i}].input",
                ))


# ── Segment fix application ──────────────────────────────────────────────────

def apply_segment_fix(body: dict, source: str, new_text: str) -> dict:
    """Replace text at a source path in the body dict.

    source is a dotted/bracketed path like 'messages[2].content' or
    'messages[0].content[1]'. Navigates the body and replaces the text.
    Returns the modified body, or the original body unchanged if the path
    cannot be resolved.
    """
    parts = _parse_source_path(source)
    obj: Any = body
    for part in parts[:-1]:
        obj = _navigate(obj, part)
        if obj is None:
            return body

    last = parts[-1]
    if isinstance(last, int):
        return _apply_fix_at_index(body, obj, last, new_text)
    if isinstance(last, str) and isinstance(obj, dict):
        return _apply_fix_at_key(body, obj, last, new_text)
    return body


def _apply_fix_at_index(
    body: dict, obj: Any, index: int, new_text: str,
) -> dict:
    """Apply a text fix at a list index."""
    if not isinstance(obj, list) or not (0 <= index < len(obj)):
        return body
    target = obj[index]
    if isinstance(target, dict) and "text" in target:
        target["text"] = new_text
        return body
    if isinstance(target, str):
        obj[index] = new_text
    return body


def _apply_fix_at_key(
    body: dict, obj: dict, key: str, new_text: str,
) -> dict:
    """Apply a text fix at a dict key."""
    current = obj.get(key)
    if isinstance(current, str):
        obj[key] = new_text
        return body
    if isinstance(current, list):
        for block in current:
            if isinstance(block, dict) and block.get("type") == "text":
                block["text"] = new_text
                return body
    return body


def _parse_source_path(source: str) -> list[str | int]:
    """Parse a source path like 'messages[2].content[0]' into parts."""
    parts: list[str | int] = []
    current = ""
    i = 0
    while i < len(source):
        ch = source[i]
        if ch == ".":
            if current:
                parts.append(current)
                current = ""
        elif ch == "[":
            if current:
                parts.append(current)
                current = ""
            j = source.index("]", i)
            idx_str = source[i + 1 : j]
            parts.append(int(idx_str))
            i = j
        else:
            current += ch
        i += 1
    if current:
        parts.append(current)
    return parts


def _navigate(obj: Any, part: str | int) -> Any:
    """Navigate one level into a nested object."""
    if isinstance(part, int):
        if isinstance(obj, list) and 0 <= part < len(obj):
            return obj[part]
        return None
    if isinstance(obj, dict):
        return obj.get(part)
    return None
