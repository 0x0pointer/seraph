import os
import pytest
import pytest_asyncio
from contextlib import asynccontextmanager
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
    HTTP test client with lifespan disabled (no ML warmup).
    API key auth is open mode (no keys in test config).
    """
    from app.main import app

    # Replace the real lifespan (which spawns ML model warmup) with a no-op
    saved_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def noop_lifespan(a):
        yield

    app.router.lifespan_context = noop_lifespan

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.router.lifespan_context = saved_lifespan
