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


# ── Additional coverage tests ─────────────────────────────────────────────────

async def _create_org_and_invite_user(client, make_user, turnstile_mock):
    """
    Helper: create an org (admin_user), invite a second user, accept the invite,
    and return (admin_headers, member_headers, admin_user, member_user, org).
    """
    # Admin creates org
    admin_headers, admin_user = await _make_authenticated_user(
        client, make_user, turnstile_mock, "adm"
    )
    org = await _create_org(client, admin_headers, "TeamOrg")

    # Invite a second user
    uid = uuid.uuid4().hex[:8]
    invite_email = f"member_{uid}@example.com"
    inv_resp = await client.post(
        "/api/org/invite",
        json={"email": invite_email, "role": "viewer"},
        headers=admin_headers,
    )
    assert inv_resp.status_code == 201
    token = inv_resp.json()["token"]

    # Accept invite (creates a new user account)
    member_username = f"mem_{uid}"
    accept_resp = await client.post(
        "/api/org/invite/accept",
        json={
            "token": token,
            "username": member_username,
            "password": "StrongPassword123!",
            "full_name": "Member User",
        },
    )
    assert accept_resp.status_code == 200, accept_resp.text
    member_token = accept_resp.json()["access_token"]
    member_headers = {"Authorization": f"Bearer {member_token}"}

    # Get member id from members list
    members_resp = await client.get("/api/org/members", headers=admin_headers)
    members = members_resp.json()
    member_info = next(m for m in members if m["username"] == member_username)

    return admin_headers, member_headers, admin_user, member_info, org


class TestUpdateOrgPermissions:
    async def test_non_org_admin_gets_403(self, client, make_user, turnstile_mock):
        """A viewer member cannot update the org name."""
        admin_headers, member_headers, _, _, _ = await _create_org_and_invite_user(
            client, make_user, turnstile_mock
        )
        resp = await client.put(
            "/api/org", json={"name": "Hacked Name"}, headers=member_headers
        )
        assert resp.status_code == 403


class TestMemberManagement:
    async def test_change_member_role(self, client, make_user, turnstile_mock):
        """Admin can change a member's role from viewer to org_admin."""
        admin_headers, _, _, member_info, _ = await _create_org_and_invite_user(
            client, make_user, turnstile_mock
        )
        resp = await client.patch(
            f"/api/org/members/{member_info['id']}/role",
            json={"role": "org_admin"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "org_admin"

    async def test_remove_member(self, client, make_user, turnstile_mock):
        """Admin can remove a member from the org."""
        admin_headers, _, _, member_info, _ = await _create_org_and_invite_user(
            client, make_user, turnstile_mock
        )
        resp = await client.delete(
            f"/api/org/members/{member_info['id']}", headers=admin_headers
        )
        assert resp.status_code == 204

        # Verify they no longer appear in the members list
        members_resp = await client.get("/api/org/members", headers=admin_headers)
        member_ids = [m["id"] for m in members_resp.json()]
        assert member_info["id"] not in member_ids

    async def test_cannot_remove_yourself(self, client, make_user, turnstile_mock):
        """Admin cannot remove themselves from the org."""
        admin_headers, admin_user = await _make_authenticated_user(
            client, make_user, turnstile_mock, "selfr"
        )
        await _create_org(client, admin_headers, "SelfRemoveOrg")

        # Get admin's own user id from members list
        members_resp = await client.get("/api/org/members", headers=admin_headers)
        admin_info = next(
            m for m in members_resp.json() if m["username"] == admin_user["username"]
        )

        resp = await client.delete(
            f"/api/org/members/{admin_info['id']}", headers=admin_headers
        )
        assert resp.status_code == 400
        assert "Cannot remove yourself" in resp.json()["detail"]

    async def test_cannot_change_own_role(self, client, make_user, turnstile_mock):
        """Admin cannot change their own role."""
        admin_headers, admin_user = await _make_authenticated_user(
            client, make_user, turnstile_mock, "selfch"
        )
        await _create_org(client, admin_headers, "SelfChangeOrg")

        members_resp = await client.get("/api/org/members", headers=admin_headers)
        admin_info = next(
            m for m in members_resp.json() if m["username"] == admin_user["username"]
        )

        resp = await client.patch(
            f"/api/org/members/{admin_info['id']}/role",
            json={"role": "viewer"},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "Cannot change your own role" in resp.json()["detail"]


class TestAcceptInvite:
    async def test_accept_invite_creates_user_and_joins_org(
        self, client, make_user, turnstile_mock
    ):
        """Accepting a valid invite creates a new user who belongs to the org."""
        admin_headers, _ = await _make_authenticated_user(
            client, make_user, turnstile_mock, "ainv"
        )
        org = await _create_org(client, admin_headers, "AcceptOrg")

        uid = uuid.uuid4().hex[:8]
        invite_email = f"accept_{uid}@example.com"
        inv_resp = await client.post(
            "/api/org/invite",
            json={"email": invite_email, "role": "viewer"},
            headers=admin_headers,
        )
        token = inv_resp.json()["token"]

        accept_resp = await client.post(
            "/api/org/invite/accept",
            json={
                "token": token,
                "username": f"accepted_{uid}",
                "password": "StrongPassword123!",
                "full_name": "Accepted User",
            },
        )
        assert accept_resp.status_code == 200
        assert "access_token" in accept_resp.json()

        # The new user should be visible in the org members list
        members_resp = await client.get("/api/org/members", headers=admin_headers)
        usernames = [m["username"] for m in members_resp.json()]
        assert f"accepted_{uid}" in usernames

    async def test_accept_invite_invalid_token_returns_400(self, client):
        """Using an invalid/expired token returns 400."""
        resp = await client.post(
            "/api/org/invite/accept",
            json={
                "token": "totally-bogus-token",
                "username": "nope_user",
                "password": "StrongPassword123!",
                "full_name": "No One",
            },
        )
        assert resp.status_code == 400
        assert "Invalid or already used" in resp.json()["detail"]


# ── Additional coverage: uncovered branches ──────────────────────────────────

class TestOrgNotInOrg:
    """Users without an org cannot access org endpoints."""

    async def test_get_org_no_membership_returns_403(self, client, make_user, turnstile_mock):
        """A user who is not part of any org gets 403 on GET /api/org."""
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "noorg")
        resp = await client.get("/api/org", headers=headers)
        assert resp.status_code == 403
        assert "not part of" in resp.json()["detail"].lower()

    async def test_put_org_no_membership_returns_403(self, client, make_user, turnstile_mock):
        """A user who is not org_admin gets 403 on PUT /api/org."""
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "noorg2")
        resp = await client.put("/api/org", json={"name": "Nope"}, headers=headers)
        assert resp.status_code == 403

    async def test_list_members_no_membership_returns_403(self, client, make_user, turnstile_mock):
        """A user without an org gets 403 on GET /api/org/members."""
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "noorg3")
        resp = await client.get("/api/org/members", headers=headers)
        assert resp.status_code == 403


