"""
Plan definitions and enforcement helpers.

Plans (applied at org level when user is in an org, else at user level):
  free       — 1,000 scans/month, core scanners only, 7-day retention, 1 connection, 1 user
  pro        — 100,000 scans/month, all scanners, 90-day retention, unlimited connections, 10 users
  enterprise — unlimited everything, unlimited users
"""
from datetime import datetime

FREE_SCAN_LIMIT = 1_000
FREE_CONNECTION_LIMIT = 1
FREE_AUDIT_DAYS = 7

# scanner_type values that free users are allowed to run (must match guardrail_catalog)
FREE_INPUT_SCANNERS: set[str] = {"PromptInjection", "Anonymize", "Toxicity", "BanTopics", "BanSubstrings"}
FREE_OUTPUT_SCANNERS: set[str] = {"Toxicity", "NoRefusal", "BanTopics", "BanSubstrings"}

PLAN_LIMITS: dict[str, dict] = {
    "free": {
        "scan_limit": FREE_SCAN_LIMIT,
        "connection_limit": FREE_CONNECTION_LIMIT,
        "audit_days": FREE_AUDIT_DAYS,
        "input_scanners": FREE_INPUT_SCANNERS,
        "output_scanners": FREE_OUTPUT_SCANNERS,
        "user_limit": 1,
    },
    "pro": {
        "scan_limit": 100_000,
        "connection_limit": None,
        "audit_days": 90,
        "input_scanners": None,
        "output_scanners": None,
        "user_limit": 10,
    },
    "enterprise": {
        "scan_limit": None,
        "connection_limit": None,
        "audit_days": None,
        "input_scanners": None,
        "output_scanners": None,
        "user_limit": None,
    },
}


def get_limits(plan: str) -> dict:
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])


def is_same_month(dt: datetime | None, now: datetime) -> bool:
    return dt is not None and dt.year == now.year and dt.month == now.month


async def get_effective_plan(user, session) -> str:
    """
    Return the plan that governs this user's limits:
    - If the user belongs to an org, use the org's plan.
    - Otherwise fall back to the user's own plan.
    """
    if user.org_id:
        from app.models.organization import Organization
        from sqlalchemy import select
        org = (await session.execute(
            select(Organization).where(Organization.id == user.org_id)
        )).scalar_one_or_none()
        if org and org.plan:
            return org.plan
    return user.plan or "free"
