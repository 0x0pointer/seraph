"""Integration tests for /api/auth endpoints."""
import os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

_db_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./test_seraph.db")
_direct_session_maker = async_sessionmaker(
    create_async_engine(_db_url), expire_on_commit=False
)


class TestLogin:
    async def test_success_returns_token(self, client, make_user, turnstile_mock):
        user = make_user("login_ok")
        with turnstile_mock():
            await client.post("/api/auth/register", json=user)

        resp = await client.post(
            "/api/auth/login",
            json={"username": user["username"], "password": user["password"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_wrong_password_returns_401(self, client, make_user, turnstile_mock):
        user = make_user("login_bad")
        with turnstile_mock():
            await client.post("/api/auth/register", json=user)

        resp = await client.post(
            "/api/auth/login",
            json={"username": user["username"], "password": "WrongPassword999!"},
        )
        assert resp.status_code == 401

    async def test_nonexistent_user_returns_401(self, client):
        resp = await client.post(
            "/api/auth/login",
            json={"username": "ghost_user_xyz", "password": "Password123!"},
        )
        assert resp.status_code == 401

    async def test_empty_body_returns_422(self, client):
        resp = await client.post("/api/auth/login", json={})
        assert resp.status_code == 422


class TestRegister:
    async def test_success_returns_201_and_token(self, client, make_user, turnstile_mock):
        user = make_user("reg_ok")
        with turnstile_mock():
            resp = await client.post("/api/auth/register", json=user)
        assert resp.status_code == 201
        assert "access_token" in resp.json()

    async def test_captcha_failure_returns_400(self, client, make_user, turnstile_mock):
        user = make_user("reg_cap")
        with turnstile_mock(success=False):
            resp = await client.post("/api/auth/register", json=user)
        assert resp.status_code == 400

    async def test_duplicate_username_returns_409(self, client, make_user, turnstile_mock):
        user = make_user("reg_dup")
        with turnstile_mock():
            await client.post("/api/auth/register", json=user)
        user2 = dict(user)
        user2["email"] = f"other_{user['email']}"
        with turnstile_mock():
            resp = await client.post("/api/auth/register", json=user2)
        assert resp.status_code == 409

    async def test_duplicate_email_returns_409(self, client, make_user, turnstile_mock):
        user = make_user("reg_dupe")
        with turnstile_mock():
            await client.post("/api/auth/register", json=user)
        user3 = dict(user)
        user3["username"] = f"other_{user['username']}"
        with turnstile_mock():
            resp = await client.post("/api/auth/register", json=user3)
        assert resp.status_code == 409

    async def test_short_username_returns_422(self, client, make_user, turnstile_mock):
        user = make_user()
        user["username"] = "ab"  # less than 3 chars
        with turnstile_mock():
            resp = await client.post("/api/auth/register", json=user)
        assert resp.status_code == 422

    async def test_invalid_email_returns_422(self, client, make_user, turnstile_mock):
        user = make_user("reg_email")
        user["email"] = "notanemail"
        with turnstile_mock():
            resp = await client.post("/api/auth/register", json=user)
        assert resp.status_code == 422

    async def test_short_password_rejected_by_pydantic(self, client, make_user, turnstile_mock):
        user = make_user("reg_pwd")
        user["password"] = "short"  # under 12 chars
        with turnstile_mock():
            resp = await client.post("/api/auth/register", json=user)
        assert resp.status_code == 422

    async def test_short_full_name_returns_422(self, client, make_user, turnstile_mock):
        user = make_user("reg_name")
        user["full_name"] = "X"  # less than 2 chars
        with turnstile_mock():
            resp = await client.post("/api/auth/register", json=user)
        assert resp.status_code == 422


class TestMe:
    async def test_authenticated_user_gets_profile(self, client, registered_user):
        resp = await client.get("/api/auth/me", headers=registered_user["headers"])
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == registered_user["user"]["username"]
        assert data["email"] == registered_user["user"]["email"]
        assert "role" in data
        assert "id" in data

    async def test_unauthenticated_returns_403(self, client):
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 403

    async def test_invalid_token_returns_403(self, client):
        resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code in (401, 403)


class TestUpdateProfile:
    async def test_update_full_name(self, client, registered_user):
        resp = await client.patch(
            "/api/auth/me",
            json={"full_name": "Updated Name"},
            headers=registered_user["headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["full_name"] == "Updated Name"

    async def test_update_email(self, client, registered_user, make_user):
        new_email = f"newemail_{registered_user['user']['username']}@example.com"
        resp = await client.patch(
            "/api/auth/me",
            json={"email": new_email},
            headers=registered_user["headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == new_email

    async def test_update_invalid_email_returns_422(self, client, registered_user):
        resp = await client.patch(
            "/api/auth/me",
            json={"email": "not-valid"},
            headers=registered_user["headers"],
        )
        assert resp.status_code == 422

    async def test_update_short_full_name_returns_422(self, client, registered_user):
        resp = await client.patch(
            "/api/auth/me",
            json={"full_name": "X"},
            headers=registered_user["headers"],
        )
        assert resp.status_code == 422


class TestChangePassword:
    async def test_success(self, client, registered_user):
        resp = await client.post(
            "/api/auth/change-password",
            json={
                "current_password": registered_user["user"]["password"],
                "new_password": "NewStrongPassword99!",
            },
            headers=registered_user["headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Password updated successfully"

    async def test_wrong_current_password_returns_400(self, client, registered_user):
        resp = await client.post(
            "/api/auth/change-password",
            json={
                "current_password": "WrongCurrent!999",
                "new_password": "NewStrongPassword99!",
            },
            headers=registered_user["headers"],
        )
        assert resp.status_code == 400

    async def test_new_password_too_short_returns_422(self, client, registered_user):
        resp = await client.post(
            "/api/auth/change-password",
            json={
                "current_password": registered_user["user"]["password"],
                "new_password": "short",
            },
            headers=registered_user["headers"],
        )
        assert resp.status_code == 422


class TestApiToken:
    async def test_generate_token_starts_with_prefix(self, client, registered_user):
        resp = await client.get(
            "/api/auth/api-token",
            headers=registered_user["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_token"].startswith("ts_live_")
        assert data["created"] is True

    async def test_same_token_returned_on_second_call(self, client, registered_user):
        h = registered_user["headers"]
        r1 = await client.get("/api/auth/api-token", headers=h)
        r2 = await client.get("/api/auth/api-token", headers=h)
        assert r1.json()["api_token"] == r2.json()["api_token"]
        assert r2.json()["created"] is False

    async def test_regenerate_returns_new_token(self, client, registered_user):
        h = registered_user["headers"]
        r1 = await client.get("/api/auth/api-token", headers=h)
        r2 = await client.post("/api/auth/api-token/regenerate", headers=h)
        assert r1.json()["api_token"] != r2.json()["api_token"]
        assert r2.json()["created"] is True


class TestForgotResetPassword:
    async def test_forgot_password_always_returns_202(self, client):
        """Anti-enumeration: always 202 regardless of whether email exists."""
        resp = await client.post(
            "/api/auth/forgot-password",
            json={"email": "ghost@example.com"},
        )
        assert resp.status_code == 202

    async def test_forgot_username_always_returns_202(self, client):
        resp = await client.post(
            "/api/auth/forgot-username",
            json={"email": "ghost@example.com"},
        )
        assert resp.status_code == 202

    async def test_reset_with_invalid_token_returns_400(self, client):
        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": "bogustoken", "new_password": "NewStrongPass99!"},
        )
        assert resp.status_code == 400

    async def test_reset_with_short_password_returns_422(self, client):
        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": "anytoken", "new_password": "short"},
        )
        assert resp.status_code == 422

    async def test_full_reset_flow(self, client, make_user, turnstile_mock):
        """Register → forgot-password → reset-password → login with new password."""
        import hashlib, secrets
        from datetime import datetime, timedelta, timezone

        user = make_user("reset_flow")
        with turnstile_mock():
            await client.post("/api/auth/register", json=user)

        # Manually inject a valid reset token into the DB
        from app.models.user import User
        from sqlalchemy import select
        async with _direct_session_maker() as s:
            result = await s.execute(
                select(User).where(User.username == user["username"])
            )
            db_user = result.scalar_one()
            raw_token = secrets.token_urlsafe(32)
            db_user.reset_token = hashlib.sha256(raw_token.encode()).hexdigest()
            db_user.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
            await s.commit()

        new_password = "NewStrongPass99!"
        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "new_password": new_password},
        )
        assert resp.status_code == 200

        login_resp = await client.post(
            "/api/auth/login",
            json={"username": user["username"], "password": new_password},
        )
        assert login_resp.status_code == 200
