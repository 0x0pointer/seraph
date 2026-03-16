"""Unit tests for app/core/plan_limits.py — access limits helper."""
import pytest
from datetime import datetime
from app.core.plan_limits import get_limits, is_same_month, get_effective_plan


class TestGetLimits:
    def test_returns_dict_with_all_none(self):
        limits = get_limits()
        assert isinstance(limits, dict)
        for key in ("scan_limit", "connection_limit", "audit_days",
                     "input_scanners", "output_scanners", "user_limit"):
            assert limits[key] is None

    def test_ignores_plan_argument(self):
        limits = get_limits("enterprise")
        assert all(v is None for v in limits.values())


class TestIsSameMonth:
    def test_matching_month(self):
        dt = datetime(2026, 3, 5)
        now = datetime(2026, 3, 16)
        assert is_same_month(dt, now) is True

    def test_different_month(self):
        dt = datetime(2026, 2, 28)
        now = datetime(2026, 3, 1)
        assert is_same_month(dt, now) is False

    def test_different_year(self):
        dt = datetime(2025, 3, 16)
        now = datetime(2026, 3, 16)
        assert is_same_month(dt, now) is False

    def test_none_dt_returns_false(self):
        now = datetime(2026, 3, 16)
        assert is_same_month(None, now) is False


class TestGetEffectivePlan:
    def test_returns_default(self):
        result = get_effective_plan(None, None)
        assert result == "default"
