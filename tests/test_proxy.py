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
    """Return a GuardState representing a clean (allowed) scan."""
    return {
        "raw_text": text, "direction": "input", "prompt_context": "",
        "scanner_results": {"Toxicity": 0.05}, "violations": [],
        "on_fail_actions": {}, "sanitized_text": text,
        "blocked": False, "block_reason": None, "nemo_risk_score": 0.0,
    }


def _blocked_scan_result(text: str = "bad content"):
    """Return a GuardState representing a blocked scan."""
    return {
        "raw_text": text, "direction": "input", "prompt_context": "",
        "scanner_results": {"PromptInjection": 0.97},
        "violations": ["PromptInjection"],
        "on_fail_actions": {"PromptInjection": "blocked"},
        "sanitized_text": text,
        "blocked": True, "block_reason": "Request blocked by guardrail(s): PromptInjection",
        "nemo_risk_score": 0.97,
    }


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
        fixed_result = {
            "raw_text": "my secret key=abc", "direction": "input", "prompt_context": "",
            "scanner_results": {"Secrets": 0.99}, "violations": [],
            "on_fail_actions": {"Secrets": "fixed"}, "sanitized_text": "REDACTED",
            "blocked": False, "block_reason": None, "nemo_risk_score": 0.0,
        }
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
        output_fixed = {
            "raw_text": "leak secret=xyz", "direction": "output", "prompt_context": "hi",
            "scanner_results": {"Secrets": 0.99}, "violations": [],
            "on_fail_actions": {"Secrets": "fixed"}, "sanitized_text": "leak secret=[REDACTED]",
            "blocked": False, "block_reason": None, "nemo_risk_score": 0.0,
        }

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
        """When block_reason is set, it appears in the 400 detail."""
        reask_result = {
            "raw_text": "bad input", "direction": "input", "prompt_context": "",
            "scanner_results": {"Scanner": 0.9}, "violations": ["Scanner"],
            "on_fail_actions": {"Scanner": "blocked"}, "sanitized_text": "bad input",
            "blocked": True, "block_reason": "Please revise your message.",
            "nemo_risk_score": 0.9,
        }
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
        output_fixed = {
            "raw_text": "secret=abc123", "direction": "output", "prompt_context": "hi",
            "scanner_results": {"Secrets": 0.99}, "violations": [],
            "on_fail_actions": {"Secrets": "fixed"}, "sanitized_text": "secret=[REDACTED]",
            "blocked": False, "block_reason": None, "nemo_risk_score": 0.0,
        }

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
        fixed_result = {
            "raw_text": "my secret", "direction": "input", "prompt_context": "",
            "scanner_results": {"Secrets": 0.99}, "violations": [],
            "on_fail_actions": {"Secrets": "fixed"}, "sanitized_text": "REDACTED",
            "blocked": False, "block_reason": None, "nemo_risk_score": 0.0,
        }
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
    def test_streaming_request_scans_output_in_buffer_mode(self, client):
        """Streaming requests scan output in buffer mode (default)."""
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
                return_value=_clean_scan_result("hi"),
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
        # In buffer mode, output IS scanned
        mock_output.assert_called_once()

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

class TestResolveUpstreamAuth:
    def test_config_key_takes_priority(self):
        from app.api.routes.proxy import _resolve_upstream_auth
        from unittest.mock import MagicMock
        config = MagicMock()
        config.upstream_api_key = "sk-from-config"
        result = _resolve_upstream_auth(config, "Bearer sk-from-header")
        assert result == "Bearer sk-from-config"

    def test_falls_back_to_header(self):
        from app.api.routes.proxy import _resolve_upstream_auth
        from unittest.mock import MagicMock
        config = MagicMock()
        config.upstream_api_key = ""
        result = _resolve_upstream_auth(config, "Bearer sk-from-header")
        assert result == "Bearer sk-from-header"

    def test_returns_none_when_no_key(self):
        from app.api.routes.proxy import _resolve_upstream_auth
        from unittest.mock import MagicMock
        config = MagicMock()
        config.upstream_api_key = ""
        result = _resolve_upstream_auth(config, None)
        assert result is None

    def test_config_key_used_in_proxy(self, client):
        """When upstream_api_key is set in config, it's used as Authorization."""
        from app.core.config import get_config
        config = get_config()
        saved = config.upstream_api_key
        config.upstream_api_key = "sk-server-side-key"

        upstream_response = httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]},
        )

        try:
            with (
                patch(
                    "app.services.scanner_engine.run_input_scan",
                    new_callable=AsyncMock,
                    return_value=_clean_scan_result("hi"),
                ),
                patch(
                    "app.services.scanner_engine.run_output_scan",
                    new_callable=AsyncMock,
                    return_value=_clean_scan_result("hi"),
                ),
                patch.object(
                    _get_proxy_client(), "post",
                    new_callable=AsyncMock,
                    return_value=upstream_response,
                ) as mock_post,
            ):
                client.post(
                    "/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": "hi"}]},
                    headers={"X-Upstream-URL": "https://api.openai.com"},
                )

            forwarded_headers = mock_post.call_args.kwargs.get("headers", {})
            assert forwarded_headers["Authorization"] == "Bearer sk-server-side-key"
        finally:
            config.upstream_api_key = saved


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
        monitored_result = {
            "raw_text": "hi", "direction": "input", "prompt_context": "",
            "scanner_results": {"Toxicity": 0.6}, "violations": [],
            "on_fail_actions": {"Toxicity": "monitored"}, "sanitized_text": "hi",
            "blocked": False, "block_reason": None, "nemo_risk_score": 0.0,
        }
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
