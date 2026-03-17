import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Point to test config before any app module is imported
os.environ["SERAPH_CONFIG"] = os.path.join(os.path.dirname(__file__), "test_config.yaml")


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_config():
    """Load test config once for the entire test session."""
    from app.core.config import load_config
    load_config()
    yield


@pytest_asyncio.fixture
async def client():
    """
    HTTP test client with startup events cleared (no ML warmup).
    API key auth is open mode (no keys in test config).
    """
    from app.main import app

    saved_startup = list(app.router.on_startup)
    app.router.on_startup.clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.router.on_startup[:] = saved_startup
