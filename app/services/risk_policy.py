"""
Policy decision engine — maps evidence + state → enforcement action.

Decision precedence (top to bottom, first match wins):
  1. Hard deny checks (blocked state, expired block check)
  2. Rate limit checks (token bucket per scope)
  3. Stream tier upgrade checks
  4. Scan tier upgrade checks (adaptive scanning)
  5. Sanitize / reask / tarpit decisions
  6. Header / debug exposure

Hard block requires: high severity + high confidence
    OR: repeated medium evidence in fast window.
    Severity alone is NEVER enough.

Input vs output have different culpability:
  - Input violations → strongly affect principal + conversation state
  - Output violations → affect conversation + execution_context, weakly affect principal

All functions are pure (no state mutation, no I/O).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from app.services.risk_scoring import EvidenceClass, SignalAttribute, ReasonCode, RequestEvidence
from app.services.risk_state import RiskLevel, ScopeState


# ── Policy Actions ───────────────────────────────────────────────────────────

class PolicyAction(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_HEADERS = "allow_with_headers"
    SHADOW_FLAG = "shadow_flag"              # no user-visible change, elevated monitoring
    DEEPEN_SCAN = "deepen_scan"              # run extra scanners for risky clients
    SANITIZE = "sanitize"                    # fix/redact output
    REASK = "reask"                          # reject with correction hint
    TARPIT = "tarpit"                        # randomized delay
    RATE_LIMIT = "rate_limit"                # token bucket exhausted
    CONVERSATION_QUARANTINE = "conv_quarantine"  # all future turns get deepened
    HARD_BLOCK = "hard_block"                # 429 rejection


# ── Scan Tiers ───────────────────────────────────────────────────────────────

class ScanTier(str, Enum):
    STANDARD = "standard"
    ENHANCED = "enhanced"
    DEEP = "deep"


# ── Stream Tiers ─────────────────────────────────────────────────────────────

class StreamTier(str, Enum):
    PASSTHROUGH = "passthrough"
    ROLLING_CHUNK_SCAN = "rolling_chunk_scan"
    HOLD_AND_RELEASE = "hold_and_release"


# ── Policy Decision (output of policy engine) ────────────────────────────────

@dataclass
class PolicyDecision:
    action: PolicyAction
    primary_reason: ReasonCode
    secondary_reasons: list[ReasonCode] = field(default_factory=list)
    scan_tier: ScanTier = ScanTier.STANDARD
    stream_tier: StreamTier = StreamTier.PASSTHROUGH
    tarpit_seconds: float = 0.0
    block_duration_seconds: float = 0.0
    trigger_scope_type: str = ""
    trigger_scope_id: str = ""
    retry_after_seconds: float = 0.0
    confidence: float = 0.0


# ── Culpability Matrix ───────────────────────────────────────────────────────
# How much each direction contributes to each scope's state update.

@dataclass(frozen=True)
class CulpabilityFactors:
    principal: float
    conversation: float
    execution_context: float
    network: float


CULPABILITY_MATRIX: dict[tuple[str, str], CulpabilityFactors] = {
    # (direction, outcome) → factors
    ("input", "block"):   CulpabilityFactors(principal=1.0, conversation=1.0, execution_context=0.0, network=0.5),
    ("input", "monitor"): CulpabilityFactors(principal=0.2, conversation=0.5, execution_context=0.0, network=0.1),
    ("input", "fix"):     CulpabilityFactors(principal=0.3, conversation=0.5, execution_context=0.0, network=0.2),
    ("input", "reask"):   CulpabilityFactors(principal=0.5, conversation=0.7, execution_context=0.0, network=0.3),
    ("output", "block"):  CulpabilityFactors(principal=0.1, conversation=0.5, execution_context=1.0, network=0.0),
    ("output", "monitor"): CulpabilityFactors(principal=0.0, conversation=0.2, execution_context=0.5, network=0.0),
    ("output", "fix"):    CulpabilityFactors(principal=0.0, conversation=0.3, execution_context=0.7, network=0.0),
    ("output", "reask"):  CulpabilityFactors(principal=0.1, conversation=0.4, execution_context=0.8, network=0.0),
}

# FP-prone scanners get capped culpability
FP_PRONE_CAP = CulpabilityFactors(principal=0.1, conversation=0.2, execution_context=0.2, network=0.05)


def get_culpability(
    direction: str,
    outcome: str,
    has_fp_prone: bool,
) -> CulpabilityFactors:
    """Get culpability factors for a given direction + outcome.

    If FP-prone signals are present, cap the factors.
    """
    base = CULPABILITY_MATRIX.get((direction, outcome))
    if base is None:
        base = CulpabilityFactors(principal=0.5, conversation=0.5, execution_context=0.5, network=0.2)

    if has_fp_prone:
        return CulpabilityFactors(
            principal=min(base.principal, FP_PRONE_CAP.principal),
            conversation=min(base.conversation, FP_PRONE_CAP.conversation),
            execution_context=min(base.execution_context, FP_PRONE_CAP.execution_context),
            network=min(base.network, FP_PRONE_CAP.network),
        )

    return base


# ── Scan Tier Selection ──────────────────────────────────────────────────────

def select_scan_tier(
    principal_slow_score: float,
    elevated_threshold: float = 0.3,
    high_threshold: float = 0.6,
) -> ScanTier:
    """Select scan tier based on principal's slow-window risk."""
    if principal_slow_score >= high_threshold:
        return ScanTier.DEEP
    if principal_slow_score >= elevated_threshold:
        return ScanTier.ENHANCED
    return ScanTier.STANDARD


