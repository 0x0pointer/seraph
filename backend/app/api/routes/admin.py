import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core.database import get_session
from app.core.security import create_access_token, hash_password
from app.models.api_connection import ApiConnection
from app.models.audit_log import AuditLog
from app.models.guardrail import GuardrailConfig
from app.models.org_invite import OrgInvite
from app.models.organization import Organization
from app.models.platform_setting import PlatformSetting
from app.models.system_event import SystemEvent
from app.models.user import User
from app.services.event_service import log_event


def _ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateUserRequest(BaseModel):
    username: str
    password: str
    full_name: str | None = None
    email: str | None = None
    role: str = "viewer"


class ChangeRoleRequest(BaseModel):
    role: str


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return current_user


async def require_admin_or_support(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("admin", "support"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator or support staff access required",
        )
    return current_user


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_admin_stats(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Platform-wide stats for the admin dashboard."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total_users = (await session.execute(select(func.count(User.id)))).scalar_one()
    admin_users = (
        await session.execute(select(func.count(User.id)).where(User.role == "admin"))
    ).scalar_one()
    new_users_week = (
        await session.execute(
            select(func.count(User.id)).where(User.created_at >= week_ago)
        )
    ).scalar_one()

    total_scans = (await session.execute(select(func.count(AuditLog.id)))).scalar_one()
    scans_today = (
        await session.execute(
            select(func.count(AuditLog.id)).where(AuditLog.created_at >= today_start)
        )
    ).scalar_one()
    total_violations = (
        await session.execute(
            select(func.count(AuditLog.id)).where(AuditLog.is_valid == False)  # noqa: E712
        )
    ).scalar_one()
    violations_today = (
        await session.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.is_valid == False,  # noqa: E712
                AuditLog.created_at >= today_start,
            )
        )
    ).scalar_one()

    total_guardrails = (
        await session.execute(select(func.count(GuardrailConfig.id)))
    ).scalar_one()
    active_guardrails = (
        await session.execute(
            select(func.count(GuardrailConfig.id)).where(GuardrailConfig.is_active == True)  # noqa: E712
        )
    ).scalar_one()

    total_connections = (
        await session.execute(select(func.count(ApiConnection.id)))
    ).scalar_one()
    blocked_connections = (
        await session.execute(
            select(func.count(ApiConnection.id)).where(ApiConnection.status == "blocked")
        )
    ).scalar_one()

    # Total token spend tracked across all connections
    total_spend_result = await session.execute(
        select(func.coalesce(func.sum(ApiConnection.month_spend), 0.0))
    )
    total_month_spend: float = total_spend_result.scalar_one()

    pass_rate = (
        round((1 - total_violations / total_scans) * 100, 1) if total_scans > 0 else 100.0
    )
    pass_rate_today = (
        round((1 - violations_today / scans_today) * 100, 1) if scans_today > 0 else 100.0
    )

    return {
        "total_users": total_users,
        "admin_users": admin_users,
        "viewer_users": total_users - admin_users,
        "new_users_week": new_users_week,
        "total_scans": total_scans,
        "scans_today": scans_today,
        "total_violations": total_violations,
        "violations_today": violations_today,
        "pass_rate": pass_rate,
        "pass_rate_today": pass_rate_today,
        "total_guardrails": total_guardrails,
        "active_guardrails": active_guardrails,
        "total_connections": total_connections,
        "blocked_connections": blocked_connections,
        "total_month_spend": round(total_month_spend, 4),
    }


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    # Fetch users + their connection counts in one pass
    users_result = await session.execute(select(User).order_by(User.created_at.desc()))
    users = users_result.scalars().all()

    # Count connections per user
    conn_counts_result = await session.execute(
        select(ApiConnection.user_id, func.count(ApiConnection.id))
        .group_by(ApiConnection.user_id)
    )
    conn_counts: dict[int, int] = {row[0]: row[1] for row in conn_counts_result.all()}

    # Total requests per user via their connections
    req_counts_result = await session.execute(
        select(ApiConnection.user_id, func.coalesce(func.sum(ApiConnection.total_requests), 0))
        .group_by(ApiConnection.user_id)
    )
    req_counts: dict[int, int] = {row[0]: row[1] for row in req_counts_result.all()}

    # Last active per user (latest connection.last_active_at)
    last_active_result = await session.execute(
        select(ApiConnection.user_id, func.max(ApiConnection.last_active_at))
        .group_by(ApiConnection.user_id)
    )
    last_active: dict[int, str | None] = {
        row[0]: row[1].isoformat() if row[1] else None
        for row in last_active_result.all()
    }

    # Org names for users that belong to an org
    org_ids = list({u.org_id for u in users if u.org_id})
    org_names: dict[int, str] = {}
    if org_ids:
        orgs_result = await session.execute(
            select(Organization).where(Organization.id.in_(org_ids))
        )
        for org in orgs_result.scalars().all():
            org_names[org.id] = org.name

    return [
        {
            "id": u.id,
            "username": u.username,
            "full_name": u.full_name,
            "email": u.email,
            "role": u.role,
            "org_id": u.org_id,
            "org_name": org_names.get(u.org_id) if u.org_id else None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "connection_count": conn_counts.get(u.id, 0),
            "total_requests": req_counts.get(u.id, 0),
            "last_active_at": last_active.get(u.id),
        }
        for u in users
    ]


