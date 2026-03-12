import asyncio
import hashlib
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.limiter import limiter
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import ApiTokenResponse, LoginRequest, RegisterRequest, TokenResponse, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer()

_RESET_TOKEN_EXPIRE_HOURS = 1


# ── Email helper ───────────────────────────────────────────────────────────────

def _send_email_sync(to: str, subject: str, html: str) -> None:
    """Send a single email via SMTP. Runs in a thread pool (blocking)."""
    if not settings.smtp_host:
        return  # email not configured — silently skip

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))

    if settings.smtp_tls:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from, to, msg.as_string())
    else:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx, timeout=10) as server:
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from, to, msg.as_string())


async def _send_email(to: str, subject: str, html: str) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_email_sync, to, subject, html)


def _reset_password_email(username: str, token: str) -> str:
    link = f"{settings.frontend_url}/reset-password?token={token}"
    return f"""
    <div style="font-family:sans-serif;max-width:480px;margin:40px auto;color:#e2e8f0;background:#0d1426;border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:32px;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:24px;">
        <span style="width:16px;height:16px;border-radius:3px;background:#515594;display:inline-block;"></span>
        <span style="font-weight:600;font-size:14px;color:#fff;">SKF Guard</span>
      </div>
      <h2 style="margin:0 0 8px;font-size:18px;color:#fff;">Reset your password</h2>
      <p style="margin:0 0 24px;font-size:13px;color:#94a3b8;line-height:1.6;">
        Hi <strong style="color:#e2e8f0;">{username}</strong>, we received a request to reset your password.
        Click the button below — the link expires in {_RESET_TOKEN_EXPIRE_HOURS}&nbsp;hour.
      </p>
      <a href="{link}" style="display:inline-block;background:#515594;color:#0A0F1F;padding:10px 24px;border-radius:6px;font-size:13px;font-weight:600;text-decoration:none;">
        Reset password
      </a>
      <p style="margin:24px 0 0;font-size:11px;color:#475569;">
        If you didn't request this, you can safely ignore this email. Your password will not change.
      </p>
      <p style="margin:8px 0 0;font-size:11px;color:#334155;word-break:break-all;">
        {link}
      </p>
    </div>
    """


def _username_reminder_email(username: str) -> str:
    return f"""
    <div style="font-family:sans-serif;max-width:480px;margin:40px auto;color:#e2e8f0;background:#0d1426;border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:32px;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:24px;">
        <span style="width:16px;height:16px;border-radius:3px;background:#515594;display:inline-block;"></span>
        <span style="font-weight:600;font-size:14px;color:#fff;">SKF Guard</span>
      </div>
      <h2 style="margin:0 0 8px;font-size:18px;color:#fff;">Your username</h2>
      <p style="margin:0 0 16px;font-size:13px;color:#94a3b8;line-height:1.6;">
        You requested a reminder of your SKF Guard username.
      </p>
      <div style="background:#0A0F1F;border-radius:6px;padding:12px 16px;margin-bottom:24px;">
        <span style="font-family:monospace;font-size:16px;color:#515594;">{username}</span>
      </div>
      <p style="margin:0;font-size:11px;color:#475569;">
        If you didn't request this, you can safely ignore this email.
      </p>
    </div>
    """

_API_TOKEN_PREFIX = "ts_live_"
_CONN_KEY_PREFIX = "ts_conn_"


