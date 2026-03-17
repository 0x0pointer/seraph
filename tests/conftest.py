import os
import pytest
from contextlib import asynccontextmanager
from fastapi.testclient import TestClient

# Point to test config before any app module is imported
os.environ["SERAPH_CONFIG"] = os.path.join(os.path.dirname(__file__), "test_config.yaml")


@pytest.fixture(scope="session", autouse=True)
def setup_test_config():
    """Load test config once for the entire test session."""
    from app.core.config import load_config
    load_config()


@pytest.fixture
def client():
    """
    Sync HTTP test client with lifespan disabled (no ML warmup).
    API key auth is open mode (no keys in test config).
    """
    from app.main import app

    saved_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def noop_lifespan(a):
        yield

    app.router.lifespan_context = noop_lifespan

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc

    app.router.lifespan_context = saved_lifespan