@router.post("/users", status_code=201)
async def create_user(
    data: CreateUserRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    if len(data.username.strip()) < 2:
        raise HTTPException(status_code=422, detail="Username must be at least 2 characters")
    if len(data.password) < 12:
        raise HTTPException(status_code=422, detail="Password must be at least 12 characters")
    if data.role not in ("admin", "support", "org_admin", "viewer"):
        raise HTTPException(status_code=422, detail="Role must be one of: admin, support, org_admin, viewer")

    existing = (
        await session.execute(select(User).where(User.username == data.username.strip()))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")

    if data.email:
        email_taken = (
            await session.execute(select(User).where(User.email == data.email.lower().strip()))
        ).scalar_one_or_none()
        if email_taken:
            raise HTTPException(status_code=409, detail="Email already in use")

    user = User(
        username=data.username.strip(),
        full_name=data.full_name.strip() if data.full_name else None,
        email=data.email.lower().strip() if data.email else None,
        hashed_password=hash_password(data.password),
        role=data.role,
    )
    session.add(user)
    try:
        await session.flush()  # get user.id before commit
    except Exception:
        raise HTTPException(status_code=409, detail="Username or email already in use")
    await log_event(session, event_type="user.created",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="user", target_id=user.id, target_name=user.username,
        details={"role": user.role, "email": user.email, "full_name": user.full_name},
        ip_address=_ip(request))
    await session.commit()
    await session.refresh(user)
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role,
        "created_at": user.created_at.isoformat(),
        "connection_count": 0,
        "total_requests": 0,
        "last_active_at": None,
    }


@router.patch("/users/{user_id}/role")
async def change_user_role(
    user_id: int,
    data: ChangeRoleRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    if data.role not in ("admin", "support", "org_admin", "viewer"):
        raise HTTPException(status_code=422, detail="Role must be one of: admin, support, org_admin, viewer")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    old_role = user.role
    user.role = data.role
    await log_event(session, event_type="user.role_changed",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="user", target_id=user.id, target_name=user.username,
        details={"old_role": old_role, "new_role": data.role},
        ip_address=_ip(request))
    await session.commit()
    return {"id": user.id, "role": user.role}


@router.patch("/users/{user_id}/password")
async def reset_user_password(
    user_id: int,
    data: dict,
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    new_password = data.get("password", "")
    if len(new_password) < 6:
        raise HTTPException(status_code=422, detail="Password must be at least 6 characters")

    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = hash_password(new_password)
    await log_event(session, event_type="user.password_reset",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="user", target_id=user.id, target_name=user.username,
        details={"method": "admin_override"},
        ip_address=_ip(request))
    await session.commit()
    return {"ok": True}


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await log_event(session, event_type="user.deleted",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="user", target_id=user.id, target_name=user.username,
        details={"role": user.role, "email": user.email},
        ip_address=_ip(request))
    await session.delete(user)
    await session.commit()


# ── Connections (all users) ───────────────────────────────────────────────────

@router.get("/connections")
async def list_all_connections(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    """All API connections across every user — admin view."""
    result = await session.execute(
        select(ApiConnection, User.username, User.full_name)
        .join(User, ApiConnection.user_id == User.id)
        .order_by(ApiConnection.last_active_at.desc().nulls_last(), ApiConnection.created_at.desc())
    )
    rows = result.all()
    return [
        {
            "id": conn.id,
            "name": conn.name,
            "environment": conn.environment,
            "status": conn.status,
            "user_id": conn.user_id,
            "username": username,
            "full_name": full_name,
            "total_requests": conn.total_requests,
            "total_violations": conn.total_violations,
            "month_spend": conn.month_spend,
            "monthly_alert_spend": conn.monthly_alert_spend,
            "max_monthly_spend": conn.max_monthly_spend,
            "alert_enabled": conn.alert_enabled,
            "alert_threshold": conn.alert_threshold,
            "created_at": conn.created_at.isoformat() if conn.created_at else None,
            "last_active_at": conn.last_active_at.isoformat() if conn.last_active_at else None,
        }
        for conn, username, full_name in rows
    ]


# ── Recent activity (platform-wide) ──────────────────────────────────────────

@router.get("/activity")
async def get_recent_activity(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Last N audit entries, all users, with summary fields."""
    result = await session.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    )
    logs = result.scalars().all()

    def max_risk(scanner_results: dict) -> float:
        vals = [v for v in scanner_results.values() if isinstance(v, (int, float))]
        return max(vals) if vals else 0.0

    return [
        {
            "id": log.id,
            "direction": log.direction,
            "is_valid": log.is_valid,
            "violation_scanners": log.violation_scanners,
            "connection_name": log.connection_name,
            "connection_environment": log.connection_environment,
            "ip_address": log.ip_address,
            "scanner_results": log.scanner_results or {},
            "max_risk_score": max_risk(log.scanner_results or {}),
            "token_cost": log.token_cost,
            "preview": (log.raw_text or "")[:80],
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


# ── Guardrails overview ───────────────────────────────────────────────────────

@router.get("/guardrails")
async def list_all_guardrails(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    """All guardrail configs — admin view."""
    result = await session.execute(
        select(GuardrailConfig).order_by(GuardrailConfig.direction, GuardrailConfig.order)
    )
    guardrails = result.scalars().all()
    return [
        {
            "id": g.id,
            "name": g.name,
            "scanner_type": g.scanner_type,
            "direction": g.direction,
            "is_active": g.is_active,
            "order": g.order,
        }
        for g in guardrails
    ]


# ── Toggle a guardrail (admin) ────────────────────────────────────────────────

@router.patch("/guardrails/{guardrail_id}/toggle")
async def toggle_guardrail(
    guardrail_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    g = (
        await session.execute(select(GuardrailConfig).where(GuardrailConfig.id == guardrail_id))
    ).scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="Guardrail not found")
    g.is_active = not g.is_active
    await log_event(session, event_type="guardrail.toggled",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="guardrail", target_id=g.id, target_name=g.name,
        details={"is_active": g.is_active, "scanner_type": g.scanner_type, "direction": g.direction},
        ip_address=_ip(request))
    await session.commit()
    return {"id": g.id, "is_active": g.is_active}


# ── Top violated scanners ─────────────────────────────────────────────────────

@router.get("/top-violations")
async def get_top_violations(
    limit: int = Query(8, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Most-triggered scanners across all users."""
    from app.services import audit_service
    return await audit_service.get_top_violations(session, limit=limit)


# ── Platform-wide audit log (paginated) ───────────────────────────────────────

@router.get("/audit-logs")
async def get_admin_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    direction: str = Query("all"),   # all | input | output
    status: str = Query("all"),      # all | pass | block
    search: str = Query("", max_length=200),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Paginated platform-wide audit log — admin view."""
    stmt = select(AuditLog)

    if direction in ("input", "output"):
        stmt = stmt.where(AuditLog.direction == direction)
    if status == "pass":
        stmt = stmt.where(AuditLog.is_valid == True)   # noqa: E712
    elif status == "block":
        stmt = stmt.where(AuditLog.is_valid == False)  # noqa: E712
    if search.strip():
        stmt = stmt.where(AuditLog.raw_text.ilike(f"%{search.strip()}%"))

    total: int = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()

    rows = (
        await session.execute(
            stmt.order_by(AuditLog.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
    ).scalars().all()

    def max_risk(sr: dict) -> float:
        vals = [v for v in (sr or {}).values() if isinstance(v, (int, float))]
        return max(vals) if vals else 0.0

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": log.id,
                "direction": log.direction,
                "is_valid": log.is_valid,
                "raw_text": log.raw_text,
                "scanner_results": log.scanner_results,
                "violation_scanners": log.violation_scanners,
                "connection_name": log.connection_name,
                "connection_environment": log.connection_environment,
                "ip_address": log.ip_address,
                "input_tokens": log.input_tokens,
                "output_tokens": log.output_tokens,
                "token_cost": log.token_cost,
                "max_risk_score": max_risk(log.scanner_results),
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in rows
        ],
    }


# ── System events (paginated) ─────────────────────────────────────────────────

@router.get("/events")
async def get_admin_events(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    event_type: str = Query("all"),
    actor: str = Query(""),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Paginated system event log — who did what, when."""
    stmt = select(SystemEvent)

    if event_type != "all":
        stmt = stmt.where(SystemEvent.event_type == event_type)
    if actor.strip():
        stmt = stmt.where(SystemEvent.actor_username.ilike(f"%{actor.strip()}%"))

    total: int = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()

    rows = (
        await session.execute(
            stmt.order_by(SystemEvent.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
    ).scalars().all()

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "actor_id": e.actor_id,
                "actor_username": e.actor_username,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "target_name": e.target_name,
                "details": e.details,
                "ip_address": e.ip_address,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ],
    }


# ── Impersonate user ──────────────────────────────────────────────────────────

@router.post("/users/{user_id}/impersonate")
async def impersonate_user(
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin_or_support),
):
    """Generate a short-lived JWT so an admin or support agent can act as another user."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot impersonate yourself")

    target = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Support staff cannot impersonate admins or other support accounts
    if current_user.role == "support" and target.role in ("admin", "support"):
        raise HTTPException(status_code=403, detail="Support staff cannot impersonate admin or support accounts")

    token = create_access_token({"sub": target.username, "role": target.role, "impersonated_by": current_user.username})
    await log_event(
        session,
        event_type="user.impersonated",
        actor_id=current_user.id,
        actor_username=current_user.username,
        target_type="user",
        target_id=target.id,
        target_name=target.username,
        details={"note": "Admin impersonation session started"},
        ip_address=_ip(request),
    )
    await session.commit()
    return {"access_token": token, "username": target.username, "full_name": target.full_name}


# ── Platform settings ─────────────────────────────────────────────────────────

_ALLOWED_SETTING_KEYS = {
    "company_name",
    "maintenance_mode",       # "true" | "false"
    "maintenance_message",    # custom message shown during maintenance
    "signup_enabled",         # "true" | "false" — allow new registrations
    "chatbot_enabled",        # "true" | "false" — chatbot demo active
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "smtp_from",
    "smtp_tls",               # "true" | "false"
}


@router.get("/platform")
async def get_platform_settings(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Return all platform-wide settings."""
    result = await session.execute(select(PlatformSetting))
    return {row.key: row.value for row in result.scalars().all()}


@router.put("/platform")
async def update_platform_settings(
    data: dict,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    """Update platform-wide settings (admin only)."""
    _BOOLEAN_KEYS = {"maintenance_mode", "signup_enabled", "chatbot_enabled", "smtp_tls"}

    for key, value in data.items():
        if key not in _ALLOWED_SETTING_KEYS:
            continue

        str_value = str(value).strip()

        # Validate boolean settings
        if key in _BOOLEAN_KEYS and str_value not in ("true", "false"):
            raise HTTPException(status_code=422, detail=f"'{key}' must be 'true' or 'false'")

        # Validate smtp_port is a valid port number
        if key == "smtp_port":
            try:
                port = int(str_value)
                if not (1 <= port <= 65535):
                    raise ValueError
            except ValueError:
                raise HTTPException(status_code=422, detail="'smtp_port' must be an integer between 1 and 65535")

        existing = (
            await session.execute(select(PlatformSetting).where(PlatformSetting.key == key))
        ).scalar_one_or_none()
        if existing:
            existing.value = str_value
            existing.updated_at = datetime.now(timezone.utc)
        else:
            session.add(PlatformSetting(key=key, value=str_value))
    await session.commit()
    return {"ok": True}



# ── Data exports ───────────────────────────────────────────────────────────────


@router.get("/export/users")
async def export_users_csv(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Download all users as a CSV file."""
    users = (await session.execute(select(User).order_by(User.created_at.desc()))).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "username", "full_name", "email", "role", "plan", "org_id", "created_at", "month_scan_count"])
    for u in users:
        writer.writerow([
            u.id, u.username, u.full_name or "", u.email or "",
            u.role, u.plan or "free", u.org_id or "",
            u.created_at.isoformat() if u.created_at else "",
            u.month_scan_count or 0,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=seraph-users.csv"},
    )


@router.get("/export/audit-logs")
async def export_audit_logs_csv(
    limit: int = Query(1000, ge=1, le=10000),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Download recent audit logs as a CSV file."""
    logs = (await session.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    )).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "direction", "is_valid", "violation_scanners", "max_risk_score", "ip_address", "connection_name", "input_tokens", "output_tokens", "token_cost", "created_at"])
    for log in logs:
        writer.writerow([
            log.id, log.direction, log.is_valid,
            "|".join(log.violation_scanners or []),
            getattr(log, "max_risk_score", ""),
            log.ip_address or "",
            getattr(log, "connection_name", "") or "",
            getattr(log, "input_tokens", "") or "",
            getattr(log, "output_tokens", "") or "",
            getattr(log, "token_cost", "") or "",
            log.created_at.isoformat() if log.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=seraph-audit-logs.csv"},
    )


# ── Organization management (superadmin) ──────────────────────────────────────

class CreateOrgRequest(BaseModel):
    name: str


class AssignOrgRequest(BaseModel):
    org_id: int | None
    role: str | None = None  # optional role override


@router.get("/orgs")
async def list_all_orgs(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    """List all organizations with member and team counts."""
    from app.models.team import Team
    orgs_result = await session.execute(select(Organization).order_by(Organization.created_at.desc()))
    orgs = orgs_result.scalars().all()

    # Member count per org
    counts_result = await session.execute(
        select(User.org_id, func.count(User.id))
        .where(User.org_id != None)  # noqa: E711
        .group_by(User.org_id)
    )
    counts: dict[int, int] = {row[0]: row[1] for row in counts_result.all()}

    # Team count per org
    team_counts_result = await session.execute(
        select(Team.org_id, func.count(Team.id)).group_by(Team.org_id)
    )
    team_counts: dict[int, int] = {row[0]: row[1] for row in team_counts_result.all()}

    # Owner usernames
    owner_ids = [o.owner_id for o in orgs if o.owner_id]
    owners: dict[int, str] = {}
    if owner_ids:
        owner_result = await session.execute(select(User).where(User.id.in_(owner_ids)))
        for u in owner_result.scalars().all():
            owners[u.id] = u.username

    return [
        {
            "id": org.id,
            "name": org.name,
            "plan": org.plan or "free",
            "created_at": org.created_at.isoformat() if org.created_at else None,
            "owner_id": org.owner_id,
            "owner_username": owners.get(org.owner_id) if org.owner_id else None,
            "member_count": counts.get(org.id, 0),
            "team_count": team_counts.get(org.id, 0),
        }
        for org in orgs
    ]


@router.get("/orgs/{org_id}/teams")
async def list_org_teams(
    org_id: int,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    """List all teams in an organization with member counts."""
    from app.models.team import Team
    teams_result = await session.execute(
        select(Team).where(Team.org_id == org_id).order_by(Team.created_at)
    )
    teams = teams_result.scalars().all()

    # Member count per team
    if teams:
        team_ids = [t.id for t in teams]
        mc_result = await session.execute(
            select(User.team_id, func.count(User.id))
            .where(User.team_id.in_(team_ids))
            .group_by(User.team_id)
        )
        mc: dict[int, int] = {row[0]: row[1] for row in mc_result.all()}
    else:
        mc = {}

    return [
        {
            "id": t.id,
            "name": t.name,
            "created_by_username": t.created_by_username,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "member_count": mc.get(t.id, 0),
        }
        for t in teams
    ]


@router.post("/orgs", status_code=201)
async def create_org(
    data: CreateOrgRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    """Create a new organization."""
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Organization name must be at least 2 characters")

    org = Organization(name=name, owner_id=current_user.id)
    session.add(org)
    await session.flush()
    await log_event(session, event_type="org.created",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="org", target_id=org.id, target_name=org.name,
        details={})
    await session.commit()
    await session.refresh(org)
    return {"id": org.id, "name": org.name, "created_at": org.created_at.isoformat(), "member_count": 0}


@router.delete("/orgs/{org_id}", status_code=204)
async def delete_org(
    org_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    """Delete an organization (removes all member org assignments)."""
    org = (await session.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Unassign all members
    members_result = await session.execute(select(User).where(User.org_id == org_id))
    for member in members_result.scalars().all():
        member.org_id = None
        if member.role == "org_admin":
            member.role = "viewer"

    await log_event(session, event_type="org.deleted",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="org", target_id=org.id, target_name=org.name,
        details={})
    await session.delete(org)
    await session.commit()


@router.get("/orgs/{org_id}/members")
async def list_org_members_admin(
    org_id: int,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    """List all members of a specific organization."""
    result = await session.execute(select(User).where(User.org_id == org_id).order_by(User.created_at.desc()))
    return [
        {"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email,
         "role": u.role, "created_at": u.created_at.isoformat() if u.created_at else None}
        for u in result.scalars().all()
    ]


@router.patch("/users/{user_id}/org")
async def assign_user_org(
    user_id: int,
    data: AssignOrgRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    """Assign or unassign a user to/from an organization."""
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.org_id is not None:
        org = (await session.execute(select(Organization).where(Organization.id == data.org_id))).scalar_one_or_none()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

    from app.models.user_org_membership import UserOrgMembership
    from sqlalchemy import delete as _delete

    effective_role = data.role if (data.role and data.role in ("org_admin", "viewer", "admin", "support")) else "viewer"

    if data.org_id is not None:
        # Upsert membership record
        existing_membership = (await session.execute(
            select(UserOrgMembership).where(
                UserOrgMembership.user_id == user.id,
                UserOrgMembership.org_id == data.org_id,
            )
        )).scalar_one_or_none()
        if existing_membership:
            existing_membership.role = effective_role
        else:
            session.add(UserOrgMembership(user_id=user.id, org_id=data.org_id, role=effective_role))
    else:
        # Remove active org's membership record
        if user.org_id:
            await session.execute(
                _delete(UserOrgMembership).where(
                    UserOrgMembership.user_id == user.id,
                    UserOrgMembership.org_id == user.org_id,
                )
            )

    user.org_id = data.org_id
    if data.role and data.role in ("org_admin", "viewer", "admin", "support"):
        user.role = data.role
    elif data.org_id is None and user.role == "org_admin":
        user.role = "viewer"

    await log_event(session, event_type="user.org_assigned",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="user", target_id=user.id, target_name=user.username,
        details={"org_id": data.org_id, "role": user.role})
    await session.commit()
    return {"id": user.id, "username": user.username, "org_id": user.org_id, "role": user.role}
