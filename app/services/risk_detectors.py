"""
Derived behavioral detectors — emit evidence events from state patterns.

These sit between per-request scoring and policy. They detect temporal behaviors
that individual scanners cannot see: boundary testing, retry mutation, distributed
probing, streaming bypass preference, multi-turn escalation.

Each detector:
  - Declares which direction(s) it consumes (input/output/metadata)
  - Receives scope state + current evidence
  - Returns an optional DerivedEvent if the pattern is detected
  - Is a pure function of (state, current_evidence) → DerivedEvent | None

Detectors do NOT mutate state — state updates happen in the engine layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.risk_scoring import EvidenceClass, ReasonCode


@dataclass
class DerivedEvent:
    """Output of a derived detector."""
    evidence_class: EvidenceClass
    reason_code: ReasonCode
    severity_contribution: float   # 0.0-1.0, added to request evidence
    confidence: float              # 0.0-1.0
    description: str               # human-readable for logs
    direction: str = "input"       # which direction this detector analyzes


# ── Boundary Testing Detector ────────────────────────────────────────────────
# Direction: input
# Detects: repeated near-threshold attempts, scanner family rotation after rejection

def detect_boundary_testing(
    near_threshold_count_60s: int,
    scanner_families_probed: set[str],
    total_requests: int,
    recent_blocks_30s: int,
) -> DerivedEvent | None:
    """Detect boundary probing — repeated near-threshold attempts.

    Triggers when:
      - 3+ near-threshold attempts in last 60 seconds
      - OR: many scanner families probed relative to request count
      - BOOST: if blocks happened recently (probing after rejection)
    """
    # Many near-threshold attempts
    if near_threshold_count_60s >= 3:
        severity = min(1.0, 0.3 + near_threshold_count_60s * 0.1)
        confidence = 0.7 if recent_blocks_30s > 0 else 0.5
        return DerivedEvent(
            evidence_class=EvidenceClass.POLICY_BOUNDARY_TEST,
            reason_code=ReasonCode.BOUNDARY_PROBE_DETECTED,
            severity_contribution=severity,
            confidence=confidence,
            description=f"Boundary probing: {near_threshold_count_60s} near-threshold attempts in 60s",
            direction="input",
        )

    # Scanner family rotation (probing different defenses)
    if total_requests >= 5 and len(scanner_families_probed) >= 4:
        ratio = len(scanner_families_probed) / max(total_requests, 1)
        if ratio > 0.5:
            return DerivedEvent(
                evidence_class=EvidenceClass.RECON,
                reason_code=ReasonCode.BOUNDARY_PROBE_DETECTED,
                severity_contribution=0.3,
                confidence=0.4,
                description=f"Scanner family rotation: {len(scanner_families_probed)} families in {total_requests} requests",
                direction="input",
            )

    return None


# ── Retry Mutation Detector ──────────────────────────────────────────────────
# Direction: input
# Detects: semantically similar prompts retried shortly after block/rejection

def detect_retry_mutation(
    current_fuzzy_fingerprint: str,
    blocked_fingerprints: list[str],
    recent_blocks_60s: int,
    seconds_since_last_block: float | None,
) -> DerivedEvent | None:
    """Detect retry mutation — similar prompt after rejection.

    Triggers when:
      - Current fuzzy fingerprint matches a recently blocked one
      - AND: block happened within 60 seconds
    """
    if not blocked_fingerprints or recent_blocks_60s == 0:
        return None

    if current_fuzzy_fingerprint in blocked_fingerprints:
        severity = 0.5 if seconds_since_last_block and seconds_since_last_block < 30 else 0.3
        return DerivedEvent(
            evidence_class=EvidenceClass.ACTIVE_ATTACK,
            reason_code=ReasonCode.MUTATION_AFTER_REJECTION,
            severity_contribution=severity,
            confidence=0.75,
            description=f"Retry mutation: fuzzy match to blocked prompt, {seconds_since_last_block:.0f}s after block",
            direction="input",
        )

    # Check if any recent block fingerprint is similar (same first 8 chars = partial match)
    current_prefix = current_fuzzy_fingerprint[:8]
    for fp in blocked_fingerprints[-5:]:
        if fp[:8] == current_prefix and seconds_since_last_block and seconds_since_last_block < 60:
            return DerivedEvent(
                evidence_class=EvidenceClass.ACTIVE_ATTACK,
                reason_code=ReasonCode.RETRY_AFTER_BLOCK,
                severity_contribution=0.25,
                confidence=0.5,
                description="Retry after block: partial fingerprint match within 60s",
                direction="input",
            )

    return None


# ── Distributed Probe Detector ───────────────────────────────────────────────
# Direction: input (ignores output-only unsafe_generation)
# Detects: same payload from multiple principals

def detect_distributed_probe(
    canonical_hash: str,
    global_hash_principals: dict[str, set[str]],
    min_principals: int = 3,
    min_severity: float = 0.3,
    current_severity: float = 0.0,
) -> DerivedEvent | None:
    """Detect distributed probing — same canonical payload from multiple principals.

    global_hash_principals: {canonical_hash: {principal_id, ...}} from global state.
    Only fires if current request has minimum severity (avoids noisy benign matches).
    """
    if current_severity < min_severity:
        return None

    principals = global_hash_principals.get(canonical_hash, set())
    if len(principals) >= min_principals:
        return DerivedEvent(
            evidence_class=EvidenceClass.ACTIVE_ATTACK,
            reason_code=ReasonCode.DISTRIBUTED_PROBE,
            severity_contribution=0.4,
            confidence=0.6 + min(0.3, (len(principals) - min_principals) * 0.1),
            description=f"Distributed probe: same canonical hash from {len(principals)} principals",
            direction="input",
        )

    return None


# ── Streaming Bypass Detector ────────────────────────────────────────────────
# Direction: metadata (request attributes, not scanner output)
# Detects: client switching to streaming after input violations

def detect_streaming_bypass(
    is_streaming: bool,
    recent_input_violations_5min: int,
    principal_slow_score: float,
) -> DerivedEvent | None:
    """Detect streaming bypass preference — client uses streaming to avoid output scanning.

    Triggers when:
      - Current request is streaming
      - AND: client has recent input violations or elevated slow risk
    """
    if not is_streaming:
        return None

    if recent_input_violations_5min >= 2 or principal_slow_score > 0.3:
        return DerivedEvent(
            evidence_class=EvidenceClass.EVASION,
            reason_code=ReasonCode.STREAM_UNINSPECTED,
            severity_contribution=0.2,
            confidence=0.4,
            description=f"Streaming bypass: {recent_input_violations_5min} violations + stream=true",
            direction="input",
        )

    return None


# ── Multi-Turn Escalation Detector ───────────────────────────────────────────
# Direction: input evidence primarily, conversation scope
# Detects: increasing severity across conversation turns

def detect_multi_turn_escalation(
    conversation_evidence_history: list[float],
    current_severity: float,
    conversation_confidence: float,
) -> DerivedEvent | None:
    """Detect multi-turn escalation — severity increasing across conversation.

    conversation_evidence_history: list of severity scores from recent turns.
    Only considers conversations with medium+ confidence ID.

    Pattern: benign (0.1) → probing (0.3) → extraction (0.6+) = escalation.
    """
    if conversation_confidence < 0.5:
        return None

    if len(conversation_evidence_history) < 2:
        return None

    # Check for monotonically increasing severity pattern
    recent = conversation_evidence_history[-3:]  # last 3 turns
    if len(recent) >= 2 and current_severity > 0.4:
        increasing = all(recent[i] <= recent[i + 1] for i in range(len(recent) - 1))
        if increasing and current_severity > recent[0] + 0.2:
            return DerivedEvent(
                evidence_class=EvidenceClass.ACTIVE_ATTACK,
                reason_code=ReasonCode.CONVERSATION_ESCALATION,
                severity_contribution=0.35,
                confidence=min(0.8, conversation_confidence),
                description=f"Multi-turn escalation: severity {recent[0]:.2f} → {current_severity:.2f}",
                direction="input",
            )

    return None
