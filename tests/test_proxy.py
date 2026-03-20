"""Tests for the transparent proxy (the sole integration pattern).

The heavy scanner_engine functions are mocked so tests don't load ML models.
"""
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch


def _get_proxy_client():
    from app.api.routes.proxy import _PROXY_CLIENT
    return _PROXY_CLIENT


def _clean_scan_result(text: str = "hello world"):
    return (True, text, {"Toxicity": 0.05}, [], {}, None, False)


def _blocked_scan_result(text: str = "bad content"):
    return (False, text, {"PromptInjection": 0.97}, ["PromptInjection"], {"PromptInjection": "blocked"}, None, False)


# ── Message extraction tests ────────────────────────────────────────────────

class TestMessageExtraction:
    def test_extract_openai_format(self):
        from app.api.routes.proxy import _extract_user_text
        body = {"messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"},
        ]}
        assert _extract_user_text(body) == "Hello!"

    def test_extract_anthropic_format(self):
        from app.api.routes.proxy import _extract_user_text
        body = {"messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "Hello from"},
                {"type": "text", "text": "Anthropic!"},
            ]},
        ]}
        assert _extract_user_text(body) == "Hello from Anthropic!"

    def test_extract_anthropic_with_image_blocks(self):
        from app.api.routes.proxy import _extract_user_text
        body = {"messages": [
            {"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "data": "..."}},
                {"type": "text", "text": "What is this?"},
            ]},
        ]}
        assert _extract_user_text(body) == "What is this?"

    def test_extract_empty_messages(self):
        from app.api.routes.proxy import _extract_user_text
        assert _extract_user_text({"messages": []}) == ""
        assert _extract_user_text({}) == ""

    def test_extract_no_user_message(self):
        from app.api.routes.proxy import _extract_user_text
        body = {"messages": [{"role": "system", "content": "You are a bot."}]}
        assert _extract_user_text(body) == ""

    def test_extract_last_user_message(self):
        from app.api.routes.proxy import _extract_user_text
        body = {"messages": [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]}
        assert _extract_user_text(body) == "second"


class TestAssistantExtraction:
    def test_openai_format(self):
        from app.api.routes.proxy import _extract_assistant_text
        body = {"choices": [{"message": {"role": "assistant", "content": "Hello!"}}]}
        assert _extract_assistant_text(body) == "Hello!"

    def test_anthropic_format(self):
        from app.api.routes.proxy import _extract_assistant_text
        body = {"content": [{"type": "text", "text": "Hello from Claude!"}]}
        assert _extract_assistant_text(body) == "Hello from Claude!"

    def test_empty_choices(self):
        from app.api.routes.proxy import _extract_assistant_text
        assert _extract_assistant_text({"choices": []}) == ""

    def test_none_response(self):
        from app.api.routes.proxy import _extract_assistant_text
        assert _extract_assistant_text({}) == ""

    def test_missing_content_key(self):
        from app.api.routes.proxy import _extract_assistant_text
        body = {"choices": [{"message": {"role": "assistant"}}]}
        assert _extract_assistant_text(body) == ""

    def test_none_message(self):
        from app.api.routes.proxy import _extract_assistant_text
        body = {"choices": [{"message": None}]}
        assert _extract_assistant_text(body) == ""


