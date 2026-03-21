"""Unit tests for risk_state.py — windows, scopes, stores, rate limiting."""
import asyncio
import time
import pytest
from app.services.risk_state import (
    RiskWindow, ScopeState, ScopeStore, TokenBucket,
    determine_risk_level, RiskLevel,
)
from app.services.risk_scoring import EvidenceClass


class TestRiskWindow:
    def test_initial_score_zero(self):
        w = RiskWindow(half_life_seconds=120.0)
        assert w.score == 0.0

    def test_update_adds_risk(self):
        w = RiskWindow(half_life_seconds=120.0)
        w.update(0.8, time.monotonic(), factor=0.3)
        assert w.score == pytest.approx(0.24, abs=0.01)

    def test_decay_over_half_life(self):
        w = RiskWindow(half_life_seconds=120.0)
        now = time.monotonic()
        w.update(1.0, now, factor=1.0)  # score = 1.0
        # After one half-life, score should be ~0.5
        score = w.current(now + 120)
        assert 0.45 < score < 0.55

    def test_accumulation_across_updates(self):
        w = RiskWindow(half_life_seconds=120.0)
        now = time.monotonic()
        w.update(0.5, now, factor=0.3)
        w.update(0.5, now + 1, factor=0.3)
        assert w.score > 0.15  # accumulated

    def test_event_count_increments(self):
        w = RiskWindow(half_life_seconds=120.0)
        w.update(0.5, time.monotonic())
        w.update(0.3, time.monotonic())
        assert w.event_count == 2

    def test_score_capped_at_1(self):
        w = RiskWindow(half_life_seconds=120.0)
        now = time.monotonic()
        for _ in range(20):
            w.update(1.0, now, factor=0.5)
        assert w.score <= 1.0


class TestDetermineRiskLevel:
    def test_normal(self):
        assert determine_risk_level(0.1, 0.1) == RiskLevel.NORMAL

    def test_elevated(self):
        assert determine_risk_level(0.4, 0.1) == RiskLevel.ELEVATED

    def test_high(self):
        assert determine_risk_level(0.7, 0.2) == RiskLevel.HIGH

    def test_critical(self):
        assert determine_risk_level(0.85, 0.5) == RiskLevel.CRITICAL

    def test_blocked(self):
        assert determine_risk_level(0.96, 0.96) == RiskLevel.BLOCKED

    def test_uses_max_of_both_windows(self):
        # Fast low, slow high → uses slow
        assert determine_risk_level(0.1, 0.7) == RiskLevel.HIGH

    def test_custom_thresholds(self):
        assert determine_risk_level(0.5, 0.1, elevated_threshold=0.6) == RiskLevel.NORMAL


class TestScopeState:
    def test_initial_state(self):
        s = ScopeState(scope_id="test", scope_type="principal")
        assert s.total_requests == 0
        assert not s.is_blocked(time.monotonic())

    def test_block_and_check(self):
        s = ScopeState(scope_id="test", scope_type="principal")
        now = time.monotonic()
        s.block_for(10.0, now)
        assert s.is_blocked(now + 5)
        assert not s.is_blocked(now + 15)

    def test_update_tracks_evidence(self):
        s = ScopeState(scope_id="test", scope_type="principal")
        s.update(0.8, {EvidenceClass.ACTIVE_ATTACK}, {"PromptInjection"}, "fp1", time.monotonic())
        assert s.total_requests == 1
        assert s.total_violations == 1
        assert "active_attack" in s.evidence_families_seen
        assert "PromptInjection" in s.scanner_families_probed

    def test_recent_events_count(self):
        s = ScopeState(scope_id="test", scope_type="principal")
        now = time.monotonic()
        for i in range(5):
            s.update(0.5, {EvidenceClass.RECON}, set(), None, now + i)
        assert s.recent_events_in(10, now + 4) == 5
        # Events at now+0..now+4, window of 3s from now+4 = events at now+2,now+3,now+4
        assert s.recent_events_in(3, now + 4) == 3

    def test_near_threshold_tracking(self):
        s = ScopeState(scope_id="test", scope_type="principal")
        now = time.monotonic()
        s.update(0.5, set(), set(), None, now, is_near_threshold=True)
        s.update(0.6, set(), set(), None, now + 1, is_near_threshold=True)
        assert s.recent_near_threshold_in(10, now + 1) == 2


class TestScopeStore:
    def test_get_or_create(self):
        async def _test():
            store = ScopeStore("principal", max_clients=100)
            state = await store.get_or_create("user1")
            assert state.scope_id == "user1"
            assert store.size == 1
        asyncio.get_event_loop().run_until_complete(_test())

    def test_update(self):
        async def _test():
            store = ScopeStore("principal", max_clients=100)
            fast, slow, state = await store.update(
                "user1", 0.5, {EvidenceClass.ACTIVE_ATTACK}, {"PI"}, "fp", time.monotonic(),
            )
            assert fast > 0
            assert slow > 0
            assert state.total_requests == 1
        asyncio.get_event_loop().run_until_complete(_test())

    def test_cleanup_evicts_idle(self):
        async def _test():
            store = ScopeStore("principal", max_clients=100)
            now = time.monotonic()
            # Create client with old timestamp
            state = await store.get_or_create("old_client")
            state.last_request_time = now - 7200  # 2 hours ago
            # Also create a fresh one
            await store.update("fresh_client", 0.1, set(), set(), None, now)
            evicted = await store.cleanup(3600, now, max_sweep=50)
            assert evicted == 1
            assert store.size == 1
        asyncio.get_event_loop().run_until_complete(_test())

    def test_lru_eviction(self):
        async def _test():
            store = ScopeStore("principal", max_clients=3)
            now = time.monotonic()
            for i in range(5):
                await store.update(f"user{i}", 0.1, set(), set(), None, now + i)
            # Max 3 clients, should evict oldest
            await store.cleanup(3600, now + 10, max_sweep=50)
            assert store.size <= 3
        asyncio.get_event_loop().run_until_complete(_test())


class TestTokenBucket:
    def test_allows_up_to_capacity(self):
        now = time.monotonic()
        b = TokenBucket(capacity=3, refill_rate=1.0, tokens=3.0, last_refill=now)
        assert b.consume(now) is True
        assert b.consume(now) is True
        assert b.consume(now) is True
        assert b.consume(now) is False

    def test_refills_over_time(self):
        now = time.monotonic()
        b = TokenBucket(capacity=3, refill_rate=1.0, tokens=0.0, last_refill=now)
        assert b.consume(now) is False
        assert b.consume(now + 2.0) is True  # refilled 2 tokens

    def test_time_until_available(self):
        now = time.monotonic()
        b = TokenBucket(capacity=3, refill_rate=1.0, tokens=0.5, last_refill=now)
        assert b.time_until_available() > 0
        b.tokens = 1.5
        assert b.time_until_available() == 0.0
