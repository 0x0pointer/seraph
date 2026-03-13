import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from app.core.config import settings
from app.core.limiter import limiter
from app.core.database import create_tables
from app.api.routes import auth, guardrails, scan, audit, analytics, public, connections, admin, org, teams, support, notifications, announcements, billing, integrations
import app.models.system_event  # noqa: F401 — ensure table is registered before create_all
import app.models.platform_setting  # noqa: F401
import app.models.organization  # noqa: F401
import app.models.org_invite  # noqa: F401
import app.models.team  # noqa: F401
import app.models.support_ticket  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.announcement  # noqa: F401
import app.models.billing  # noqa: F401
import app.models.user_org_membership  # noqa: F401
import app.models.connection_guardrail  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    description="Production-ready LLM guardrails platform",
    version="1.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": "Invalid request data"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
)


_MAINTENANCE_BYPASS_PREFIXES = ("/api/admin", "/api/auth", "/api/public", "/health")


_MAX_REQUEST_BODY_BYTES = 1 * 1024 * 1024  # 1 MB


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
    """Reject requests with a body larger than 1 MB."""
    if request.method in ("POST", "PUT", "PATCH"):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_REQUEST_BODY_BYTES:
            return JSONResponse(status_code=413, content={"detail": "Request body too large (max 1 MB)"})
    return await call_next(request)


@app.middleware("http")
async def maintenance_mode_middleware(request: Request, call_next):
    """Return 503 for non-admin routes when maintenance_mode is enabled."""
    if any(request.url.path.startswith(p) for p in _MAINTENANCE_BYPASS_PREFIXES):
        return await call_next(request)

    from sqlalchemy import select as _select
    from app.core.database import async_session_maker
    from app.models.platform_setting import PlatformSetting
    try:
        async with async_session_maker() as session:
            rows = {
                r.key: r.value
                for r in (
                    await session.execute(
                        _select(PlatformSetting).where(
                            PlatformSetting.key.in_(["maintenance_mode", "maintenance_message"])
                        )
                    )
                ).scalars().all()
            }
            if rows.get("maintenance_mode") == "true":
                msg = rows.get("maintenance_message") or "System maintenance in progress. Please try again shortly."
                return JSONResponse(status_code=503, content={"detail": msg})
    except Exception:
        pass  # If DB not ready yet, let request through

    return await call_next(request)

