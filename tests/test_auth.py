"""Unit tests for app/core/auth.py — API key verification."""
import pytest
import httpx
from unittest.mock import patch, AsyncMock


def _get_proxy_client():
    from app.api.routes.proxy import _PROXY_CLIENT
    return _PROXY_CLIENT


def _clean_scan_result(text: str = "hello"):
    return (True, text, {}, [], {}, None, False)


def _proxy_post(client, text="test", headers=None):
    """Helper to POST to the proxy endpoint."""
    hdrs = {"X-Upstream-URL": "https://api.openai.com"}
    if headers:
        hdrs.update(headers)

    upstream_response = httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
    )

    with (
        patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=_clean_scan_result(text),
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
        return client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": text}]},
            headers=hdrs,
        )


class TestApiKeyAuthOpenMode:
    """When api_keys is empty, all requests should pass (open mode)."""

    def test_health_no_auth_required(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_proxy_allowed_without_key(self, client):
        resp = _proxy_post(client, "test")
        assert resp.status_code == 200


class TestApiKeyAuthProtectedMode:
    """When api_keys is set, requests without a valid key should be rejected."""

    @pytest.fixture(autouse=True)
    def _enable_api_keys(self):
        from app.core.config import get_config
        config = get_config()
        saved = config.api_keys
        config.api_keys = ["test-key-123", "test-key-456"]
        yield
        config.api_keys = saved

    def test_missing_key_returns_403(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
            headers={"X-Upstream-URL": "https://api.openai.com"},
        )
        assert resp.status_code == 403
        assert "Missing API key" in resp.json()["detail"]

    def test_invalid_key_returns_403(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
            headers={
                "Authorization": "Bearer wrong-key",
                "X-Upstream-URL": "https://api.openai.com",
            },
        )
        assert resp.status_code == 403
        assert "Invalid API key" in resp.json()["detail"]

    def test_valid_key_passes(self, client):
        resp = _proxy_post(client, "hello", {"Authorization": "Bearer test-key-123"})
        assert resp.status_code == 200

    def test_second_valid_key_also_passes(self, client):
        resp = _proxy_post(client, "hello", {"Authorization": "Bearer test-key-456"})
        assert resp.status_code == 200

    def test_reload_requires_key(self, client):
        resp = client.post("/reload")
        assert resp.status_code == 403

    def test_health_does_not_require_key(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
