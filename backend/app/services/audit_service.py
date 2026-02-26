from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


def _scope_filters(
    role: str,
    user_id: int | None,
    org_id: int | None,
    team_id: int | None = None,
    admin_filter_org_id: int | None = None,
) -> list:
    """
    Return SQLAlchemy WHERE conditions to scope audit log queries.

    - admin (superadmin): no filter — sees everything; optionally filter by org via admin_filter_org_id
    - org_admin: sees all logs from their org
    - team member: sees logs from their team
    - everyone else: sees only their own logs
    """
    if role == "admin":
        if admin_filter_org_id is not None:
            return [AuditLog.org_id == admin_filter_org_id]
        return []
    if role == "org_admin" and org_id is not None:
        return [AuditLog.org_id == org_id]
    if team_id is not None:
        return [AuditLog.team_id == team_id]
    if user_id is not None:
        return [AuditLog.user_id == user_id]
    return []


async def create_audit_log(
    session: AsyncSession,
    direction: str,
    raw_text: str,
    sanitized_text: str,
    is_valid: bool,
    scanner_results: dict,
    violation_scanners: list,
    ip_address: str | None = None,
    user_id: int | None = None,
    org_id: int | None = None,
    team_id: int | None = None,
    connection_id: int | None = None,
    connection_name: str | None = None,
    connection_environment: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    token_cost: float | None = None,
) -> AuditLog:
    log = AuditLog(
        direction=direction,
        raw_text=raw_text,
        sanitized_text=sanitized_text,
        is_valid=is_valid,
        scanner_results=scanner_results,
        violation_scanners=violation_scanners,
        ip_address=ip_address,
        user_id=user_id,
        org_id=org_id,
        team_id=team_id,
        connection_id=connection_id,
        connection_name=connection_name,
        connection_environment=connection_environment,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        token_cost=token_cost,
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)
    return log


