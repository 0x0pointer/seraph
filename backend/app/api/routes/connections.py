import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, func, delete as _sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core.database import get_session
from app.models.api_connection import ApiConnection
from app.models.user import User
from app.models.connection_guardrail import ConnectionGuardrail
from app.models.guardrail import GuardrailConfig
from app.schemas.connection import (
    ApiConnectionCreate,
    ApiConnectionRead,
    ApiConnectionUpdate,
    ConnectionGuardrailItem,
    ConnectionGuardrailsUpdate,
    GuardrailSelection,
)
from app.services.event_service import log_event

router = APIRouter(prefix="/connections", tags=["connections"])

_CONN_KEY_PREFIX = "ts_conn_"


def _generate_connection_key() -> str:
    return _CONN_KEY_PREFIX + secrets.token_hex(32)


def _read(conn: ApiConnection) -> ApiConnectionRead:
    return ApiConnectionRead.model_validate(conn)


async def _get_conn(
    conn_id: int,
    user: User,
    session: AsyncSession,
) -> ApiConnection:
    """
    Access rules (team_id takes priority):
    - team member  → any connection where team_id == user.team_id
    - org_admin    → any connection where org_id == user.org_id
    - personal     → connection where user_id == user.id and no org/team
    """
    from sqlalchemy import or_, and_
    if user.role == "admin":
        # Platform admin — can access any connection they own
        filter_clause = and_(ApiConnection.id == conn_id, ApiConnection.user_id == user.id)
    else:
        filter_clause = and_(
            ApiConnection.id == conn_id,
            or_(
                # Team connection
                and_(ApiConnection.team_id.isnot(None), ApiConnection.team_id == user.team_id),
                # Org-admin sees all org connections
                and_(ApiConnection.org_id.isnot(None), ApiConnection.org_id == user.org_id,
                     user.role == "org_admin"),
                # Personal connection
                and_(ApiConnection.org_id.is_(None), ApiConnection.team_id.is_(None),
                     ApiConnection.user_id == user.id),
            ),
        )
    result = await session.execute(select(ApiConnection).where(filter_clause))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return conn


