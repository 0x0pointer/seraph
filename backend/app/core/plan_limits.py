"""
Access limits helper — no plan tiers, all limits removed.
Every user has unlimited access to all scanners and features.
"""
from datetime import datetime


def get_limits(_plan: str = "") -> dict:
    return {
        "scan_limit": None,
        "connection_limit": None,
        "audit_days": None,
        "input_scanners": None,
        "output_scanners": None,
        "user_limit": None,
    }


def is_same_month(dt: datetime | None, now: datetime) -> bool:
    return dt is not None and dt.year == now.year and dt.month == now.month


async def get_effective_plan(_user, _session) -> str:
    return "default"
