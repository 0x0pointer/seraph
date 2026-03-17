"""Integration tests for /api/integrations endpoints (hook, litellm pre/post call).

The heavy scanner_engine functions are mocked so tests don't load ML models.
"""
import pytest
import httpx
from unittest.mock import AsyncMock, patch


def _get_proxy_client():
    from app.api.routes.integrations import _PROXY_CLIENT
    return _PROXY_CLIENT


def _clean_scan_result(text: str = "hello world"):
    return (True, text, {"Toxicity": 0.05}, [], {}, None, False)


def _blocked_scan_result(text: str = "bad content"):
    return (False, text, {"PromptInjection": 0.97}, ["PromptInjection"], {"PromptInjection": "blocked"}, None, False)


# ── Universal Hook tests ─────────────────────────────────────────────────────

class TestUniversalHook:
    def test_input_scan_allowed(self, client):
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=_clean_scan_result("safe prompt"),
        ):
            resp = client.post(
                "/api/integrations/hook",
                json={"text": "safe prompt", "direction": "input"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["sanitized_text"] == "safe prompt"

    def test_input_scan_blocked(self, client):
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=_blocked_scan_result("malicious input"),
        ):
            resp = client.post(
                "/api/integrations/hook",
                json={"text": "malicious input", "direction": "input"},
            )

        assert resp.status_code == 400
        data = resp.json()
        assert "PromptInjection" in data["detail"]

    def test_output_scan_allowed(self, client):
        with patch(
            "app.services.scanner_engine.run_output_scan",
            new_callable=AsyncMock,
            return_value=_clean_scan_result("helpful answer"),
        ):
            resp = client.post(
                "/api/integrations/hook",
                json={
                    "text": "helpful answer",
                    "direction": "output",
                    "prompt": "What is AI?",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["sanitized_text"] == "helpful answer"

    def test_empty_input_text_returns_allowed(self, client):
        resp = client.post(
            "/api/integrations/hook",
            json={"text": "", "direction": "input"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["detail"] == "No input text to scan"

    def test_empty_output_text_returns_allowed(self, client):
        resp = client.post(
            "/api/integrations/hook",
            json={"text": "", "direction": "output"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["detail"] == "No output text to scan"


# ── LiteLLM pre_call tests ───────────────────────────────────────────────────

class TestLiteLLMPreCall:
    def test_clean_message_allowed(self, client):
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=_clean_scan_result("What is Python?"),
        ):
            resp = client.post(
                "/api/integrations/litellm/pre_call",
                json={
                    "messages": [
                        {"role": "user", "content": "What is Python?"},
                    ],
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["sanitized_text"] == "What is Python?"

    def test_no_user_message_returns_allowed(self, client):
        resp = client.post(
            "/api/integrations/litellm/pre_call",
            json={
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                ],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["detail"] == "No user message to scan"


# ── LiteLLM post_call tests ──────────────────────────────────────────────────

class TestLiteLLMPostCall:
    def test_clean_response_allowed(self, client):
        with patch(
            "app.services.scanner_engine.run_output_scan",
            new_callable=AsyncMock,
            return_value=_clean_scan_result("Python is a programming language."),
        ):
            resp = client.post(
                "/api/integrations/litellm/post_call",
                json={
                    "messages": [
                        {"role": "user", "content": "What is Python?"},
                    ],
                    "response": {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "Python is a programming language.",
                                }
                            }
                        ]
                    },
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["sanitized_text"] == "Python is a programming language."

    def test_no_response_returns_allowed(self, client):
        resp = client.post(
            "/api/integrations/litellm/post_call",
            json={
                "messages": [
                    {"role": "user", "content": "Hello"},
                ],
                "response": None,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["detail"] == "No assistant response to scan"


# ── Helper function unit tests ────────────────────────────────────────────────

class TestHelperFunctions:
    def test_last_user_message_with_messages(self):
        from app.api.routes.integrations import _last_user_message, LiteLLMMessage

        messages = [
            LiteLLMMessage(role="system", content="Be helpful."),
            LiteLLMMessage(role="user", content="First question"),
            LiteLLMMessage(role="assistant", content="Answer"),
            LiteLLMMessage(role="user", content="Follow-up"),
        ]
        assert _last_user_message(messages) == "Follow-up"

    def test_last_user_message_empty_list(self):
        from app.api.routes.integrations import _last_user_message

        assert _last_user_message([]) == ""

    def test_assistant_reply_with_response_dict(self):
        from app.api.routes.integrations import _assistant_reply

        response = {
            "choices": [
                {"message": {"role": "assistant", "content": "Hello there!"}}
            ]
        }
        assert _assistant_reply(response) == "Hello there!"

    def test_assistant_reply_none(self):
        from app.api.routes.integrations import _assistant_reply

        assert _assistant_reply(None) == ""

    def test_assistant_reply_empty_dict(self):
        from app.api.routes.integrations import _assistant_reply

        assert _assistant_reply({}) == ""

    def test_assistant_reply_no_choices(self):
        from app.api.routes.integrations import _assistant_reply

        assert _assistant_reply({"choices": []}) == ""


# ── LiteLLM during_call tests ────────────────────────────────────────────────

class TestLiteLLMDuringCall:
    def test_during_call_clean_message(self, client):
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=_clean_scan_result("What is AI?"),
        ):
            resp = client.post(
                "/api/integrations/litellm/during_call",
                json={
                    "messages": [
                        {"role": "user", "content": "What is AI?"},
                    ],
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["sanitized_text"] == "What is AI?"

    def test_during_call_no_user_message(self, client):
        resp = client.post(
            "/api/integrations/litellm/during_call",
            json={
                "messages": [
                    {"role": "system", "content": "You are a bot."},
                ],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["detail"] == "No user message to scan"

    def test_during_call_blocked(self, client):
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=_blocked_scan_result("inject this"),
        ):
            resp = client.post(
                "/api/integrations/litellm/during_call",
                json={
                    "messages": [
                        {"role": "user", "content": "inject this"},
                    ],
                },
            )

        assert resp.status_code == 400
        assert "PromptInjection" in resp.json()["detail"]


# ── Transparent Proxy tests ──────────────────────────────────────────────────

class TestTransparentProxy:
    def test_proxy_missing_upstream_url_returns_400(self, client):
        """No X-Upstream-URL header and no config.upstream → 400."""
        from app.core.config import get_config
        config = get_config()
        saved = config.upstream
        config.upstream = ""
        try:
            resp = client.post(
                "/api/integrations/proxy",
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
                "/api/integrations/proxy/v1/chat/completions",
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
                "/api/integrations/proxy",
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
                "/api/integrations/proxy",
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
                "/api/integrations/proxy/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "my secret key=abc"}]},
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 200
        # Verify the forwarded body had the sanitized message
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
                "/api/integrations/proxy",
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
                "/api/integrations/proxy",
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
                "/api/integrations/proxy",
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
                "/api/integrations/proxy",
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
                "/api/integrations/proxy",
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
                "/api/integrations/proxy",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Upstream-URL": "https://api.openai.com"},
            )

        assert resp.status_code == 500
        assert "error" in resp.json()


# ── Reask context tests ─────────────────────────────────────────────────────

class TestReaskContext:
    def test_hook_reask_context_in_error_detail(self, client):
        """When reask_context is present, it appears in the 400 detail."""
        reask_result = (False, "bad", {"Scanner": 0.9}, ["Scanner"], {"Scanner": "reask"},
                        ["Please revise your message."], False)
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=reask_result,
        ):
            resp = client.post(
                "/api/integrations/hook",
                json={"text": "bad input", "direction": "input"},
            )

        assert resp.status_code == 400
        assert "revise" in resp.json()["detail"].lower()

    def test_output_hook_reask_context(self, client):
        """Reask context works for output direction too."""
        reask_result = (False, "bad output", {"Scanner": 0.9}, ["Scanner"], {"Scanner": "reask"},
                        ["Please revise your output."], False)
        with patch(
            "app.services.scanner_engine.run_output_scan",
            new_callable=AsyncMock,
            return_value=reask_result,
        ):
            resp = client.post(
                "/api/integrations/hook",
                json={"text": "bad output", "direction": "output", "prompt": "test"},
            )

        assert resp.status_code == 400
        assert "revise" in resp.json()["detail"].lower()


# ── _assistant_reply edge cases ──────────────────────────────────────────────

class TestAssistantReplyEdgeCases:
    def test_choices_with_missing_content_key(self):
        from app.api.routes.integrations import _assistant_reply
        response = {"choices": [{"message": {"role": "assistant"}}]}
        assert _assistant_reply(response) == ""

    def test_choices_with_none_message(self):
        from app.api.routes.integrations import _assistant_reply
        response = {"choices": [{"message": None}]}
        assert _assistant_reply(response) == ""

    def test_non_dict_response(self):
        from app.api.routes.integrations import _assistant_reply
        assert _assistant_reply("not a dict") == ""