class TestDetectApiFormat:
    def test_openai(self):
        from app.api.routes.proxy import _detect_api_format
        assert _detect_api_format({"messages": [{"role": "user", "content": "hi"}]}) == "openai"

    def test_anthropic(self):
        from app.api.routes.proxy import _detect_api_format
        body = {"messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]}
        assert _detect_api_format(body) == "anthropic"

    def test_unknown_no_messages(self):
        from app.api.routes.proxy import _detect_api_format
        assert _detect_api_format({}) == "unknown"

    def test_unknown_empty_messages(self):
        from app.api.routes.proxy import _detect_api_format
        assert _detect_api_format({"messages": []}) == "unknown"


# ── Transparent Proxy tests ──────────────────────────────────────────────────

class TestTransparentProxy:
    def test_proxy_missing_upstream_url_returns_400(self, client):
        """No X-Upstream-URL header and no config.upstream -> 400."""
        from app.core.config import get_config
        config = get_config()
        saved = config.upstream
        config.upstream = ""
        try:
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )
            assert resp.status_code == 400
            assert "upstream" in resp.json()["detail"].lower()
        finally:
            config.upstream = saved

    def test_proxy_forwards_and_returns(self, client):
        upstream_response = httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "Hello!"}}
                ]
            },
        )

        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("hi"),
            ),
            patch(
                "app.services.scanner_engine.run_output_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("Hello!"),
            ),
            patch.object(
                _get_proxy_client(), "post",
                new_callable=AsyncMock,
                return_value=upstream_response,
            ),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={
                    "X-Upstream-URL": "https://api.openai.com",
                    "X-Upstream-Auth": "Bearer sk-fake",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Hello!"

    def test_proxy_upstream_error_relayed(self, client):
        upstream_response = httpx.Response(
            429,
            json={"error": "rate limited"},
        )

        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("hi"),
            ),
            patch.object(
                _get_proxy_client(), "post",
                new_callable=AsyncMock,
                return_value=upstream_response,
            ),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={
                    "X-Upstream-URL": "https://api.openai.com",
                },
            )

        assert resp.status_code == 429

    def test_proxy_upstream_unreachable_returns_502(self, client):
        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("hi"),
            ),
            patch.object(
                _get_proxy_client(), "post",
                new_callable=AsyncMock,
                side_effect=httpx.ConnectError("Connection refused"),
            ),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={
                    "X-Upstream-URL": "https://api.openai.com",
                },
            )

        assert resp.status_code == 502
        assert "Upstream LLM unreachable" in resp.json()["detail"]

    def test_proxy_input_sanitization_replaces_message(self, client):
        """When input scan applies a fix, the sanitized text replaces the user message."""
        fixed_result = (True, "REDACTED", {"Secrets": 0.99}, [], {"Secrets": "fixed"}, None, True)
        upstream_response = httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "Got it."}}]},
        )

        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=fixed_result,
            ),
            patch(
                "app.services.scanner_engine.run_output_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("Got it."),
            ),
            patch.object(
                _get_proxy_client(), "post",
                new_callable=AsyncMock,
                return_value=upstream_response,
            ) as mock_post,
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "my secret key=abc"}]},
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 200
        forwarded_body = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert forwarded_body["messages"][0]["content"] == "REDACTED"

    def test_proxy_output_sanitization_replaces_content(self, client):
        """When output scan applies a fix, the response content is replaced."""
        upstream_response = httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "leak secret=xyz"}}]},
        )
        output_fixed = (True, "leak secret=[REDACTED]", {"Secrets": 0.99}, [], {"Secrets": "fixed"}, None, True)

        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("hi"),
            ),
            patch(
                "app.services.scanner_engine.run_output_scan",
                new_callable=AsyncMock,
                return_value=output_fixed,
            ),
            patch.object(
                _get_proxy_client(), "post",
                new_callable=AsyncMock,
                return_value=upstream_response,
            ),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "leak secret=[REDACTED]"

    def test_proxy_non_json_upstream_response_returns_502(self, client):
        """When upstream returns non-JSON, proxy returns 502."""
        upstream_response = httpx.Response(200, text="not json", headers={"content-type": "text/plain"})

        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("hi"),
            ),
            patch.object(
                _get_proxy_client(), "post",
                new_callable=AsyncMock,
                return_value=upstream_response,
            ),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 502
        assert "Non-JSON" in resp.json()["error"]

    def test_proxy_input_blocked_returns_400(self, client):
        """When input scan blocks, proxy returns 400 without forwarding."""
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=_blocked_scan_result("malicious"),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "malicious"}]},
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 400
        assert "PromptInjection" in resp.json()["detail"]

    def test_proxy_no_messages_skips_input_scan(self, client):
        """When there are no messages, input scan is skipped."""
        upstream_response = httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]},
        )

        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
            ) as mock_input,
            patch(
                "app.services.scanner_engine.run_output_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("hi"),
            ),
            patch.object(
                _get_proxy_client(), "post",
                new_callable=AsyncMock,
                return_value=upstream_response,
            ),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": []},
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 200
        mock_input.assert_not_called()

    def test_proxy_no_assistant_content_skips_output_scan(self, client):
        """When upstream has no assistant content, output scan is skipped."""
        upstream_response = httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": ""}}]},
        )

        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("hi"),
            ),
            patch(
                "app.services.scanner_engine.run_output_scan",
                new_callable=AsyncMock,
            ) as mock_output,
            patch.object(
                _get_proxy_client(), "post",
                new_callable=AsyncMock,
                return_value=upstream_response,
            ),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 200
        mock_output.assert_not_called()

    def test_proxy_upstream_non_200_error_relayed_non_json(self, client):
        """When upstream returns non-200 with non-JSON body, error text is relayed."""
        upstream_response = httpx.Response(500, text="Internal Server Error")

        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("hi"),
            ),
            patch.object(
                _get_proxy_client(), "post",
                new_callable=AsyncMock,
                return_value=upstream_response,
            ),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 500
        assert "error" in resp.json()


