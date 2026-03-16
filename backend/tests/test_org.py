"""Integration tests for /api/org endpoints."""
import pytest
import pytest_asyncio
import uuid


# ── Helper: register + login a fresh user, return headers ─────────────────────

async def _make_authenticated_user(client, make_user, turnstile_mock, prefix="org"):
    """Register a new user and return (headers_dict, user_payload)."""
    user = make_user(prefix)
    with turnstile_mock():
        await client.post("/api/auth/register", json=user)
    resp = await client.post(
        "/api/auth/login",
        json={"username": user["username"], "password": user["password"]},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user


async def _create_org(client, headers, name="TestOrg"):
    """Create an org and return the response JSON."""
    resp = await client.post("/api/org", json={"name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestCreateOrg:
    async def test_create_org_success(self, client, make_user, turnstile_mock):
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "corg")
        resp = await client.post("/api/org", json={"name": "My New Org"}, headers=headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My New Org"
        assert data["member_count"] == 1
        assert "id" in data
        assert "owner_id" in data

    async def test_create_org_already_in_org(self, client, make_user, turnstile_mock):
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "cdup")
        await _create_org(client, headers, "First Org")
        resp = await client.post("/api/org", json={"name": "Second Org"}, headers=headers)
        assert resp.status_code == 400
        assert "already part of" in resp.json()["detail"].lower()

    async def test_create_org_short_name(self, client, make_user, turnstile_mock):
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "cshort")
        resp = await client.post("/api/org", json={"name": "X"}, headers=headers)
        assert resp.status_code == 422
        assert "at least 2 characters" in resp.json()["detail"]


class TestGetMyOrg:
    async def test_get_org_success(self, client, make_user, turnstile_mock):
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "gorg")
        org = await _create_org(client, headers, "Get Org Test")
        resp = await client.get("/api/org", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Get Org Test"
        assert data["id"] == org["id"]
        assert data["member_count"] == 1

    async def test_get_org_not_in_org(self, client, make_user, turnstile_mock):
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "gnone")
        resp = await client.get("/api/org", headers=headers)
        assert resp.status_code == 403


class TestUpdateOrg:
    async def test_update_org_name_success(self, client, make_user, turnstile_mock):
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "uorg")
        await _create_org(client, headers, "Old Name")
        resp = await client.put("/api/org", json={"name": "New Name"}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_update_org_short_name(self, client, make_user, turnstile_mock):
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "ushort")
        await _create_org(client, headers, "Valid Name")
        resp = await client.put("/api/org", json={"name": "X"}, headers=headers)
        assert resp.status_code == 422
        assert "at least 2 characters" in resp.json()["detail"]


class TestListMembers:
    async def test_list_members_returns_creator(self, client, make_user, turnstile_mock):
        headers, user = await _make_authenticated_user(client, make_user, turnstile_mock, "lmem")
        await _create_org(client, headers, "Members Org")
        resp = await client.get("/api/org/members", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        usernames = [m["username"] for m in data]
        assert user["username"] in usernames


class TestCreateInvite:
    async def test_create_invite_success(self, client, make_user, turnstile_mock):
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "inv")
        await _create_org(client, headers, "Invite Org")
        uid = uuid.uuid4().hex[:8]
        resp = await client.post(
            "/api/org/invite",
            json={"email": f"invitee_{uid}@example.com", "role": "viewer"},
            headers=headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "token" in data
        assert data["role"] == "viewer"
        assert data["email"] == f"invitee_{uid}@example.com"

    async def test_create_invite_invalid_email(self, client, make_user, turnstile_mock):
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "inve")
        await _create_org(client, headers, "Invite Org 2")
        resp = await client.post(
            "/api/org/invite",
            json={"email": "notanemail", "role": "viewer"},
            headers=headers,
        )
        assert resp.status_code == 422
        assert "Invalid email" in resp.json()["detail"]

    async def test_create_invite_invalid_role(self, client, make_user, turnstile_mock):
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "invr")
        await _create_org(client, headers, "Invite Org 3")
        resp = await client.post(
            "/api/org/invite",
            json={"email": "someone@example.com", "role": "superuser"},
            headers=headers,
        )
        assert resp.status_code == 422
        assert "Role must be" in resp.json()["detail"]


class TestListInvites:
    async def test_list_invites_shows_pending(self, client, make_user, turnstile_mock):
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "linv")
        await _create_org(client, headers, "List Invites Org")
        uid = uuid.uuid4().hex[:8]
        email = f"pending_{uid}@example.com"
        await client.post(
            "/api/org/invite",
            json={"email": email, "role": "viewer"},
            headers=headers,
        )
        resp = await client.get("/api/org/invites", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        emails = [inv["email"] for inv in data]
        assert email in emails


class TestCancelInvite:
    async def test_cancel_invite_success(self, client, make_user, turnstile_mock):
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "cinv")
        await _create_org(client, headers, "Cancel Invites Org")
        uid = uuid.uuid4().hex[:8]
        create_resp = await client.post(
            "/api/org/invite",
            json={"email": f"cancel_{uid}@example.com", "role": "viewer"},
            headers=headers,
        )
        invite_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/org/invites/{invite_id}", headers=headers)
        assert resp.status_code == 204

        # Verify it's gone
        list_resp = await client.get("/api/org/invites", headers=headers)
        ids = [inv["id"] for inv in list_resp.json()]
        assert invite_id not in ids

    async def test_cancel_nonexistent_invite_returns_404(self, client, make_user, turnstile_mock):
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "cinv2")
        await _create_org(client, headers, "Cancel Invites Org 2")
        resp = await client.delete("/api/org/invites/999999", headers=headers)
        assert resp.status_code == 404


class TestValidateInviteToken:
    async def test_validate_valid_token(self, client, make_user, turnstile_mock):
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "vinv")
        await _create_org(client, headers, "Validate Token Org")
        uid = uuid.uuid4().hex[:8]
        create_resp = await client.post(
            "/api/org/invite",
            json={"email": f"validate_{uid}@example.com", "role": "viewer"},
            headers=headers,
        )
        token = create_resp.json()["token"]
        resp = await client.get(f"/api/org/invite/validate?token={token}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["org_name"] == "Validate Token Org"
        assert data["email"] == f"validate_{uid}@example.com"
        assert data["role"] == "viewer"

    async def test_validate_invalid_token_returns_404(self, client):
        resp = await client.get("/api/org/invite/validate?token=bogus-token-abc")
        assert resp.status_code == 404
        assert "Invalid or already used" in resp.json()["detail"]
