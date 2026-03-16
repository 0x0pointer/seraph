import os
import uuid

# MUST be set before any app module is imported so pydantic-settings picks them up
os.environ.setdefault("SECRET_KEY", "ci-test-secret-key-at-least-32-characters-long")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_seraph.db")

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

TEST_DB_URL = os.environ["DATABASE_URL"]
_test_engine = create_async_engine(TEST_DB_URL)
_test_session_maker = async_sessionmaker(_test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    """Create all tables once for the entire test session."""
    # Import main.py to register every SQLAlchemy model with Base.metadata
    import app.main  # noqa: F401
    from app.core.database import Base

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    await _test_engine.dispose()
    try:
        os.remove("test_seraph.db")
    except FileNotFoundError:
        pass


@pytest_asyncio.fixture
async def db_session():
    """Provide a database session scoped to one test."""
    async with _test_session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    """
    HTTP test client with:
    - startup events cleared (no ML warmup, no seeding)
    - get_session overridden to use the test DB
    - rate-limiter storage reset
    """
    from app.main import app
    from app.core.database import get_session
    from app.core.limiter import limiter

    saved_startup = list(app.router.on_startup)
    app.router.on_startup.clear()

    # Reset in-memory rate-limit counters so tests don't hit limits
    try:
        limiter._storage.reset()
    except Exception:
        pass

    async def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.router.on_startup[:] = saved_startup
    app.dependency_overrides.clear()


# ── Shared helpers ─────────────────────────────────────────────────────────────

@pytest.fixture
def make_user():
    """Return a factory that produces unique user payloads."""
    def _factory(prefix: str = "u") -> dict:
        uid = uuid.uuid4().hex[:8]
        return {
            "username": f"{prefix}_{uid}",
            "full_name": "Test User",
            "email": f"{prefix}_{uid}@example.com",
            "password": "StrongPassword123!",
            "turnstile_token": "test-token",
        }
    return _factory


@pytest.fixture
def turnstile_mock():
    """Return a factory for Turnstile CAPTCHA mocks."""
    def _mock(success: bool = True):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": success}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        return patch("httpx.AsyncClient", return_value=mock_client)
    return _mock


@pytest_asyncio.fixture
async def registered_user(client, make_user, turnstile_mock):
    """Register a user, log them in, and return credentials + auth headers."""
    user = make_user("fixture")
    with turnstile_mock():
        await client.post("/api/auth/register", json=user)
    resp = await client.post(
        "/api/auth/login",
        json={"username": user["username"], "password": user["password"]},
    )
    token = resp.json()["access_token"]
    return {
        "user": user,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }
