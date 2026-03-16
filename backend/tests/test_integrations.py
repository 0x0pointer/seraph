"""Integration tests for /api/integrations endpoints (hook, litellm pre/post call).

The heavy scanner_engine functions are mocked so tests don't load ML models.
"""
import pytest
import httpx
from unittest.mock import AsyncMock, patch


def _get_proxy_client():
    """Return the module-level _PROXY_CLIENT from integrations so we can mock it."""
    from app.api.routes.integrations import _PROXY_CLIENT
    return _PROXY_CLIENT


# ── Scan return-value helpers ─────────────────────────────────────────────────

def _clean_scan_result(text: str = "hello world"):
    """Simulate a scan that passes all checks."""
    return (
        True,           # is_valid
        text,           # sanitized_text (unchanged)
        {"Toxicity": 0.05},  # scanner_results
        [],             # violations
        {},             # on_fail_actions
        None,           # reask_context
        False,          # fix_applied
    )


def _blocked_scan_result(text: str = "bad content"):
    """Simulate a scan that blocks the request."""
    return (
        False,
        text,
        {"PromptInjection": 0.97},
        ["PromptInjection"],
        {"PromptInjection": "blocked"},
        None,
        False,
    )


# ── Universal Hook tests ─────────────────────────────────────────────────────

class TestUniversalHook:
    """POST /api/integrations/hook"""

    async def test_input_scan_allowed(self, client, registered_user):
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=_clean_scan_result("safe prompt"),
        ):
            resp = await client.post(
                "/api/integrations/hook",
                json={"text": "safe prompt", "direction": "input"},
                headers=registered_user["headers"],
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["sanitized_text"] == "safe prompt"
        assert "audit_log_id" in data

    async def test_input_scan_blocked(self, client, registered_user):
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=_blocked_scan_result("malicious input"),
        ):
            resp = await client.post(
                "/api/integrations/hook",
                json={"text": "malicious input", "direction": "input"},
                headers=registered_user["headers"],
            )

        assert resp.status_code == 400
        data = resp.json()
        assert "PromptInjection" in data["detail"]

    async def test_output_scan_allowed(self, client, registered_user):
        with patch(
            "app.services.scanner_engine.run_output_scan",
            new_callable=AsyncMock,
            return_value=_clean_scan_result("helpful answer"),
        ):
            resp = await client.post(
                "/api/integrations/hook",
                json={
                    "text": "helpful answer",
                    "direction": "output",
                    "prompt": "What is AI?",
                },
                headers=registered_user["headers"],
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["sanitized_text"] == "helpful answer"

    async def test_empty_input_text_returns_allowed(self, client, registered_user):
        resp = await client.post(
            "/api/integrations/hook",
            json={"text": "", "direction": "input"},
            headers=registered_user["headers"],
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["detail"] == "No input text to scan"

    async def test_empty_output_text_returns_allowed(self, client, registered_user):
        resp = await client.post(
            "/api/integrations/hook",
            json={"text": "", "direction": "output"},
            headers=registered_user["headers"],
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["detail"] == "No output text to scan"


# ── LiteLLM pre_call tests ───────────────────────────────────────────────────

class TestLiteLLMPreCall:
    """POST /api/integrations/litellm/pre_call"""

    async def test_clean_message_allowed(self, client, registered_user):
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=_clean_scan_result("What is Python?"),
        ):
            resp = await client.post(
                "/api/integrations/litellm/pre_call",
                json={
                    "messages": [
                        {"role": "user", "content": "What is Python?"},
                    ],
                },
                headers=registered_user["headers"],
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["sanitized_text"] == "What is Python?"

    async def test_no_user_message_returns_allowed(self, client, registered_user):
        resp = await client.post(
            "/api/integrations/litellm/pre_call",
            json={
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                ],
            },
            headers=registered_user["headers"],
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["detail"] == "No user message to scan"


# ── LiteLLM post_call tests ──────────────────────────────────────────────────

class TestLiteLLMPostCall:
    """POST /api/integrations/litellm/post_call"""

    async def test_clean_response_allowed(self, client, registered_user):
        with patch(
            "app.services.scanner_engine.run_output_scan",
            new_callable=AsyncMock,
            return_value=_clean_scan_result("Python is a programming language."),
        ):
            resp = await client.post(
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
                headers=registered_user["headers"],
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["sanitized_text"] == "Python is a programming language."

    async def test_no_response_returns_allowed(self, client, registered_user):
        resp = await client.post(
            "/api/integrations/litellm/post_call",
            json={
                "messages": [
                    {"role": "user", "content": "Hello"},
                ],
                "response": None,
            },
            headers=registered_user["headers"],
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["detail"] == "No assistant response to scan"


# ── Helper function unit tests ────────────────────────────────────────────────

class TestHelperFunctions:
    """Unit tests for private helpers in integrations.py (no HTTP needed)."""

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
    """POST /api/integrations/litellm/during_call"""

    async def test_during_call_clean_message(self, client, registered_user):
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=_clean_scan_result("What is AI?"),
        ):
            resp = await client.post(
                "/api/integrations/litellm/during_call",
                json={
                    "messages": [
                        {"role": "user", "content": "What is AI?"},
                    ],
                },
                headers=registered_user["headers"],
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["sanitized_text"] == "What is AI?"

    async def test_during_call_no_user_message(self, client, registered_user):
        resp = await client.post(
            "/api/integrations/litellm/during_call",
            json={
                "messages": [
                    {"role": "system", "content": "You are a bot."},
                ],
            },
            headers=registered_user["headers"],
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "allowed"
        assert data["detail"] == "No user message to scan"

    async def test_during_call_blocked(self, client, registered_user):
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=_blocked_scan_result("inject this"),
        ):
            resp = await client.post(
                "/api/integrations/litellm/during_call",
                json={
                    "messages": [
                        {"role": "user", "content": "inject this"},
                    ],
                },
                headers=registered_user["headers"],
            )

        assert resp.status_code == 400
        assert "PromptInjection" in resp.json()["detail"]


# ── Transparent Proxy tests ──────────────────────────────────────────────────

class TestTransparentProxy:
    """POST /api/integrations/proxy"""

    async def test_proxy_missing_upstream_url_returns_400(self, client, registered_user):
        """No X-Upstream-URL header → 400."""
        resp = await client.post(
            "/api/integrations/proxy",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers=registered_user["headers"],
        )
        assert resp.status_code == 400
        assert "X-Upstream-URL" in resp.json()["detail"]

    async def test_proxy_forwards_and_returns(self, client, registered_user):
        """Successful proxy round-trip with mocked upstream + scanner."""
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
            resp = await client.post(
                "/api/integrations/proxy/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={
                    **registered_user["headers"],
                    "X-Upstream-URL": "https://api.openai.com",
                    "X-Upstream-Auth": "Bearer sk-fake",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Hello!"

    async def test_proxy_upstream_error_relayed(self, client, registered_user):
        """Upstream returns non-200 → error is relayed back."""
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
            resp = await client.post(
                "/api/integrations/proxy",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={
                    **registered_user["headers"],
                    "X-Upstream-URL": "https://api.openai.com",
                },
            )

        assert resp.status_code == 429

    async def test_proxy_upstream_unreachable_returns_502(self, client, registered_user):
        """Upstream connection failure → 502."""
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
            resp = await client.post(
                "/api/integrations/proxy",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={
                    **registered_user["headers"],
                    "X-Upstream-URL": "https://api.openai.com",
                },
            )

        assert resp.status_code == 502
        assert "Upstream LLM unreachable" in resp.json()["detail"]
