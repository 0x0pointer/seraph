"""Integration tests for app/main.py — health, reload, middleware."""
import pytest
from unittest.mock import patch


class TestHealthEndpoint:
    def test_returns_200_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["app"] == "Seraph"


class TestSecurityHeaders:
    def test_security_headers_present(self, client):
        resp = client.get("/health")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert resp.headers["X-XSS-Protection"] == "1; mode=block"
        assert "max-age=31536000" in resp.headers["Strict-Transport-Security"]


class TestReloadEndpoint:
    def test_reload_returns_status(self, client):
        with patch(
            "app.services.scanner_engine.reload_scanners",
        ) as mock_reload:
            resp = client.post("/reload")
        assert resp.status_code == 200
        assert resp.json()["status"] == "reloaded"
        mock_reload.assert_called_once()


class TestValidationErrorHandler:
    def test_invalid_json_returns_422(self, client):
        resp = client.post(
            "/api/scan/prompt",
            json={"wrong_field": "no text field"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Invalid request data"


class TestBodySizeLimiting:
    def test_oversized_body_returns_413(self, client):
        """POST with Content-Length > 1 MB is rejected."""
        resp = client.post(
            "/api/scan/prompt",
            content=b"x" * 100,
            headers={"Content-Length": str(2 * 1024 * 1024), "Content-Type": "application/json"},
        )
        assert resp.status_code == 413
        assert "too large" in resp.json()["detail"].lower()

    def test_normal_body_passes(self, client):
        """POST with small Content-Length passes through to normal handling."""
        from unittest.mock import AsyncMock, patch
        with patch(
            "app.services.scanner_engine.run_input_scan",
            new_callable=AsyncMock,
            return_value=(True, "hi", {}, [], {}, None, False),
        ):
            resp = client.post("/api/scan/prompt", json={"text": "hi"})
        assert resp.status_code == 200

    def test_get_request_bypasses_size_check(self, client):
        """GET requests are not subject to body size checking."""
        resp = client.get("/health")
        assert resp.status_code == 200


class TestLifespan:
    def test_sighup_handler_reloads_config(self):
        """_handle_sighup calls reload_config and reload_scanners."""
        from app.main import _handle_sighup
        with (
            patch("app.main.reload_config") as mock_rc,
            patch("app.main.reload_scanners") as mock_rs,
        ):
            _handle_sighup()
        mock_rc.assert_called_once()
        mock_rs.assert_called_once()

    def test_warmup_scanners_calls_engine(self):
        """_warmup_scanners delegates to scanner_engine.warmup."""
        import asyncio
        from app.main import _warmup_scanners
        with patch(
            "app.services.scanner_engine.warmup",
            new_callable=AsyncMock,
        ) as mock_warmup:
            asyncio.get_event_loop().run_until_complete(_warmup_scanners())
        mock_warmup.assert_called_once()