def _generate_api_token() -> str:
    return _API_TOKEN_PREFIX + secrets.token_hex(32)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    token = credentials.credentials

    # Connection key path (ts_conn_...) — used by external clients via API connections
    if token.startswith(_CONN_KEY_PREFIX):
        from app.models.api_connection import ApiConnection
        result = await session.execute(
            select(ApiConnection).where(ApiConnection.api_key == token)
        )
        conn = result.scalar_one_or_none()
        if not conn:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid connection key")
        if conn.status == "blocked":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This connection has been blocked due to an alert threshold being reached",
            )
        # Store connection on request state so scan routes can update metrics
        request.state.api_connection = conn
        user_result = await session.execute(select(User).where(User.id == conn.user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Connection user not found")
        return user

    # Clear connection state for non-connection requests
    request.state.api_connection = None

    # Static API token path (ts_live_...)
    if token.startswith(_API_TOKEN_PREFIX):
        result = await session.execute(select(User).where(User.api_token == token))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
        return user

    # JWT path
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    # Mark impersonation sessions so routes can bypass user-level restrictions
    request.state.is_impersonation = "impersonated_by" in payload
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, data: LoginRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.hashed_password):
        from app.services.event_service import log_event
        await log_event(session, event_type="auth.login_failed",
            actor_id=None, actor_username=data.username,
            target_type="user", target_id=None, target_name=data.username,
            details={"reason": "invalid_credentials"},
            ip_address=request.client.host if request.client else None)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    token = create_access_token({"sub": user.username, "role": user.role})
    return TokenResponse(access_token=token)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour")
async def register(request: Request, data: RegisterRequest, session: AsyncSession = Depends(get_session)):
    # Verify Cloudflare Turnstile
    import httpx
    from app.core.config import settings as app_settings
    async with httpx.AsyncClient() as client:
        ts = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={
                "secret": app_settings.turnstile_secret_key,
                "response": data.turnstile_token,
                "remoteip": request.client.host if request.client else None,
            },
        )
    if not ts.json().get("success"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CAPTCHA verification failed. Please try again.")

    if len(data.full_name.strip()) < 2:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Please enter your full name")
    if "@" not in data.email or "." not in data.email.split("@")[-1]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid email address")
    if len(data.username.strip()) < 3:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Username must be at least 3 characters")

    existing = await session.execute(select(User).where(User.username == data.username.strip()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username or email already registered")
    existing_email = await session.execute(select(User).where(User.email == data.email.lower().strip()))
    if existing_email.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username or email already registered")

    user = User(
        username=data.username.strip(),
        full_name=data.full_name.strip(),
        email=data.email.lower().strip(),
        hashed_password=hash_password(data.password),
        role="viewer",
    )
    session.add(user)
    await session.flush()
    from app.services.event_service import log_event
    await log_event(session, event_type="user.registered",
        actor_id=user.id, actor_username=user.username,
        target_type="user", target_id=user.id, target_name=user.username,
        details={"role": "viewer", "email": user.email},
        ip_address=request.client.host if request.client else None)
    await session.commit()
    await session.refresh(user)
    token = create_access_token({"sub": user.username, "role": user.role})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserRead)
async def me(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    from app.models.user_org_membership import UserOrgMembership
    from app.models.organization import Organization

    memberships = (await session.execute(
        select(UserOrgMembership).where(UserOrgMembership.user_id == current_user.id)
    )).scalars().all()

    orgs = []
    for m in memberships:
        org = (await session.execute(
            select(Organization).where(Organization.id == m.org_id)
        )).scalar_one_or_none()
        if org:
            orgs.append({"id": org.id, "name": org.name, "role": m.role})

    return {
        "id": current_user.id,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "email": current_user.email,
        "role": current_user.role,
        "org_id": current_user.org_id,
        "team_id": current_user.team_id,
        "created_at": current_user.created_at,
        "orgs": orgs,
    }


class SwitchOrgRequest(BaseModel):
    org_id: int | None  # None = switch to personal (no org)


@router.patch("/switch-org")
async def switch_org(
    data: SwitchOrgRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Switch the active organization context. User must be a member of the target org."""
    from app.models.user_org_membership import UserOrgMembership

    if data.org_id is not None:
        membership = (await session.execute(
            select(UserOrgMembership).where(
                UserOrgMembership.user_id == current_user.id,
                UserOrgMembership.org_id == data.org_id,
            )
        )).scalar_one_or_none()
        if not membership:
            raise HTTPException(status_code=403, detail="Not a member of that organization")
        current_user.org_id = data.org_id
        # Update role to reflect their role in the target org (superadmins are unchanged)
        if current_user.role != "admin":
            current_user.role = membership.role
    else:
        current_user.org_id = None
        if current_user.role in ("org_admin",):
            current_user.role = "viewer"

    session.add(current_user)
    await session.commit()
    return {"org_id": current_user.org_id, "role": current_user.role}


class UpdateProfileRequest(BaseModel):
    username: str | None = None
    full_name: str | None = None
    email: str | None = None


@router.patch("/me", response_model=UserRead)
async def update_profile(
    data: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if data.username is not None:
        username = data.username.strip()
        if len(username) < 3:
            raise HTTPException(status_code=422, detail="Username must be at least 3 characters")
        existing = (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()
        if existing and existing.id != current_user.id:
            raise HTTPException(status_code=409, detail="Username already taken")
        current_user.username = username

    if data.full_name is not None:
        full_name = data.full_name.strip()
        if len(full_name) < 2:
            raise HTTPException(status_code=422, detail="Please enter your full name")
        current_user.full_name = full_name

    if data.email is not None:
        email = data.email.lower().strip()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise HTTPException(status_code=422, detail="Invalid email address")
        existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing and existing.id != current_user.id:
            raise HTTPException(status_code=409, detail="Email already in use")
        current_user.email = email

    session.add(current_user)
    await session.commit()
    await session.refresh(current_user)
    return current_user


@router.get("/plan")
async def get_plan(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Return the effective plan (org plan if in an org), monthly usage, and limits."""
    from app.core.plan_limits import get_effective_plan, get_limits
    from sqlalchemy import func, select as _select
    from app.models.user import User as _User

    effective_plan = await get_effective_plan(current_user, session)
    limits = get_limits(effective_plan)
    scan_limit = limits["scan_limit"]
    used = current_user.month_scan_count or 0

    # Member count for orgs (to show user limit usage)
    member_count: int | None = None
    if current_user.org_id:
        member_count = (await session.execute(
            _select(func.count(_User.id)).where(_User.org_id == current_user.org_id)
        )).scalar_one()

    return {
        "plan": effective_plan,
        "is_org_plan": current_user.org_id is not None,
        "scan_limit": scan_limit,
        "scans_used": used,
        "scans_remaining": max(0, scan_limit - used) if scan_limit is not None else None,
        "scan_pct": round(used / scan_limit * 100, 1) if scan_limit else 0,
        "audit_days": limits["audit_days"],
        "connection_limit": limits["connection_limit"],
        "user_limit": limits["user_limit"],
        "member_count": member_count,
        "allowed_input_scanners": sorted(limits["input_scanners"]) if limits["input_scanners"] else None,
        "allowed_output_scanners": sorted(limits["output_scanners"]) if limits["output_scanners"] else None,
        "subscription_status": getattr(current_user, "subscription_status", "inactive"),
        "has_stripe": bool(getattr(current_user, "stripe_customer_id", None)),
    }


@router.get("/api-token", response_model=ApiTokenResponse)
async def get_api_token(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Return the user's static API token, generating one if it doesn't exist yet."""
    if current_user.api_token:
        return ApiTokenResponse(api_token=current_user.api_token, created=False)
    token = _generate_api_token()
    current_user.api_token = token
    session.add(current_user)
    await session.commit()
    return ApiTokenResponse(api_token=token, created=True)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password", status_code=200)
async def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(data.new_password) < 12:
        raise HTTPException(status_code=422, detail="Password must be at least 12 characters")
    current_user.hashed_password = hash_password(data.new_password)
    session.add(current_user)
    await session.commit()
    return {"detail": "Password updated successfully"}


@router.post("/api-token/regenerate", response_model=ApiTokenResponse)
async def regenerate_api_token(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Invalidate the existing API token and issue a new one."""
    token = _generate_api_token()
    current_user.api_token = token
    session.add(current_user)
    await session.commit()
    return ApiTokenResponse(api_token=token, created=True)


# ── Password / username recovery ───────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ForgotUsernameRequest(BaseModel):
    email: str


@router.post("/forgot-password", status_code=202)
@limiter.limit("5/hour")
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """
    Send a password-reset email. Always returns 202 to prevent email enumeration.
    """
    result = await session.execute(select(User).where(User.email == data.email.lower().strip()))
    user = result.scalar_one_or_none()

    if user:
        raw_token = secrets.token_urlsafe(32)
        # Store only the hash — the raw token is sent by email and never persisted
        user.reset_token = hashlib.sha256(raw_token.encode()).hexdigest()
        user.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=_RESET_TOKEN_EXPIRE_HOURS)
        await session.commit()
        background_tasks.add_task(
            _send_email,
            user.email,
            "Reset your SKF Guard password",
            _reset_password_email(user.username, raw_token),
        )

    return {"detail": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(
    data: ResetPasswordRequest,
    session: AsyncSession = Depends(get_session),
):
    if len(data.new_password) < 12:
        raise HTTPException(status_code=422, detail="Password must be at least 12 characters")

    token_hash = hashlib.sha256(data.token.encode()).hexdigest()
    result = await session.execute(select(User).where(User.reset_token == token_hash))
    user = result.scalar_one_or_none()

    if not user or not user.reset_token_expires_at:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    expires = user.reset_token_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires:
        raise HTTPException(status_code=400, detail="Reset link has expired")

    user.hashed_password = hash_password(data.new_password)
    user.reset_token = None
    user.reset_token_expires_at = None
    await session.commit()

    return {"detail": "Password updated successfully"}


@router.post("/forgot-username", status_code=202)
@limiter.limit("5/hour")
async def forgot_username(
    request: Request,
    data: ForgotUsernameRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """
    Send a username reminder email. Always returns 202 to prevent email enumeration.
    """
    result = await session.execute(select(User).where(User.email == data.email.lower().strip()))
    user = result.scalar_one_or_none()

    if user:
        background_tasks.add_task(
            _send_email,
            user.email,
            "Your SKF Guard username",
            _username_reminder_email(user.username),
        )

    return {"detail": "If that email is registered, your username has been sent."}