# ── Reask context tests ──────────────────────────────────────────────────────

class TestReaskContext:
    def test_proxy_reask_context_in_error_detail(self, client):
        """When reask_context is present, it appears in the 400 detail."""
        reask_result = (False, "bad", {"Scanner": 0.9}, ["Scanner"], {"Scanner": "reask"},
                        ["Please revise your message."], False)
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=reask_result,
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "bad input"}]},
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 400
        assert "revise" in resp.json()["detail"].lower()


# ── Anthropic proxy integration tests ────────────────────────────────────────

class TestAnthropicProxy:
    def test_anthropic_input_scanned(self, client):
        """Anthropic-format messages are correctly extracted and scanned."""
        upstream_response = httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "Hello from Claude!"}]},
        )

        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("Hello!"),
            ) as mock_input,
            patch(
                "app.services.scanner_engine.run_output_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("Hello from Claude!"),
            ),
            patch.object(
                _get_proxy_client(), "post",
                new_callable=AsyncMock,
                return_value=upstream_response,
            ),
        ):
            resp = client.post(
                "/v1/messages",
                json={"messages": [
                    {"role": "user", "content": [{"type": "text", "text": "Hello!"}]},
                ]},
                headers={"X-Upstream-URL": "https://api.anthropic.com"},
            )

        assert resp.status_code == 200
        mock_input.assert_called_once_with("Hello!")
        assert resp.json()["content"][0]["text"] == "Hello from Claude!"

    def test_anthropic_output_sanitization(self, client):
        """Anthropic-format output is sanitized correctly."""
        upstream_response = httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "secret=abc123"}]},
        )
        output_fixed = (True, "secret=[REDACTED]", {"Secrets": 0.99}, [], {"Secrets": "fixed"}, None, True)

        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("hi"),
            ),
            patch(
                "app.services.scanner_engine.run_output_scan",
                new_callable=AsyncMock,
                return_value=output_fixed,
            ),
            patch.object(
                _get_proxy_client(), "post",
                new_callable=AsyncMock,
                return_value=upstream_response,
            ),
        ):
            resp = client.post(
                "/v1/messages",
                json={"messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                ]},
                headers={"X-Upstream-URL": "https://api.anthropic.com"},
            )

        assert resp.status_code == 200
        assert resp.json()["content"][0]["text"] == "secret=[REDACTED]"

    def test_anthropic_input_fix_replaces_blocks(self, client):
        """When input fix is applied on Anthropic format, content blocks are replaced."""
        fixed_result = (True, "REDACTED", {"Secrets": 0.99}, [], {"Secrets": "fixed"}, None, True)
        upstream_response = httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "Got it."}]},
        )

        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=fixed_result,
            ),
            patch(
                "app.services.scanner_engine.run_output_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("Got it."),
            ),
            patch.object(
                _get_proxy_client(), "post",
                new_callable=AsyncMock,
                return_value=upstream_response,
            ) as mock_post,
        ):
            resp = client.post(
                "/v1/messages",
                json={"messages": [
                    {"role": "user", "content": [{"type": "text", "text": "my secret"}]},
                ]},
                headers={"X-Upstream-URL": "https://api.anthropic.com"},
            )

        assert resp.status_code == 200
        forwarded_body = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert forwarded_body["messages"][0]["content"] == [{"type": "text", "text": "REDACTED"}]


