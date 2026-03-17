"""Unit tests for app/core/auth.py — API key verification."""
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport


class TestApiKeyAuthOpenMode:
    """When api_keys is empty, all requests should pass (open mode)."""

    async def test_health_no_auth_required(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_scan_endpoint_allowed_without_key(self, client):
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=(True, "test", {}, [], {}, None, False),
        ):
            resp = await client.post(
                "/api/scan/prompt",
                json={"text": "test"},
            )
        assert resp.status_code == 200

    async def test_hook_allowed_without_key(self, client):
        resp = await client.post(
            "/api/integrations/hook",
            json={"text": "", "direction": "input"},
        )
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

    async def test_missing_key_returns_403(self, client):
        resp = await client.post(
            "/api/scan/prompt",
            json={"text": "hello"},
        )
        assert resp.status_code == 403
        assert "Missing API key" in resp.json()["detail"]

    async def test_invalid_key_returns_403(self, client):
        resp = await client.post(
            "/api/scan/prompt",
            json={"text": "hello"},
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 403
        assert "Invalid API key" in resp.json()["detail"]

    async def test_valid_key_passes(self, client):
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=(True, "hello", {}, [], {}, None, False),
        ):
            resp = await client.post(
                "/api/scan/prompt",
                json={"text": "hello"},
                headers={"Authorization": "Bearer test-key-123"},
            )
        assert resp.status_code == 200

    async def test_second_valid_key_also_passes(self, client):
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=(True, "hello", {}, [], {}, None, False),
        ):
            resp = await client.post(
                "/api/scan/prompt",
                json={"text": "hello"},
                headers={"Authorization": "Bearer test-key-456"},
            )
        assert resp.status_code == 200

    async def test_hook_requires_key(self, client):
        resp = await client.post(
            "/api/integrations/hook",
            json={"text": "test", "direction": "input"},
        )
        assert resp.status_code == 403

    async def test_litellm_requires_key(self, client):
        resp = await client.post(
            "/api/integrations/litellm/pre_call",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 403

    async def test_reload_requires_key(self, client):
        resp = await client.post("/reload")
        assert resp.status_code == 403

    async def test_health_does_not_require_key(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