async def list_audit_logs(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    direction: str | None = None,
    is_valid: bool | None = None,
    violations_only: bool = False,
    connection_id: int | None = None,
    max_age_days: int | None = None,
    # scope
    role: str = "admin",
    user_id: int | None = None,
    org_id: int | None = None,
    team_id: int | None = None,
    admin_filter_org_id: int | None = None,
) -> tuple[list[AuditLog], int]:
    query = select(AuditLog)
    count_query = select(func.count(AuditLog.id))

    filters = _scope_filters(role, user_id, org_id, team_id, admin_filter_org_id)
    if max_age_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        filters.append(AuditLog.created_at >= cutoff)
    if direction:
        filters.append(AuditLog.direction == direction)
    if is_valid is not None:
        filters.append(AuditLog.is_valid == is_valid)
    if violations_only:
        filters.append(AuditLog.is_valid == False)  # noqa: E712
    if connection_id is not None:
        filters.append(AuditLog.connection_id == connection_id)

    if filters:
        query = query.where(and_(*filters))
        count_query = count_query.where(and_(*filters))

    total_result = await session.execute(count_query)
    total = total_result.scalar_one()

    query = query.order_by(AuditLog.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    items = list(result.scalars().all())

    return items, total


async def get_summary(
    session: AsyncSession,
    role: str = "admin",
    user_id: int | None = None,
    org_id: int | None = None,
    team_id: int | None = None,
    admin_filter_org_id: int | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    scope = _scope_filters(role, user_id, org_id, team_id, admin_filter_org_id)

    def _with_scope(*extra):
        return and_(*scope, *extra) if scope else and_(*extra) if extra else True

    total_result = await session.execute(
        select(func.count(AuditLog.id)).where(_with_scope())
    )
    total_scans = total_result.scalar_one()

    scans_today_result = await session.execute(
        select(func.count(AuditLog.id)).where(_with_scope(AuditLog.created_at >= today_start))
    )
    scans_today = scans_today_result.scalar_one()

    violations_today_result = await session.execute(
        select(func.count(AuditLog.id)).where(
            _with_scope(AuditLog.is_valid == False, AuditLog.created_at >= today_start)  # noqa: E712
        )
    )
    violations_today = violations_today_result.scalar_one()

    total_violations_result = await session.execute(
        select(func.count(AuditLog.id)).where(_with_scope(AuditLog.is_valid == False))  # noqa: E712
    )
    total_violations = total_violations_result.scalar_one()

    input_result = await session.execute(
        select(func.count(AuditLog.id)).where(_with_scope(AuditLog.direction == "input"))
    )
    input_scans = input_result.scalar_one()
    output_scans = total_scans - input_scans

    avg_result = await session.execute(
        select(AuditLog.scanner_results).where(_with_scope())
    )
    all_results = avg_result.scalars().all()
    if all_results:
        scores = []
        for r in all_results:
            if isinstance(r, dict):
                scores.extend(r.values())
        avg_risk = sum(scores) / len(scores) if scores else 0.0
    else:
        avg_risk = 0.0

    pass_rate_today = round((1 - violations_today / scans_today) * 100, 1) if scans_today > 0 else 100.0

    return {
        "total_scans": total_scans,
        "scans_today": scans_today,
        "violations_today": violations_today,
        "total_violations": total_violations,
        "pass_rate_today": pass_rate_today,
        "input_scans": input_scans,
        "output_scans": output_scans,
        "avg_risk_score": round(avg_risk, 3),
    }


async def get_hourly(
    session: AsyncSession,
    role: str = "admin",
    user_id: int | None = None,
    org_id: int | None = None,
    team_id: int | None = None,
    admin_filter_org_id: int | None = None,
) -> list[dict]:
    """Return scan counts grouped by hour for the last 24 hours, oldest → newest."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    scope = _scope_filters(role, user_id, org_id, team_id, admin_filter_org_id)
    where = and_(*scope, AuditLog.created_at >= cutoff) if scope else AuditLog.created_at >= cutoff

    result = await session.execute(
        select(AuditLog.created_at, AuditLog.is_valid).where(where)
    )
    rows = result.all()

    slots: dict[str, dict] = {}
    for i in range(24):
        slot_time = cutoff + timedelta(hours=i)
        key = slot_time.strftime("%Y-%m-%d %H")
        slots[key] = {"hour": slot_time.strftime("%H:00"), "total": 0, "violations": 0}

    for created_at, is_valid in rows:
        key = created_at.strftime("%Y-%m-%d %H")
        if key in slots:
            slots[key]["total"] += 1
            if not is_valid:
                slots[key]["violations"] += 1

    return list(slots.values())


async def get_trends(
    session: AsyncSession,
    days: int = 30,
    role: str = "admin",
    user_id: int | None = None,
    org_id: int | None = None,
    team_id: int | None = None,
    admin_filter_org_id: int | None = None,
) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    scope = _scope_filters(role, user_id, org_id, team_id, admin_filter_org_id)
    where = and_(*scope, AuditLog.created_at >= cutoff) if scope else AuditLog.created_at >= cutoff

    result = await session.execute(
        select(AuditLog.created_at, AuditLog.is_valid).where(where)
    )
    rows = result.all()

    daily: dict[str, dict] = {}
    for created_at, is_valid in rows:
        day = created_at.strftime("%Y-%m-%d")
        if day not in daily:
            daily[day] = {"date": day, "total": 0, "violations": 0}
        daily[day]["total"] += 1
        if not is_valid:
            daily[day]["violations"] += 1

    return sorted(daily.values(), key=lambda x: x["date"])


async def get_top_violations(
    session: AsyncSession,
    limit: int = 10,
    role: str = "admin",
    user_id: int | None = None,
    org_id: int | None = None,
    team_id: int | None = None,
    admin_filter_org_id: int | None = None,
) -> list[dict]:
    scope = _scope_filters(role, user_id, org_id, team_id, admin_filter_org_id)
    query = select(AuditLog.violation_scanners)
    if scope:
        query = query.where(and_(*scope))

    result = await session.execute(query)
    rows = result.scalars().all()

    counts: dict[str, int] = {}
    for violation_list in rows:
        if isinstance(violation_list, list):
            for scanner in violation_list:
                counts[scanner] = counts.get(scanner, 0) + 1

    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{"scanner": k, "count": v} for k, v in sorted_items]