# ── Non-POST pass-through tests ──────────────────────────────────────────────

class TestNonPostPassthrough:
    def test_get_request_forwarded(self, client):
        """GET requests are forwarded without scanning."""
        upstream_response = httpx.Response(
            200,
            json={"data": [{"id": "gpt-4"}]},
        )

        with patch.object(
            _get_proxy_client(), "request",
            new_callable=AsyncMock,
            return_value=upstream_response,
        ) as mock_req:
            resp = client.get(
                "/v1/models",
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 200
        assert resp.json()["data"][0]["id"] == "gpt-4"
        mock_req.assert_called_once()

    def test_get_request_non_json_response(self, client):
        """GET with non-JSON upstream response returns error text."""
        upstream_response = httpx.Response(200, text="plain text", headers={"content-type": "text/plain"})

        with patch.object(
            _get_proxy_client(), "request",
            new_callable=AsyncMock,
            return_value=upstream_response,
        ):
            resp = client.get(
                "/v1/models",
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_get_request_upstream_unreachable(self, client):
        """GET with unreachable upstream returns 502."""
        with patch.object(
            _get_proxy_client(), "request",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            resp = client.get(
                "/v1/models",
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 502

    def test_get_forwards_upstream_auth(self, client):
        """GET requests forward X-Upstream-Auth as Authorization."""
        upstream_response = httpx.Response(200, json={"ok": True})

        with patch.object(
            _get_proxy_client(), "request",
            new_callable=AsyncMock,
            return_value=upstream_response,
        ) as mock_req:
            client.get(
                "/v1/models",
                headers={
                    "X-Upstream-URL": "https://api.openai.com",
                    "X-Upstream-Auth": "Bearer sk-test",
                },
            )

        call_kwargs = mock_req.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer sk-test"


# ── Streaming tests ──────────────────────────────────────────────────────────

class TestStreaming:
    def test_streaming_request_passes_through(self, client):
        """Streaming requests do input scan but skip output scan."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/event-stream"}

        async def mock_aiter_bytes():
            yield b"data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}\n\n"
            yield b"data: [DONE]\n\n"

        mock_resp.aiter_bytes = mock_aiter_bytes
        mock_resp.aclose = AsyncMock()

        mock_send = AsyncMock(return_value=mock_resp)

        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("hello"),
            ) as mock_input,
            patch(
                "app.services.scanner_engine.run_output_scan",
                new_callable=AsyncMock,
            ) as mock_output,
            patch.object(_get_proxy_client(), "send", mock_send),
            patch.object(_get_proxy_client(), "build_request", return_value=MagicMock()),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 200
        mock_input.assert_called_once()
        mock_output.assert_not_called()

    def test_streaming_upstream_unreachable(self, client):
        """Streaming with unreachable upstream returns 502."""
        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("hello"),
            ),
            patch.object(
                _get_proxy_client(), "build_request",
                return_value=MagicMock(),
            ),
            patch.object(
                _get_proxy_client(), "send",
                new_callable=AsyncMock,
                side_effect=httpx.ConnectError("Connection refused"),
            ),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 502


# ── Helper function tests ────────────────────────────────────────────────────

class TestBuildForwardUrl:
    def test_with_path(self):
        from app.api.routes.proxy import _build_forward_url
        assert _build_forward_url("https://api.openai.com", "v1/chat/completions") == \
            "https://api.openai.com/v1/chat/completions"

    def test_without_path(self):
        from app.api.routes.proxy import _build_forward_url
        assert _build_forward_url("https://api.openai.com/", "") == "https://api.openai.com"

    def test_strips_leading_slash(self):
        from app.api.routes.proxy import _build_forward_url
        assert _build_forward_url("https://api.openai.com", "/v1/models") == \
            "https://api.openai.com/v1/models"


class TestApplyOutputFix:
    def test_openai_format(self):
        from app.api.routes.proxy import _apply_output_fix
        body = {"choices": [{"message": {"content": "old"}}]}
        result = _apply_output_fix(body, "new")
        assert result["choices"][0]["message"]["content"] == "new"

    def test_anthropic_format(self):
        from app.api.routes.proxy import _apply_output_fix
        body = {"content": [{"type": "text", "text": "old"}]}
        result = _apply_output_fix(body, "new")
        assert result["content"][0]["text"] == "new"

    def test_unknown_format_returns_unchanged(self):
        from app.api.routes.proxy import _apply_output_fix
        body = {"result": "something"}
        result = _apply_output_fix(body, "new")
        assert result == {"result": "something"}


class TestApplyInputFix:
    def test_openai_format(self):
        from app.api.routes.proxy import _apply_input_fix
        body = {"messages": [{"role": "user", "content": "old"}]}
        result = _apply_input_fix(body, "new")
        assert result["messages"][0]["content"] == "new"

    def test_no_user_message(self):
        from app.api.routes.proxy import _apply_input_fix
        body = {"messages": [{"role": "system", "content": "be helpful"}]}
        result = _apply_input_fix(body, "new")
        assert result["messages"][0]["content"] == "be helpful"


# ── Edge case tests ──────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_invalid_json_body_returns_400(self, client):
        """POST with invalid JSON returns 400."""
        resp = client.post(
            "/v1/chat/completions",
            content=b"not json",
            headers={
                "Content-Type": "application/json",
                "X-Upstream-URL": "https://api.openai.com",
            },
        )
        assert resp.status_code == 400
        assert "JSON" in resp.json()["detail"]

    def test_output_blocked_returns_400(self, client):
        """When output scan blocks, proxy returns 400."""
        upstream_response = httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "toxic output"}}]},
        )

        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("hi"),
            ),
            patch(
                "app.services.scanner_engine.run_output_scan",
                new_callable=AsyncMock,
                return_value=_blocked_scan_result("toxic output"),
            ),
            patch.object(
                _get_proxy_client(), "post",
                new_callable=AsyncMock,
                return_value=upstream_response,
            ),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 400
        assert "PromptInjection" in resp.json()["detail"]

    def test_monitored_scanner_allowed_through(self, client):
        """Monitored violations are logged but allowed."""
        monitored_result = (True, "hi", {"Toxicity": 0.6}, [], {"Toxicity": "monitored"}, None, False)
        upstream_response = httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )

        with (
            patch(
                "app.services.scanner_engine.run_input_scan",
                new_callable=AsyncMock,
                return_value=monitored_result,
            ),
            patch(
                "app.services.scanner_engine.run_output_scan",
                new_callable=AsyncMock,
                return_value=_clean_scan_result("ok"),
            ),
            patch.object(
                _get_proxy_client(), "post",
                new_callable=AsyncMock,
                return_value=upstream_response,
            ),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 200
