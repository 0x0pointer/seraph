"""
Simple API key authentication for the guardrail proxy.

Checks Bearer token against config.api_keys list.
If api_keys is empty, all requests are allowed (open mode).
"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_config

_bearer_scheme = HTTPBearer(auto_error=False)


def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str | None:
    """
    FastAPI dependency that validates the Bearer token against configured API keys.
    Returns the API key if valid, or None if no keys are configured (open mode).
    """
    config = get_config()

    # Open mode: no API keys configured → allow all requests
    if not config.api_keys:
        return None

    if credentials is None:
        raise HTTPException(status_code=403, detail="Missing API key")

    if credentials.credentials not in config.api_keys:
        raise HTTPException(status_code=403, detail="Invalid API key")

    return credentials.credentials
