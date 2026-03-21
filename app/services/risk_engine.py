"""
Risk engine — orchestrates evidence scoring, state tracking, behavioral
detection, policy decisions, and persistence.

This is the entry point for the risk subsystem. proxy.py calls:
  - check_pre_request(...)  → PreRequestDecision
  - assess_request(...)     → PostScanDecision
  - assess_stream_chunk(...) → StreamDecision

proxy.py is a dumb executor of decisions — no ad hoc conditions.

The engine is a singleton, initialized at startup via init_risk_engine()
and accessed via get_risk_engine().
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.services.risk_scoring import (
    EvidenceClass, SignalAttribute, ReasonCode, RequestEvidence,
    compute_request_evidence,
)
from app.services.risk_fingerprint import (
    fingerprint_prompt, evidence_signature, canonical_hash,
)
from app.services.risk_state import (
    ScopeStore, ScopeState, RiskLevel, TokenBucket,
    determine_risk_level,
)
from app.services.risk_detectors import (
    detect_boundary_testing, detect_retry_mutation,
    detect_distributed_probe, detect_streaming_bypass,
    detect_multi_turn_escalation, DerivedEvent,
)
from app.services.risk_policy import (
    PolicyAction, PolicyDecision, ScanTier, StreamTier,
    decide, get_culpability, select_scan_tier, select_stream_tier,
)
from app.services import risk_persistence

logger = logging.getLogger(__name__)


# ── Decision types returned to proxy.py ──────────────────────────────────────

@dataclass
class PreRequestDecision:
    """Returned by check_pre_request(). proxy.py acts on this before scanning."""
    allowed: bool
    action: PolicyAction = PolicyAction.ALLOW
    reason: ReasonCode = ReasonCode.PI_HIGH_CONF
    scan_tier: ScanTier = ScanTier.STANDARD
    stream_tier: StreamTier = StreamTier.PASSTHROUGH
    retry_after_seconds: float = 0.0
    risk_level: str = RiskLevel.NORMAL
    correlation_id: str = ""


@dataclass
class PostScanDecision:
    """Returned by assess_request(). proxy.py acts on this after scanning."""
    policy: PolicyDecision
    evidence: RequestEvidence
    risk_level: str = RiskLevel.NORMAL
    correlation_id: str = ""
    tarpit_seconds: float = 0.0


@dataclass
class StreamDecision:
    """Returned by assess_stream_chunk(). Controls mid-stream behavior."""
    terminate: bool = False
    reason: ReasonCode | None = None
    severity: float = 0.0


# ── Scan Budget Controller ───────────────────────────────────────────────────

class ScanBudget:
    """Prevents adaptive scanning from becoming a DoS vector.

    Tracks deep/enhanced scan counts per second. Degrades tier when over budget.
    """
    def __init__(self, max_deep_per_second: int = 5, max_enhanced_per_second: int = 20):
        self.max_deep = max_deep_per_second
        self.max_enhanced = max_enhanced_per_second
        self._deep_count = 0
        self._enhanced_count = 0
        self._window_start = 0.0

    def _maybe_reset(self, now: float) -> None:
        if now - self._window_start >= 1.0:
            self._deep_count = 0
            self._enhanced_count = 0
            self._window_start = now

    def request_tier(self, desired: ScanTier, now: float) -> tuple[ScanTier, bool]:
        """Request a scan tier. Returns (actual_tier, was_degraded)."""
        self._maybe_reset(now)
        if desired == ScanTier.DEEP:
            if self._deep_count < self.max_deep:
                self._deep_count += 1
                return ScanTier.DEEP, False
            desired = ScanTier.ENHANCED  # degrade
        if desired == ScanTier.ENHANCED:
            if self._enhanced_count < self.max_enhanced:
                self._enhanced_count += 1
                return ScanTier.ENHANCED, desired != ScanTier.ENHANCED
            return ScanTier.STANDARD, True  # degrade
        return ScanTier.STANDARD, False


# ── Global Correlation State ─────────────────────────────────────────────────

class GlobalCorrelation:
    """Tracks canonical hashes across principals for distributed probe detection.

    Bounded: max 50,000 entries with TTL-based eviction.
    """
    def __init__(self, max_entries: int = 50000, ttl_seconds: float = 900.0):
        self.max_entries = max_entries
        self.ttl = ttl_seconds
        # {canonical_hash: {principal_id: timestamp}}
        self._hashes: dict[str, dict[str, float]] = {}

    def record(self, canon_hash: str, principal_id: str, now: float) -> None:
        """Record a canonical hash from a principal."""
        if canon_hash not in self._hashes:
            self._hashes[canon_hash] = {}
        self._hashes[canon_hash][principal_id] = now

        # Lazy eviction
        if len(self._hashes) > self.max_entries:
            self._evict(now)

    def get_principals(self, canon_hash: str, now: float) -> set[str]:
        """Get principals that sent the same canonical hash recently."""
        entries = self._hashes.get(canon_hash, {})
        cutoff = now - self.ttl
        return {pid for pid, ts in entries.items() if ts > cutoff}

    def _evict(self, now: float) -> None:
        cutoff = now - self.ttl
        to_remove = [
            h for h, pids in self._hashes.items()
            if all(ts < cutoff for ts in pids.values())
        ]
        for h in to_remove[:1000]:  # bounded work
            del self._hashes[h]


# ── Identity Resolution ──────────────────────────────────────────────────────

def identify_client(
    ip: str | None,
    api_key: str | None,
    user_agent: str | None = None,
    upstream: str | None = None,
) -> dict[str, str]:
    """Resolve multi-scope identity from request attributes.

    Returns dict with scope_type → scope_id for each scope.
    """
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16] if api_key else None

    principal = f"key:{key_hash}" if key_hash else f"ip:{ip or 'unknown'}"
    network = f"net:{ip or 'unknown'}"

    # Execution context: upstream + route (model/route added later when available)
    exec_ctx = f"ctx:{upstream or 'default'}"

    return {
        "principal": principal,
        "network": network,
        "execution_context": exec_ctx,
    }


def derive_conversation_id(
    api_key: str | None,
    body: dict | None,
    upstream: str | None,
) -> tuple[str, float]:
    """Derive conversation ID with confidence score.

    High confidence: explicit session/thread ID in body.
    Low confidence: heuristic bucket from key + upstream + time.
    """
    if body:
        for field_name in ("conversation_id", "session_id", "thread_id"):
            val = body.get(field_name)
            if val and isinstance(val, str):
                return val, 0.95

    # Heuristic: 15-min time bucket
    bucket_key = f"{api_key or ''}:{upstream or ''}:{int(time.time()) // 900}"
    bucket_hash = hashlib.sha256(bucket_key.encode()).hexdigest()[:16]
    return f"conv:{bucket_hash}", 0.3


def generate_correlation_id() -> str:
    """Generate a stable correlation ID for one request (reused across all events)."""
    return uuid.uuid4().hex[:16]


# ── Risk Engine ──────────────────────────────────────────────────────────────

class RiskEngine:
    """Stateful risk assessment engine.

    Orchestrates: scoring → state update → derived detection → policy → persistence.
    Thread-safe via lock-striped scope stores.
    """

    def __init__(
        self,
        persist_db: str | None = None,
        scanner_weights: dict[str, float] | None = None,
        max_clients: int = 10000,
        block_duration_seconds: float = 300.0,
        max_deep_per_second: int = 5,
        max_enhanced_per_second: int = 20,
        expose_debug_headers: bool = False,
        elevated_threshold: float = 0.3,
        high_threshold: float = 0.6,
        critical_threshold: float = 0.8,
        blocked_threshold: float = 0.95,
    ):
        self.persist_db = persist_db
        self.scanner_weights = scanner_weights
        self.block_duration = block_duration_seconds
        self.expose_debug = expose_debug_headers
        self.thresholds = {
            "elevated": elevated_threshold,
            "high": high_threshold,
            "critical": critical_threshold,
            "blocked": blocked_threshold,
        }

        # Scope stores
        self.principals = ScopeStore("principal", max_clients)
        self.networks = ScopeStore("network", max_clients)
        self.conversations = ScopeStore("conversation", max_clients)
        self.exec_contexts = ScopeStore("execution_context", max_clients)

        # Global correlation
        self.global_correlation = GlobalCorrelation()

        # Scan budget
        self.scan_budget = ScanBudget(max_deep_per_second, max_enhanced_per_second)

        # Rate limiters per principal
        self._rate_limiters: dict[str, TokenBucket] = {}

        # Cleanup counter
        self._request_counter = 0

    async def check_pre_request(
        self,
        identities: dict[str, str],
        is_streaming: bool = False,
    ) -> PreRequestDecision:
        """Pre-flight check before any scanning. Returns blocking decision if client is blocked."""
        now = time.monotonic()
        principal_id = identities.get("principal", "unknown")
        correlation_id = generate_correlation_id()

        # Check if principal is blocked (only from input-driven blocks, not output)
        state = await self.principals.get(principal_id)
        if state and state.is_blocked(now):
            # Only enforce block if there were actual input violations (not just output FPs)
            if state.total_violations >= 3:
                remaining = state.blocked_until - now
                return PreRequestDecision(
                    allowed=False,
                    action=PolicyAction.HARD_BLOCK,
                    reason=ReasonCode.RETRY_AFTER_BLOCK,
                    retry_after_seconds=remaining,
                    risk_level=RiskLevel.BLOCKED,
                    correlation_id=correlation_id,
                )

        # Check rate limit
        if principal_id in self._rate_limiters:
            if not self._rate_limiters[principal_id].consume(now):
                return PreRequestDecision(
                    allowed=False,
                    action=PolicyAction.RATE_LIMIT,
                    reason=ReasonCode.RESOURCE_ABUSE_DETECTED,
                    retry_after_seconds=self._rate_limiters[principal_id].time_until_available(),
                    risk_level=RiskLevel.HIGH,
                    correlation_id=correlation_id,
                )

        # Determine scan tier from principal's slow window
        slow_score = 0.0
        if state:
            slow_score = state.slow_window.current(now)

        desired_tier = select_scan_tier(slow_score)
        actual_tier, degraded = self.scan_budget.request_tier(desired_tier, now)
        stream_tier = select_stream_tier(actual_tier, is_streaming)

        risk_level = determine_risk_level(
            state.fast_window.current(now) if state else 0.0,
            slow_score,
        )

        return PreRequestDecision(
            allowed=True,
            scan_tier=actual_tier,
            stream_tier=stream_tier,
            risk_level=risk_level,
            correlation_id=correlation_id,
        )

    async def assess_request(
        self,
        identities: dict[str, str],
        scanner_results: dict[str, float],
        direction: str,
        violations: list[str],
        correlation_id: str,
        conversation_id: str | None = None,
        conversation_confidence: float = 0.3,
        is_streaming: bool = False,
        prompt_text: str = "",
        upstream_target: str = "",
    ) -> PostScanDecision:
        """Assess a scan result (input or output). Returns policy decision."""
        now = time.monotonic()
        principal_id = identities.get("principal", "unknown")
        network_id = identities.get("network", "unknown")
        exec_ctx_id = identities.get("execution_context", "default")

        # ── 1. Compute request evidence ──────────────────────────────────
        evidence = compute_request_evidence(
            scanner_results, direction, self.scanner_weights
        )

        # ── 2. Fingerprint prompt ────────────────────────────────────────
        fp = fingerprint_prompt(prompt_text) if prompt_text else {}
        canon_hash = fp.get("canonical", "")
        fuzzy_fp = fp.get("fuzzy", "")
        ev_sig = evidence_signature(evidence.triggered_scanners)

        # ── 3. Record in global correlation ──────────────────────────────
        if canon_hash and direction == "input":
            self.global_correlation.record(canon_hash, principal_id, now)

        # ── 4. Get current state ─────────────────────────────────────────
        principal_state = await self.principals.get_or_create(principal_id)
        conv_state = None
        if conversation_id:
            conv_state = await self.conversations.get_or_create(conversation_id)

        # ── 5. Determine culpability ─────────────────────────────────────
        outcome = "block" if violations else "monitor"
        has_fp = SignalAttribute.FP_PRONE in evidence.signal_attributes
        culp = get_culpability(direction, outcome, has_fp)

        is_near_threshold = 0.45 <= evidence.severity <= 0.75

        # ── 6. Update scope states ───────────────────────────────────────
        # Output scans use lower accumulation factor to avoid punishing principals
        # for model/prompt weaknesses
        acc_factor = 0.15 if direction == "output" else 0.3

        p_fast, p_slow, _ = await self.principals.update(
            principal_id, evidence.severity * culp.principal,
            evidence.evidence_classes, evidence.triggered_scanners,
            fuzzy_fp, now,
            fast_factor=acc_factor, slow_factor=acc_factor,
            was_blocked=bool(violations),
            is_near_threshold=is_near_threshold,
        )

        await self.networks.update(
            network_id, evidence.severity * culp.network,
            evidence.evidence_classes, evidence.triggered_scanners,
            None, now,
        )

        await self.exec_contexts.update(
            exec_ctx_id, evidence.severity * culp.execution_context,
            evidence.evidence_classes, evidence.triggered_scanners,
            None, now,
        )

        if conv_state and conversation_id:
            await self.conversations.update(
                conversation_id, evidence.severity * culp.conversation,
                evidence.evidence_classes, evidence.triggered_scanners,
                fuzzy_fp, now,
            )

        # ── 7. Run derived detectors ─────────────────────────────────────
        derived_events: list[DerivedEvent] = []

        if direction == "input":
            # Boundary testing
            bt = detect_boundary_testing(
                principal_state.recent_near_threshold_in(60, now),
                principal_state.scanner_families_probed,
                principal_state.total_requests,
                principal_state.recent_blocks_in(30, now),
            )
            if bt:
                derived_events.append(bt)
                evidence.evidence_classes.add(bt.evidence_class)
                evidence.reason_codes.append(bt.reason_code)

            # Retry mutation
            rm = detect_retry_mutation(
                fuzzy_fp,
                list(principal_state.blocked_fingerprints),
                principal_state.recent_blocks_in(60, now),
                (now - principal_state.recent_block_timestamps[-1]) if principal_state.recent_block_timestamps else None,
            )
            if rm:
                derived_events.append(rm)
                evidence.evidence_classes.add(rm.evidence_class)
                evidence.reason_codes.append(rm.reason_code)

            # Distributed probe
            if canon_hash:
                dp = detect_distributed_probe(
                    canon_hash,
                    {canon_hash: self.global_correlation.get_principals(canon_hash, now)},
                    current_severity=evidence.severity,
                )
                if dp:
                    derived_events.append(dp)
                    evidence.evidence_classes.add(dp.evidence_class)
                    evidence.reason_codes.append(dp.reason_code)

            # Streaming bypass
            sb = detect_streaming_bypass(
                is_streaming,
                principal_state.total_violations,
                p_slow,
            )
            if sb:
                derived_events.append(sb)
                evidence.evidence_classes.add(sb.evidence_class)
                evidence.reason_codes.append(sb.reason_code)

        # Multi-turn escalation (conversation scope)
        if conv_state and conversation_confidence > 0.5:
            recent_severities = [
                conv_state.fast_window.score  # approximate from window
            ]
            me = detect_multi_turn_escalation(
                recent_severities, evidence.severity, conversation_confidence,
            )
            if me:
                derived_events.append(me)
                evidence.evidence_classes.add(me.evidence_class)
                evidence.reason_codes.append(me.reason_code)

        # ── 8. Boost severity from derived events (max contribution, not sum)
        if derived_events:
            max_derived = max(d.severity_contribution for d in derived_events)
            evidence.severity = min(1.0, evidence.severity + max_derived * 0.5)
            evidence.confidence = max(
                evidence.confidence,
                max(d.confidence for d in derived_events),
            )

        # ── 9. Run policy ────────────────────────────────────────────────
        policy = decide(
            evidence, principal_state, conv_state,
            is_streaming=is_streaming,
            conversation_confidence=conversation_confidence,
            block_duration_seconds=self.block_duration,
        )

        # ── 10. Apply block if policy says so ────────────────────────────
        if policy.action == PolicyAction.HARD_BLOCK:
            principal_state.block_for(self.block_duration, now)
            if fuzzy_fp:
                principal_state.blocked_fingerprints.append(fuzzy_fp)

        # ── 11. Apply rate limit if policy says so ───────────────────────
        if policy.action == PolicyAction.RATE_LIMIT:
            if principal_id not in self._rate_limiters:
                self._rate_limiters[principal_id] = TokenBucket(
                    capacity=10, refill_rate=0.2, tokens=10.0, last_refill=now,
                )

        # ── 12. Determine risk level ─────────────────────────────────────
        risk_level = determine_risk_level(p_fast, p_slow)

        # ── 13. Persist (fire-and-forget) ────────────────────────────────
        if self.persist_db:
            await risk_persistence.persist_event(
                db_path=self.persist_db,
                correlation_id=correlation_id,
                scope_type="principal",
                scope_id=principal_id,
                direction=direction,
                severity=evidence.severity,
                confidence=evidence.confidence,
                evidence_tags=evidence.evidence_classes,
                signal_attributes=evidence.signal_attributes,
                scanner_scores=scanner_results,
                attack_patterns=evidence.attack_patterns_matched,
                policy_decision=policy.action.value,
                reason_codes=[r.value for r in evidence.reason_codes],
                scan_tier=policy.scan_tier.value,
                trigger_scope_type="principal",
                trigger_scope_id=principal_id,
                trigger_window="fast" if p_fast > p_slow else "slow",
                decision_confidence=evidence.confidence,
                request_fingerprint=canon_hash,
                upstream_target=upstream_target,
                streaming_flag=is_streaming,
                mitigation_source=f"{direction}_scan",
            )

        # ── 14. Periodic cleanup ─────────────────────────────────────────
        self._request_counter += 1
        if self._request_counter % 100 == 0:
            await self._cleanup(now)

        return PostScanDecision(
            policy=policy,
            evidence=evidence,
            risk_level=risk_level,
            correlation_id=correlation_id,
            tarpit_seconds=policy.tarpit_seconds,
        )

    async def _cleanup(self, now: float) -> None:
        """Incremental cleanup across all scope stores."""
        max_idle = 3600.0
        for store in (self.principals, self.networks, self.conversations, self.exec_contexts):
            await store.cleanup(max_idle, now, max_sweep=50)

    async def close(self) -> None:
        """Shutdown: close persistence."""
        await risk_persistence.close()

    def get_response_headers(
        self,
        decision: PostScanDecision | PreRequestDecision,
    ) -> dict[str, str]:
        """Build response headers based on decision. Respects debug mode."""
        headers: dict[str, str] = {
            "X-Seraph-Correlation-ID": decision.correlation_id,
        }

        if isinstance(decision, PostScanDecision):
            headers["X-Seraph-Action"] = decision.policy.action.value
            if decision.policy.action == PolicyAction.HARD_BLOCK:
                headers["Retry-After"] = str(int(decision.policy.retry_after_seconds or self.block_duration))
        elif isinstance(decision, PreRequestDecision):
            headers["X-Seraph-Action"] = decision.action.value
            if decision.action == PolicyAction.HARD_BLOCK:
                headers["Retry-After"] = str(int(decision.retry_after_seconds))

        if self.expose_debug:
            risk_level = decision.risk_level if isinstance(decision, str) else getattr(decision, "risk_level", "normal")
            headers["X-Seraph-Risk-Level"] = str(risk_level)
            if isinstance(decision, PostScanDecision):
                headers["X-Seraph-Evidence"] = ",".join(
                    sorted(e.value for e in decision.evidence.evidence_classes)
                )
                if decision.evidence.reason_codes:
                    headers["X-Seraph-Reason"] = decision.evidence.reason_codes[0].value
                headers["X-Seraph-Scan-Tier"] = decision.policy.scan_tier.value

        return headers


# ── Module singleton ─────────────────────────────────────────────────────────

_risk_engine: RiskEngine | None = None


def get_risk_engine() -> RiskEngine | None:
    """Get the risk engine singleton. Returns None if not initialized (disabled)."""
    return _risk_engine


def init_risk_engine(
    persist_db: str | None = None,
    scanner_weights: dict[str, float] | None = None,
    max_clients: int = 10000,
    block_duration_seconds: float = 300.0,
    max_deep_per_second: int = 5,
    max_enhanced_per_second: int = 20,
    expose_debug_headers: bool = False,
    **kwargs,
) -> RiskEngine:
    """Initialize the risk engine singleton."""
    global _risk_engine
    _risk_engine = RiskEngine(
        persist_db=persist_db,
        scanner_weights=scanner_weights,
        max_clients=max_clients,
        block_duration_seconds=block_duration_seconds,
        max_deep_per_second=max_deep_per_second,
        max_enhanced_per_second=max_enhanced_per_second,
        expose_debug_headers=expose_debug_headers,
        **kwargs,
    )
    logger.info("Risk engine initialized (persist=%s, debug_headers=%s)", persist_db, expose_debug_headers)
    return _risk_engine


async def shutdown_risk_engine() -> None:
    """Shutdown the risk engine singleton."""
    global _risk_engine
    if _risk_engine:
        await _risk_engine.close()
        _risk_engine = None
        logger.info("Risk engine shutdown")
