"""
Risk state management — in-memory per-scope state with dual-window tracking.

Each scope (conversation, principal, network, execution_context, global) has:
  - Fast window (half-life ~120s) — detects burst attacks
  - Slow window (half-life ~3600s) — detects persistent probing
  - Recent timestamps deques — for repeat/velocity detection (NOT event_count)
  - Prompt fingerprint history — for mutation/similarity detection

Thread safety via lock striping: 64 locks per scope type, chosen by hash(scope_id).
Memory bounded via LRU eviction and configurable max clients per scope.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from app.services.risk_scoring import EvidenceClass


# ── Risk Window ──────────────────────────────────────────────────────────────

@dataclass
class RiskWindow:
    """Exponentially decaying risk accumulator.

    half_life_seconds controls decay rate:
      - fast window (120s): risk halves every 2 minutes
      - slow window (3600s): risk halves every hour
    """
    half_life_seconds: float
    score: float = 0.0
    last_update: float = 0.0     # time.monotonic()
    event_count: int = 0         # analytics only, NOT for enforcement

    def update(self, risk: float, now: float, factor: float = 0.3) -> float:
        """Add risk with exponential decay since last update.

        factor: fraction of incoming risk to add (0.3 = 30% of request risk).
        Returns new score after decay + accumulation.
        """
        if self.last_update > 0:
            elapsed = max(0.0, now - self.last_update)
            decay = math.exp(-0.693 * elapsed / self.half_life_seconds)
            self.score = self.score * decay
        self.score = min(1.0, self.score + risk * factor)
        self.last_update = now
        self.event_count += 1
        return self.score

    def current(self, now: float) -> float:
        """Get current decayed score without updating."""
        if self.last_update <= 0:
            return 0.0
        elapsed = max(0.0, now - self.last_update)
        decay = math.exp(-0.693 * elapsed / self.half_life_seconds)
        return self.score * decay


# ── Risk Level ───────────────────────────────────────────────────────────────

class RiskLevel:
    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"
    BLOCKED = "blocked"


def determine_risk_level(
    fast_score: float,
    slow_score: float,
    elevated_threshold: float = 0.3,
    high_threshold: float = 0.6,
    critical_threshold: float = 0.8,
    blocked_threshold: float = 0.95,
) -> str:
    """Derive risk level from dual-window scores.

    Uses max of fast and slow, but distinguishes patterns:
    - fast high + slow low = burst (risk level from fast)
    - fast low + slow high = persistent (risk level from slow)
    """
    effective = max(fast_score, slow_score)
    if effective >= blocked_threshold:
        return RiskLevel.BLOCKED
    if effective >= critical_threshold:
        return RiskLevel.CRITICAL
    if effective >= high_threshold:
        return RiskLevel.HIGH
    if effective >= elevated_threshold:
        return RiskLevel.ELEVATED
    return RiskLevel.NORMAL


# ── Scope State ──────────────────────────────────────────────────────────────

MAX_RECENT_TIMESTAMPS = 20
MAX_FINGERPRINTS = 50

@dataclass
class ScopeState:
    """Per-scope risk state with dual windows and behavioral tracking."""
    scope_id: str
    scope_type: str              # "conversation" | "principal" | "network" | "execution_context"

    fast_window: RiskWindow = field(default_factory=lambda: RiskWindow(half_life_seconds=120.0))
    slow_window: RiskWindow = field(default_factory=lambda: RiskWindow(half_life_seconds=3600.0))

    # Recent timestamps for repeat/velocity detection (NOT event_count)
    recent_event_timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=MAX_RECENT_TIMESTAMPS))
    recent_block_timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=MAX_RECENT_TIMESTAMPS))
    recent_near_threshold_timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=MAX_RECENT_TIMESTAMPS))

    # Evidence tracking
    evidence_families_seen: dict[str, int] = field(default_factory=dict)  # EvidenceClass.value → count
    scanner_families_probed: set[str] = field(default_factory=set)

    # Prompt fingerprints for similarity/mutation detection
    prompt_fingerprints: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_FINGERPRINTS))
    blocked_fingerprints: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_FINGERPRINTS))

    # Block state
    blocked_until: float = 0.0   # monotonic timestamp, 0 = not blocked

    # Counters (analytics only)
    total_requests: int = 0
    total_violations: int = 0
    last_request_time: float = 0.0

    def is_blocked(self, now: float) -> bool:
        """Check if currently in block state."""
        return self.blocked_until > now

    def block_for(self, duration_seconds: float, now: float) -> None:
        """Set block state for a duration."""
        self.blocked_until = now + duration_seconds

    def recent_events_in(self, window_seconds: float, now: float) -> int:
        """Count events in the last N seconds."""
        cutoff = now - window_seconds
        return sum(1 for t in self.recent_event_timestamps if t > cutoff)

    def recent_blocks_in(self, window_seconds: float, now: float) -> int:
        """Count blocks in the last N seconds."""
        cutoff = now - window_seconds
        return sum(1 for t in self.recent_block_timestamps if t > cutoff)

    def recent_near_threshold_in(self, window_seconds: float, now: float) -> int:
        """Count near-threshold attempts in the last N seconds."""
        cutoff = now - window_seconds
        return sum(1 for t in self.recent_near_threshold_timestamps if t > cutoff)

    def update(
        self,
        severity: float,
        evidence_classes: set[EvidenceClass],
        triggered_scanners: set[str],
        fingerprint: str | None,
        now: float,
        fast_factor: float = 0.3,
        slow_factor: float = 0.3,
        was_blocked: bool = False,
        is_near_threshold: bool = False,
    ) -> tuple[float, float]:
        """Update state with new evidence. Returns (fast_score, slow_score)."""
        fast = self.fast_window.update(severity, now, fast_factor)
        slow = self.slow_window.update(severity, now, slow_factor)

        self.recent_event_timestamps.append(now)
        self.last_request_time = now
        self.total_requests += 1

        if severity > 0.3:
            self.total_violations += 1

        if was_blocked:
            self.recent_block_timestamps.append(now)

        if is_near_threshold:
            self.recent_near_threshold_timestamps.append(now)

        for ec in evidence_classes:
            self.evidence_families_seen[ec.value] = self.evidence_families_seen.get(ec.value, 0) + 1

        self.scanner_families_probed.update(triggered_scanners)

        if fingerprint:
            self.prompt_fingerprints.append(fingerprint)

        return fast, slow


# ── Scope Store with Lock Striping ───────────────────────────────────────────

_NUM_LOCK_STRIPES = 64


class ScopeStore:
    """Thread-safe store for scope states with lock striping and LRU eviction.

    Lock striping: 64 locks per scope type, chosen by hash(scope_id) % 64.
    LRU eviction: when max_clients is exceeded, evict least recently used.
    """

    def __init__(self, scope_type: str, max_clients: int = 10000):
        self.scope_type = scope_type
        self.max_clients = max_clients
        self._states: dict[str, ScopeState] = {}
        self._locks = [asyncio.Lock() for _ in range(_NUM_LOCK_STRIPES)]
        self._cleanup_cursor = 0

    def _stripe_lock(self, scope_id: str) -> asyncio.Lock:
        """Get the lock stripe for a given scope ID."""
        return self._locks[hash(scope_id) % _NUM_LOCK_STRIPES]

    async def get_or_create(self, scope_id: str) -> ScopeState:
        """Get existing state or create new one. Thread-safe."""
        lock = self._stripe_lock(scope_id)
        async with lock:
            if scope_id not in self._states:
                self._states[scope_id] = ScopeState(scope_id=scope_id, scope_type=self.scope_type)
            return self._states[scope_id]

    async def get(self, scope_id: str) -> ScopeState | None:
        """Get existing state or None. Thread-safe."""
        lock = self._stripe_lock(scope_id)
        async with lock:
            return self._states.get(scope_id)

    async def update(
        self,
        scope_id: str,
        severity: float,
        evidence_classes: set[EvidenceClass],
        triggered_scanners: set[str],
        fingerprint: str | None,
        now: float,
        fast_factor: float = 0.3,
        slow_factor: float = 0.3,
        was_blocked: bool = False,
        is_near_threshold: bool = False,
    ) -> tuple[float, float, ScopeState]:
        """Update scope state. Returns (fast_score, slow_score, state)."""
        lock = self._stripe_lock(scope_id)
        async with lock:
            if scope_id not in self._states:
                self._states[scope_id] = ScopeState(scope_id=scope_id, scope_type=self.scope_type)
            state = self._states[scope_id]
            fast, slow = state.update(
                severity, evidence_classes, triggered_scanners, fingerprint, now,
                fast_factor, slow_factor, was_blocked, is_near_threshold,
            )
            return fast, slow, state

    async def cleanup(self, max_idle_seconds: float, now: float, max_sweep: int = 50) -> int:
        """Incremental cleanup: evict idle clients, bounded work per call.

        Returns number of evicted entries.
        """
        evicted = 0
        scope_ids = list(self._states.keys())
        if not scope_ids:
            return 0

        # Start from cursor, wrap around
        start = self._cleanup_cursor % len(scope_ids)
        end = min(start + max_sweep, len(scope_ids))
        candidates = scope_ids[start:end]
        self._cleanup_cursor = end

        cutoff = now - max_idle_seconds
        for sid in candidates:
            lock = self._stripe_lock(sid)
            async with lock:
                state = self._states.get(sid)
                if state and state.last_request_time > 0 and state.last_request_time < cutoff:
                    del self._states[sid]
                    evicted += 1

        # LRU eviction if over max_clients
        if len(self._states) > self.max_clients:
            # Sort by last_request_time, evict oldest
            sorted_ids = sorted(
                self._states.keys(),
                key=lambda k: self._states[k].last_request_time,
            )
            to_evict = sorted_ids[: len(self._states) - self.max_clients]
            for sid in to_evict:
                lock = self._stripe_lock(sid)
                async with lock:
                    self._states.pop(sid, None)
                    evicted += 1

        return evicted

    @property
    def size(self) -> int:
        return len(self._states)


# ── Token Bucket (rate limiting) ─────────────────────────────────────────────

@dataclass
class TokenBucket:
    """Token bucket rate limiter per scope.

    capacity: max burst size
    refill_rate: tokens per second
    """
    capacity: float = 60.0
    refill_rate: float = 1.0
    tokens: float = 60.0
    last_refill: float = 0.0

    def consume(self, now: float) -> bool:
        """Try to consume one token. Returns True if allowed, False if rate limited."""
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    def time_until_available(self) -> float:
        """Seconds until next token is available."""
        if self.tokens >= 1.0:
            return 0.0
        deficit = 1.0 - self.tokens
        return deficit / self.refill_rate if self.refill_rate > 0 else float("inf")
