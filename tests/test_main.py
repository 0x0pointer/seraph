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