class TestUpdateOrgShortName:
    async def test_update_org_empty_name(self, client, make_user, turnstile_mock):
        """PUT /api/org with empty name returns 422."""
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "uempty")
        await _create_org(client, headers, "Valid Name")
        resp = await client.put("/api/org", json={"name": ""}, headers=headers)
        assert resp.status_code == 422
        assert "at least 2 characters" in resp.json()["detail"]

    async def test_update_org_single_char_name(self, client, make_user, turnstile_mock):
        """PUT /api/org with single char name returns 422."""
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "u1ch")
        await _create_org(client, headers, "Valid Name")
        resp = await client.put("/api/org", json={"name": "A"}, headers=headers)
        assert resp.status_code == 422
        assert "at least 2 characters" in resp.json()["detail"]


class TestInviteExistingMember:
    async def test_invite_already_existing_member_returns_409(self, client, make_user, turnstile_mock):
        """Inviting someone who is already a member of the org returns 409."""
        admin_headers, member_headers, admin_user, member_info, org = (
            await _create_org_and_invite_user(client, make_user, turnstile_mock)
        )
        # member_info has the member's username; get their email from the members list
        members_resp = await client.get("/api/org/members", headers=admin_headers)
        member = next(m for m in members_resp.json() if m["id"] == member_info["id"])
        member_email = member["email"]

        resp = await client.post(
            "/api/org/invite",
            json={"email": member_email, "role": "viewer"},
            headers=admin_headers,
        )
        assert resp.status_code == 409
        assert "already a member" in resp.json()["detail"].lower()


class TestRemoveMemberSuperadminGuard:
    async def test_change_role_nonexistent_member_returns_404(self, client, make_user, turnstile_mock):
        """Changing role of a non-existent member returns 404."""
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "nfm")
        await _create_org(client, headers, "NFM Org")
        resp = await client.patch(
            "/api/org/members/999999/role",
            json={"role": "viewer"},
            headers=headers,
        )
        assert resp.status_code == 404
        assert "Member not found" in resp.json()["detail"]

    async def test_change_role_invalid_role_returns_422(self, client, make_user, turnstile_mock):
        """Changing to an invalid role returns 422."""
        admin_headers, _, _, member_info, _ = await _create_org_and_invite_user(
            client, make_user, turnstile_mock
        )
        resp = await client.patch(
            f"/api/org/members/{member_info['id']}/role",
            json={"role": "superuser"},
            headers=admin_headers,
        )
        assert resp.status_code == 422
        assert "Role must be" in resp.json()["detail"]

    async def test_remove_nonexistent_member_returns_404(self, client, make_user, turnstile_mock):
        """Removing a non-existent member returns 404."""
        headers, _ = await _make_authenticated_user(client, make_user, turnstile_mock, "nfr")
        await _create_org(client, headers, "NFR Org")
        resp = await client.delete("/api/org/members/999999", headers=headers)
        assert resp.status_code == 404
        assert "Member not found" in resp.json()["detail"]
