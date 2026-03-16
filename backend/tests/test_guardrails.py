"""Integration tests for /api/guardrails endpoints (CRUD + toggle)."""
import pytest
from unittest.mock import patch


# Patch invalidate_cache to avoid touching scanner state in tests
_no_op_cache = patch("app.services.scanner_engine.invalidate_cache", return_value=None)

_BASE_GUARDRAIL = {
    "name": "Test Toxicity Guard",
    "scanner_type": "Toxicity",
    "direction": "input",
    "is_active": True,
    "on_fail_action": "block",
    "params": {"threshold": 0.5},
    "order": 0,
}


class TestListGuardrails:
    async def test_unauthenticated_returns_403(self, client):
        resp = await client.get("/api/guardrails")
        assert resp.status_code == 403

    async def test_authenticated_returns_list(self, client, registered_user):
        resp = await client.get("/api/guardrails", headers=registered_user["headers"])
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestCreateGuardrail:
    async def test_create_returns_201(self, client, registered_user):
        with _no_op_cache:
            resp = await client.post(
                "/api/guardrails",
                json=_BASE_GUARDRAIL,
                headers=registered_user["headers"],
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == _BASE_GUARDRAIL["name"]
        assert data["scanner_type"] == "Toxicity"
        assert data["direction"] == "input"
        assert data["is_active"] is True
        assert "id" in data
        assert "created_at" in data

    async def test_create_with_monitor_action(self, client, registered_user):
        payload = {**_BASE_GUARDRAIL, "on_fail_action": "monitor", "name": "Monitor Guard"}
        with _no_op_cache:
            resp = await client.post(
                "/api/guardrails",
                json=payload,
                headers=registered_user["headers"],
            )
        assert resp.status_code == 201
        assert resp.json()["on_fail_action"] == "monitor"

    async def test_create_output_direction(self, client, registered_user):
        payload = {**_BASE_GUARDRAIL, "direction": "output", "name": "Output Guard"}
        with _no_op_cache:
            resp = await client.post(
                "/api/guardrails",
                json=payload,
                headers=registered_user["headers"],
            )
        assert resp.status_code == 201
        assert resp.json()["direction"] == "output"

    async def test_unauthenticated_returns_403(self, client):
        resp = await client.post("/api/guardrails", json=_BASE_GUARDRAIL)
        assert resp.status_code == 403


class TestUpdateGuardrail:
    async def test_update_name_and_params(self, client, registered_user):
        with _no_op_cache:
            create_resp = await client.post(
                "/api/guardrails",
                json=_BASE_GUARDRAIL,
                headers=registered_user["headers"],
            )
        guardrail_id = create_resp.json()["id"]

        with _no_op_cache:
            update_resp = await client.put(
                f"/api/guardrails/{guardrail_id}",
                json={"name": "Updated Name", "params": {"threshold": 0.9}},
                headers=registered_user["headers"],
            )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["name"] == "Updated Name"
        assert data["params"]["threshold"] == 0.9

    async def test_update_nonexistent_returns_404(self, client, registered_user):
        with _no_op_cache:
            resp = await client.put(
                "/api/guardrails/999999",
                json={"name": "Ghost"},
                headers=registered_user["headers"],
            )
        assert resp.status_code == 404

    async def test_update_active_status(self, client, registered_user):
        with _no_op_cache:
            create_resp = await client.post(
                "/api/guardrails",
                json=_BASE_GUARDRAIL,
                headers=registered_user["headers"],
            )
        gid = create_resp.json()["id"]

        with _no_op_cache:
            resp = await client.put(
                f"/api/guardrails/{gid}",
                json={"is_active": False},
                headers=registered_user["headers"],
            )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False


class TestDeleteGuardrail:
    async def test_delete_returns_204(self, client, registered_user):
        with _no_op_cache:
            create_resp = await client.post(
                "/api/guardrails",
                json=_BASE_GUARDRAIL,
                headers=registered_user["headers"],
            )
        gid = create_resp.json()["id"]

        with _no_op_cache:
            del_resp = await client.delete(
                f"/api/guardrails/{gid}",
                headers=registered_user["headers"],
            )
        assert del_resp.status_code == 204

    async def test_delete_nonexistent_returns_404(self, client, registered_user):
        with _no_op_cache:
            resp = await client.delete(
                "/api/guardrails/999999",
                headers=registered_user["headers"],
            )
        assert resp.status_code == 404

    async def test_deleted_guardrail_not_in_list(self, client, registered_user):
        payload = {**_BASE_GUARDRAIL, "name": "To Be Deleted"}
        with _no_op_cache:
            create_resp = await client.post(
                "/api/guardrails",
                json=payload,
                headers=registered_user["headers"],
            )
        gid = create_resp.json()["id"]
        with _no_op_cache:
            await client.delete(f"/api/guardrails/{gid}", headers=registered_user["headers"])

        list_resp = await client.get("/api/guardrails", headers=registered_user["headers"])
        ids = [g["id"] for g in list_resp.json()]
        assert gid not in ids


class TestToggleGuardrail:
    async def test_toggle_flips_active_status(self, client, registered_user):
        with _no_op_cache:
            create_resp = await client.post(
                "/api/guardrails",
                json=_BASE_GUARDRAIL,
                headers=registered_user["headers"],
            )
        gid = create_resp.json()["id"]
        original_status = create_resp.json()["is_active"]

        with _no_op_cache:
            toggle_resp = await client.patch(
                f"/api/guardrails/{gid}/toggle",
                headers=registered_user["headers"],
            )
        assert toggle_resp.status_code == 200
        assert toggle_resp.json()["is_active"] is not original_status

    async def test_toggle_twice_restores_original(self, client, registered_user):
        with _no_op_cache:
            create_resp = await client.post(
                "/api/guardrails",
                json=_BASE_GUARDRAIL,
                headers=registered_user["headers"],
            )
        gid = create_resp.json()["id"]
        original = create_resp.json()["is_active"]

        with _no_op_cache:
            await client.patch(f"/api/guardrails/{gid}/toggle", headers=registered_user["headers"])
            resp2 = await client.patch(
                f"/api/guardrails/{gid}/toggle",
                headers=registered_user["headers"],
            )
        assert resp2.json()["is_active"] == original

    async def test_toggle_nonexistent_returns_404(self, client, registered_user):
        with _no_op_cache:
            resp = await client.patch(
                "/api/guardrails/999999/toggle",
                headers=registered_user["headers"],
            )
        assert resp.status_code == 404