app.include_router(auth.router, prefix="/api")
app.include_router(guardrails.router, prefix="/api")
app.include_router(scan.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(public.router, prefix="/api")
app.include_router(connections.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(org.router, prefix="/api")
app.include_router(teams.router, prefix="/api")
app.include_router(support.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(announcements.router, prefix="/api")
app.include_router(billing.router, prefix="/api")
app.include_router(integrations.router, prefix="/api")


@app.on_event("startup")
async def startup():
    await create_tables()
    await _run_migrations()
    await _seed_guardrails()
    await _sync_guardrail_defaults()
    await _seed_org_memberships()
    logger.info("Database tables created/verified.")
    # Pre-load scanner models in the background so the first real request
    # doesn't pay the cold-start penalty.
    asyncio.create_task(_warmup_scanners())


async def _warmup_scanners() -> None:
    from app.services import scanner_engine
    from app.core.database import async_session_maker
    async with async_session_maker() as session:
        await scanner_engine.warmup(session)


async def _run_migrations():
    """Add new columns to existing tables without a full migration tool."""
    from sqlalchemy import text
    from app.core.database import async_session_maker

    migrations = [
        # users table
        "ALTER TABLE users ADD COLUMN full_name VARCHAR(200)",
        "ALTER TABLE users ADD COLUMN email VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN api_token VARCHAR(80)",
        # audit_logs table — connection attribution
        "ALTER TABLE audit_logs ADD COLUMN connection_id INTEGER",
        "ALTER TABLE audit_logs ADD COLUMN connection_name VARCHAR(100)",
        "ALTER TABLE audit_logs ADD COLUMN connection_environment VARCHAR(20)",
        # audit_logs table — token cost tracking
        "ALTER TABLE audit_logs ADD COLUMN input_tokens INTEGER",
        "ALTER TABLE audit_logs ADD COLUMN output_tokens INTEGER",
        "ALTER TABLE audit_logs ADD COLUMN token_cost FLOAT",
        # users table — password reset
        "ALTER TABLE users ADD COLUMN reset_token VARCHAR(80)",
        "ALTER TABLE users ADD COLUMN reset_token_expires_at DATETIME",
        # api_connections table — spend tracking
        "ALTER TABLE api_connections ADD COLUMN cost_per_input_token FLOAT DEFAULT 0",
        "ALTER TABLE api_connections ADD COLUMN cost_per_output_token FLOAT DEFAULT 0",
        "ALTER TABLE api_connections ADD COLUMN monthly_alert_spend FLOAT",
        "ALTER TABLE api_connections ADD COLUMN max_monthly_spend FLOAT",
        "ALTER TABLE api_connections ADD COLUMN month_spend FLOAT DEFAULT 0",
        "ALTER TABLE api_connections ADD COLUMN month_input_tokens INTEGER DEFAULT 0",
        "ALTER TABLE api_connections ADD COLUMN month_output_tokens INTEGER DEFAULT 0",
        "ALTER TABLE api_connections ADD COLUMN month_started_at DATETIME",
        # users table — org support
        "ALTER TABLE users ADD COLUMN org_id INTEGER",
        # api_connections table — org-wide connections
        "ALTER TABLE api_connections ADD COLUMN org_id INTEGER",
        "ALTER TABLE api_connections ADD COLUMN created_by_username VARCHAR(100)",
        # audit_logs table — per-user / per-org scoping
        "ALTER TABLE audit_logs ADD COLUMN user_id INTEGER",
        "ALTER TABLE audit_logs ADD COLUMN org_id INTEGER",
        "ALTER TABLE audit_logs ADD COLUMN team_id INTEGER",
        # users table — team membership
        "ALTER TABLE users ADD COLUMN team_id INTEGER",
        # api_connections table — team ownership
        "ALTER TABLE api_connections ADD COLUMN team_id INTEGER",
        # users table — plan & monthly usage tracking
        "ALTER TABLE users ADD COLUMN plan VARCHAR(20) DEFAULT 'free'",
        "ALTER TABLE users ADD COLUMN month_scan_count INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN month_started_at DATETIME",
        # organizations table — org-level plan
        "ALTER TABLE organizations ADD COLUMN plan VARCHAR(20) DEFAULT 'free'",
        # api_connections table — per-connection guardrail selection
        "ALTER TABLE api_connections ADD COLUMN use_custom_guardrails BOOLEAN DEFAULT 0",
        # connection_guardrails table — per-guardrail threshold override
        "ALTER TABLE connection_guardrails ADD COLUMN threshold_override FLOAT",
        # guardrail_configs table — on_fail_action (Guardrails AI-inspired)
        "ALTER TABLE guardrail_configs ADD COLUMN on_fail_action VARCHAR(20) DEFAULT 'block'",
        # audit_logs table — on_fail_action metadata
        "ALTER TABLE audit_logs ADD COLUMN on_fail_actions JSON",
        "ALTER TABLE audit_logs ADD COLUMN fix_applied BOOLEAN DEFAULT 0",
        "ALTER TABLE audit_logs ADD COLUMN reask_context JSON",
        # Stripe billing columns
        "ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN stripe_subscription_id VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN subscription_status VARCHAR(20) DEFAULT 'inactive'",
        "ALTER TABLE organizations ADD COLUMN stripe_customer_id VARCHAR(255)",
        "ALTER TABLE organizations ADD COLUMN stripe_subscription_id VARCHAR(255)",
        "ALTER TABLE organizations ADD COLUMN subscription_status VARCHAR(20) DEFAULT 'inactive'",
        "ALTER TABLE invoices ADD COLUMN stripe_invoice_id VARCHAR(255)",
        "ALTER TABLE invoices ADD COLUMN stripe_subscription_id VARCHAR(255)",
        "ALTER TABLE invoices ADD COLUMN hosted_invoice_url TEXT",
    ]
    async with async_session_maker() as session:
        for stmt in migrations:
            try:
                await session.execute(text(stmt))
                await session.commit()
            except Exception:
                # Column already exists — safe to ignore
                await session.rollback()


async def _sync_guardrail_defaults():
    """
    One-time migration: update existing guardrail records to match the current catalog defaults.
    Uses a platform_settings marker so it only ever runs once, preserving future user edits.
    """
    from sqlalchemy import select as _select
    from app.models.guardrail import GuardrailConfig
    from app.models.platform_setting import PlatformSetting
    from app.core.guardrail_catalog import GUARDRAIL_CATALOG
    from app.core.database import async_session_maker
    from app.services.scanner_engine import invalidate_cache

    async with async_session_maker() as session:
        # Check for the latest migration marker (bump version to re-run after catalog changes)
        marker = (await session.execute(
            _select(PlatformSetting).where(PlatformSetting.key == "guardrails_defaults_v11")
        )).scalar_one_or_none()
        if marker:
            return

        all_gs = (await session.execute(_select(GuardrailConfig))).scalars().all()
        updated = 0
        for g in all_gs:
            entry = next(
                (c for c in GUARDRAIL_CATALOG
                 if c["scanner_type"] == g.scanner_type and c["direction"] == g.direction),
                None,
            )
            if entry:
                # v11: remove false-positive output BanSubstrings ("access granted", "authorization confirmed")
                g.params = entry["params"]
                if entry.get("on_fail_action"):
                    g.on_fail_action = entry["on_fail_action"]
                session.add(g)
                updated += 1

        session.add(PlatformSetting(key="guardrails_defaults_v11", value="applied"))
        await session.commit()
        invalidate_cache()
        if updated:
            logger.info("Synced %d guardrail configs to v11 defaults (false-positive fix for output BanSubstrings).", updated)


async def _seed_org_memberships():
    """Backfill user_org_memberships from existing users.org_id values."""
    from sqlalchemy import select as _select
    from app.models.user import User as _User
    from app.models.user_org_membership import UserOrgMembership
    from app.core.database import async_session_maker

    async with async_session_maker() as session:
        users_with_org = (await session.execute(
            _select(_User).where(_User.org_id != None)  # noqa: E711
        )).scalars().all()

        for user in users_with_org:
            existing = (await session.execute(
                _select(UserOrgMembership).where(
                    UserOrgMembership.user_id == user.id,
                    UserOrgMembership.org_id == user.org_id,
                )
            )).scalar_one_or_none()
            if not existing:
                session.add(UserOrgMembership(
                    user_id=user.id,
                    org_id=user.org_id,
                    role=user.role if user.role in ("org_admin", "viewer") else "viewer",
                ))
        await session.commit()


async def _seed_guardrails():
    """Insert any guardrail configs that are missing from the database."""
    from sqlalchemy import select as _select
    from app.models.guardrail import GuardrailConfig
    from app.core.guardrail_catalog import GUARDRAIL_CATALOG
    from app.core.database import async_session_maker

    async with async_session_maker() as session:
        result = await session.execute(_select(GuardrailConfig))
        existing_keys = {(g.scanner_type, g.direction) for g in result.scalars().all()}
        added = 0
        for config in GUARDRAIL_CATALOG:
            if (config["scanner_type"], config["direction"]) not in existing_keys:
                session.add(GuardrailConfig(**config))
                added += 1
        if added:
            await session.commit()
            logger.info("Auto-seeded %d missing guardrail configs.", added)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}