def select_stream_tier(
    scan_tier: ScanTier,
    is_streaming: bool,
) -> StreamTier:
    """Select stream tier based on scan tier and whether request is streaming."""
    if not is_streaming:
        return StreamTier.PASSTHROUGH  # not a streaming request
    if scan_tier == ScanTier.DEEP:
        return StreamTier.HOLD_AND_RELEASE
    if scan_tier == ScanTier.ENHANCED:
        return StreamTier.ROLLING_CHUNK_SCAN
    return StreamTier.PASSTHROUGH


# ── Policy Decision Logic ────────────────────────────────────────────────────

def decide(
    evidence: RequestEvidence,
    principal_state: ScopeState | None,
    conversation_state: ScopeState | None,
    is_streaming: bool = False,
    conversation_confidence: float = 0.3,
    block_duration_seconds: float = 300.0,
    tarpit_min: float = 1.0,
    tarpit_max: float = 5.0,
) -> PolicyDecision:
    """
    Main policy decision function.

    Evaluates evidence + state using decision precedence order.
    Returns exactly one PolicyDecision with one primary action and reason.
    """
    now_fast = principal_state.fast_window.current(principal_state.last_request_time) if principal_state else 0.0
    now_slow = principal_state.slow_window.current(principal_state.last_request_time) if principal_state else 0.0

    scan_tier = select_scan_tier(now_slow)
    stream_tier = select_stream_tier(scan_tier, is_streaming)

    # ── 1. Hard block: high severity + high confidence ───────────────────
    if (evidence.severity > 0.7 and evidence.confidence > 0.85
            and EvidenceClass.ACTIVE_ATTACK in evidence.evidence_classes):
        return PolicyDecision(
            action=PolicyAction.HARD_BLOCK,
            primary_reason=ReasonCode.PI_HIGH_CONF,
            block_duration_seconds=block_duration_seconds,
            scan_tier=scan_tier,
            stream_tier=stream_tier,
            confidence=evidence.confidence,
            retry_after_seconds=block_duration_seconds,
        )

    # ── 2. Hard block: data exfil with high confidence ───────────────────
    if (evidence.severity > 0.6 and evidence.confidence > 0.8
            and EvidenceClass.DATA_EXFIL in evidence.evidence_classes):
        return PolicyDecision(
            action=PolicyAction.HARD_BLOCK,
            primary_reason=ReasonCode.DATA_EXFIL_HIGH_CONF,
            block_duration_seconds=block_duration_seconds,
            scan_tier=scan_tier,
            stream_tier=stream_tier,
            confidence=evidence.confidence,
            retry_after_seconds=block_duration_seconds,
        )

    # ── 3. Hard block: repeated medium attacks in fast window ────────────
    # Requires 8+ events AND high fast window AND evidence is input-direction
    if (principal_state
            and principal_state.recent_events_in(60, principal_state.last_request_time) > 8
            and evidence.direction == "input"):
        if now_fast > 0.8 and evidence.severity > 0.5:
            return PolicyDecision(
                action=PolicyAction.HARD_BLOCK,
                primary_reason=ReasonCode.RETRY_AFTER_BLOCK,
                block_duration_seconds=block_duration_seconds,
                scan_tier=scan_tier,
                stream_tier=stream_tier,
                confidence=0.7,
                retry_after_seconds=block_duration_seconds,
            )

    # ── 4. Output-only unsafe generation → sanitize, don't punish principal
    if (EvidenceClass.UNSAFE_GENERATION in evidence.evidence_classes
            and evidence.direction == "output"
            and EvidenceClass.ACTIVE_ATTACK not in evidence.evidence_classes):
        return PolicyDecision(
            action=PolicyAction.SANITIZE,
            primary_reason=ReasonCode.UNSAFE_OUTPUT_DETECTED,
            scan_tier=scan_tier,
            stream_tier=stream_tier,
            confidence=evidence.confidence,
        )

    # ── 5. Resource abuse → rate limit ───────────────────────────────────
    if EvidenceClass.RESOURCE_ABUSE in evidence.evidence_classes and evidence.severity > 0.4:
        return PolicyDecision(
            action=PolicyAction.RATE_LIMIT,
            primary_reason=ReasonCode.RESOURCE_ABUSE_DETECTED,
            scan_tier=scan_tier,
            stream_tier=stream_tier,
            confidence=evidence.confidence,
        )

    # ── 6. Evasion detected → deepen scanning ───────────────────────────
    if EvidenceClass.EVASION in evidence.evidence_classes and evidence.severity > 0.3:
        return PolicyDecision(
            action=PolicyAction.DEEPEN_SCAN,
            primary_reason=ReasonCode.PATTERN_EVASION_CLUSTER,
            scan_tier=max(scan_tier, ScanTier.ENHANCED, key=lambda t: list(ScanTier).index(t)),
            stream_tier=stream_tier,
            confidence=evidence.confidence,
        )

    # ── 7. Boundary testing (derived) + repeat → tarpit ──────────────────
    if EvidenceClass.POLICY_BOUNDARY_TEST in evidence.evidence_classes:
        jitter = random.uniform(tarpit_min, tarpit_max)
        return PolicyDecision(
            action=PolicyAction.TARPIT,
            primary_reason=ReasonCode.BOUNDARY_PROBE_DETECTED,
            tarpit_seconds=jitter,
            scan_tier=scan_tier,
            stream_tier=stream_tier,
            confidence=evidence.confidence,
        )

    # ── 8. Multi-turn escalation → conversation quarantine ───────────────
    if (EvidenceClass.ACTIVE_ATTACK in evidence.evidence_classes
            and conversation_state
            and conversation_confidence > 0.5):
        conv_events = conversation_state.recent_events_in(300, conversation_state.last_request_time)
        if conv_events >= 3 and now_fast > 0.4:
            return PolicyDecision(
                action=PolicyAction.CONVERSATION_QUARANTINE,
                primary_reason=ReasonCode.CONVERSATION_ESCALATION,
                scan_tier=ScanTier.DEEP,
                stream_tier=StreamTier.HOLD_AND_RELEASE if is_streaming else StreamTier.PASSTHROUGH,
                confidence=evidence.confidence * conversation_confidence,
            )

    # ── 9. Streaming from elevated client → upgrade stream tier ──────────
    if is_streaming and now_slow > 0.3:
        return PolicyDecision(
            action=PolicyAction.ALLOW_WITH_HEADERS,
            primary_reason=ReasonCode.STREAM_UNINSPECTED,
            scan_tier=scan_tier,
            stream_tier=stream_tier,  # already upgraded by select_stream_tier
            confidence=evidence.confidence,
        )

    # ── 10. Any moderate evidence → shadow flag ──────────────────────────
    if evidence.severity > 0.3 and evidence.confidence > 0.3:
        return PolicyDecision(
            action=PolicyAction.SHADOW_FLAG,
            primary_reason=evidence.reason_codes[0] if evidence.reason_codes else ReasonCode.PI_HIGH_CONF,
            scan_tier=scan_tier,
            stream_tier=stream_tier,
            confidence=evidence.confidence,
        )

    # ── 11. Low evidence with some signal → headers only ─────────────────
    if evidence.severity > 0.1:
        return PolicyDecision(
            action=PolicyAction.ALLOW_WITH_HEADERS,
            primary_reason=evidence.reason_codes[0] if evidence.reason_codes else ReasonCode.PI_HIGH_CONF,
            scan_tier=scan_tier,
            stream_tier=stream_tier,
            confidence=evidence.confidence,
        )

    # ── 12. Clean → allow ────────────────────────────────────────────────
    return PolicyDecision(
        action=PolicyAction.ALLOW,
        primary_reason=ReasonCode.PI_HIGH_CONF,  # placeholder, no evidence
        scan_tier=scan_tier,
        stream_tier=stream_tier,
        confidence=0.0,
    )