@router.get("", response_model=list[ApiConnectionRead])
async def list_connections(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    from sqlalchemy import or_, and_
    if current_user.role == "admin":
        # Platform admin — all connections they own, regardless of org/team state
        where_clause = ApiConnection.user_id == current_user.id
    elif current_user.team_id is not None:
        # Team member — see only team connections
        where_clause = ApiConnection.team_id == current_user.team_id
    elif current_user.role == "org_admin" and current_user.org_id is not None:
        # Org admin — see all connections across the whole org (all teams + teamless)
        where_clause = ApiConnection.org_id == current_user.org_id
    elif current_user.org_id is not None:
        # Org member without a team — personal connections only
        where_clause = and_(ApiConnection.user_id == current_user.id,
                            ApiConnection.org_id == current_user.org_id,
                            ApiConnection.team_id.is_(None))
    else:
        # Solo user — personal connections
        where_clause = and_(ApiConnection.user_id == current_user.id, ApiConnection.org_id.is_(None))
    result = await session.execute(
        select(ApiConnection).where(where_clause).order_by(ApiConnection.created_at.desc())
    )
    return [_read(c) for c in result.scalars().all()]


@router.post("", response_model=ApiConnectionRead, status_code=status.HTTP_201_CREATED)
async def create_connection(
    data: ApiConnectionCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conn = ApiConnection(
        user_id=current_user.id,
        org_id=current_user.org_id,
        team_id=current_user.team_id,  # None unless user belongs to a team
        created_by_username=current_user.username,
        name=data.name.strip(),
        environment=data.environment,
        api_key=_generate_connection_key(),
        alert_enabled=data.alert_enabled,
        alert_threshold=data.alert_threshold,
        cost_per_input_token=data.cost_per_input_token,
        cost_per_output_token=data.cost_per_output_token,
        monthly_alert_spend=data.monthly_alert_spend,
        max_monthly_spend=data.max_monthly_spend,
    )
    session.add(conn)
    await session.flush()
    await log_event(session, event_type="connection.created",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="connection", target_id=conn.id, target_name=conn.name,
        details={"environment": conn.environment})
    await session.commit()
    await session.refresh(conn)
    return _read(conn)


@router.put("/{conn_id}", response_model=ApiConnectionRead)
async def update_connection(
    conn_id: int,
    data: ApiConnectionUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conn = await _get_conn(conn_id, current_user, session)
    if data.name is not None:
        conn.name = data.name.strip()
    if data.environment is not None:
        conn.environment = data.environment
    if data.alert_enabled is not None:
        conn.alert_enabled = data.alert_enabled
    if data.alert_threshold is not None or "alert_threshold" in data.model_fields_set:
        conn.alert_threshold = data.alert_threshold
    if data.cost_per_input_token is not None:
        conn.cost_per_input_token = data.cost_per_input_token
    if data.cost_per_output_token is not None:
        conn.cost_per_output_token = data.cost_per_output_token
    if data.monthly_alert_spend is not None or "monthly_alert_spend" in data.model_fields_set:
        conn.monthly_alert_spend = data.monthly_alert_spend
    if data.max_monthly_spend is not None or "max_monthly_spend" in data.model_fields_set:
        conn.max_monthly_spend = data.max_monthly_spend
    await log_event(session, event_type="connection.updated",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="connection", target_id=conn.id, target_name=conn.name,
        details={"environment": conn.environment, "alert_enabled": conn.alert_enabled})
    session.add(conn)
    await session.commit()
    await session.refresh(conn)
    return _read(conn)


@router.patch("/{conn_id}/toggle", response_model=ApiConnectionRead)
async def toggle_connection(
    conn_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conn = await _get_conn(conn_id, current_user, session)
    new_status = "blocked" if conn.status == "active" else "active"
    conn.status = new_status
    await log_event(session, event_type="connection.toggled",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="connection", target_id=conn.id, target_name=conn.name,
        details={"status": new_status, "environment": conn.environment})
    session.add(conn)
    await session.commit()
    await session.refresh(conn)
    return _read(conn)


@router.post("/{conn_id}/reset-spend", response_model=ApiConnectionRead)
async def reset_connection_spend(
    conn_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Zero out the monthly spend counters for this connection."""
    conn = await _get_conn(conn_id, current_user, session)
    old_spend = conn.month_spend
    conn.month_spend = 0.0
    conn.month_input_tokens = 0
    conn.month_output_tokens = 0
    conn.month_started_at = datetime.now(timezone.utc)
    await log_event(session, event_type="connection.spend_reset",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="connection", target_id=conn.id, target_name=conn.name,
        details={"previous_spend": round(old_spend, 4)})
    session.add(conn)
    await session.commit()
    await session.refresh(conn)
    return _read(conn)


@router.get("/{conn_id}/guardrails", response_model=list[ConnectionGuardrailItem])
async def get_connection_guardrails(
    conn_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _get_conn(conn_id, current_user, session)
    all_g = (
        await session.execute(select(GuardrailConfig).order_by(GuardrailConfig.order))
    ).scalars().all()
    conn_rows = (
        await session.execute(
            select(ConnectionGuardrail).where(ConnectionGuardrail.connection_id == conn_id)
        )
    ).scalars().all()
    enabled_ids = {r.guardrail_id for r in conn_rows}
    threshold_map = {r.guardrail_id: r.threshold_override for r in conn_rows}
    return [
        ConnectionGuardrailItem(
            id=g.id,
            name=g.name,
            scanner_type=g.scanner_type,
            direction=g.direction,
            is_active=g.is_active,
            enabled_for_conn=g.id in enabled_ids,
            threshold_override=threshold_map.get(g.id),
        )
        for g in all_g
    ]


@router.put("/{conn_id}/guardrails", status_code=200)
async def set_connection_guardrails(
    conn_id: int,
    data: ConnectionGuardrailsUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conn = await _get_conn(conn_id, current_user, session)
    conn.use_custom_guardrails = data.use_custom_guardrails
    session.add(conn)
    await session.execute(
        _sa_delete(ConnectionGuardrail).where(ConnectionGuardrail.connection_id == conn_id)
    )
    seen: set[int] = set()
    for sel in data.guardrails:
        if sel.id not in seen:
            seen.add(sel.id)
            session.add(ConnectionGuardrail(
                connection_id=conn_id,
                guardrail_id=sel.id,
                threshold_override=sel.threshold_override,
            ))
    await session.commit()
    return {"ok": True}


@router.post("/{conn_id}/test-scan")
async def test_connection_scan(
    conn_id: int,
    data: dict,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Run a scan using this connection's exact guardrail configuration.
    Authenticated via user JWT (dashboard use only) — simulates what an external
    client would see when sending with this connection's API key.
    """
    from app.services import scanner_engine
    from app.models.connection_guardrail import ConnectionGuardrail as CG

    conn = await _get_conn(conn_id, current_user, session)
    text = data.get("text", "")
    direction = data.get("direction", "input")

    # Resolve per-connection guardrail overrides (same logic as scan.py)
    allowed_ids = None
    threshold_overrides: dict[int, float] = {}
    if conn.use_custom_guardrails:
        rows = (await session.execute(
            select(CG).where(CG.connection_id == conn_id)
        )).scalars().all()
        allowed_ids = {r.guardrail_id for r in rows}
        threshold_overrides = {r.guardrail_id: r.threshold_override for r in rows if r.threshold_override is not None}

    if direction == "output":
        prompt = data.get("prompt", "")
        is_valid, sanitized, results, violations = await scanner_engine.run_output_scan(
            session, prompt, text,
            allowed_guardrail_ids=allowed_ids,
            threshold_overrides=threshold_overrides,
        )
    else:
        is_valid, sanitized, results, violations = await scanner_engine.run_input_scan(
            session, text,
            allowed_guardrail_ids=allowed_ids,
            threshold_overrides=threshold_overrides,
        )

    return {
        "is_valid": is_valid,
        "sanitized_text": sanitized,
        "scanner_results": results,
        "violation_scanners": violations,
        "use_custom_guardrails": conn.use_custom_guardrails,
        "active_guardrail_count": len(allowed_ids) if allowed_ids is not None else None,
    }


@router.delete("/{conn_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    conn_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conn = await _get_conn(conn_id, current_user, session)
    await log_event(session, event_type="connection.deleted",
        actor_id=current_user.id, actor_username=current_user.username,
        target_type="connection", target_id=conn.id, target_name=conn.name,
        details={"environment": conn.environment})
    await session.delete(conn)
    await session.commit()
