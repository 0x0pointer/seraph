import asyncio
import logging
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import load_config, reload_config, get_config
from app.core.auth import verify_api_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load config at import time
load_config()


@asynccontextmanager
async def lifespan(application: FastAPI):
    # ── startup ──────────────────────────────────────────────────────────────
    config = get_config()
    log_level = getattr(logging, config.logging.level.upper(), logging.INFO)
    logging.getLogger().setLevel(log_level)

    logger.info("Seraph starting — listen=%s", config.listen)

    try:
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGHUP, _handle_sighup)
    except (NotImplementedError, AttributeError):
        pass  # Windows doesn't support SIGHUP

    warmup_task = asyncio.create_task(_warmup_scanners())

    yield

    warmup_task.cancel()

    # ── shutdown ─────────────────────────────────────────────────────────────
    from app.services import audit_logger
    await audit_logger.close()


app = FastAPI(
    title="Seraph",
    description="YAML-configured LLM guardrail proxy",
    version="2.0.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": "Invalid request data"})


_MAX_REQUEST_BODY_BYTES = 4 * 1024 * 1024  # 4 MB


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Attach security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def limit_body_size_middleware(request: Request, call_next):
    """Reject requests with a body larger than 4 MB."""
    if request.method in ("POST", "PUT", "PATCH"):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_REQUEST_BODY_BYTES:
            return JSONResponse(status_code=413, content={"detail": "Request body too large (max 4 MB)"})
    return await call_next(request)


# ── Routes ────────────────────────────────────────────────────────────────────

from typing import Annotated  # noqa: E402
from fastapi import Depends  # noqa: E402

ReloadApiKey = Annotated[str | None, Depends(verify_api_key)]


@app.get("/health")
async def health():
    return {"status": "ok", "app": "Seraph"}


@app.post("/reload")
async def reload(api_key: ReloadApiKey):
    """Hot-reload config and scanners."""
    from app.services.scanner_engine import reload_scanners
    reload_config()
    reload_scanners()
    return {"status": "reloaded"}


# Proxy catch-all must be registered LAST so /health and /reload match first
from app.api.routes import proxy  # noqa: E402

app.include_router(proxy.router)



def _handle_sighup():
    """Handle SIGHUP for config hot-reload."""
    from app.services.scanner_engine import reload_scanners
    reload_config()
    reload_scanners()
    logger.info("SIGHUP received — config and scanners reloaded")


async def _warmup_scanners() -> None:
    from app.services import scanner_engine
    await scanner_engine.warmup()
