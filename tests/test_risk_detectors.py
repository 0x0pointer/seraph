"""Unit tests for risk_detectors.py — derived behavioral detectors."""
import pytest
from app.services.risk_detectors import (
    detect_boundary_testing,
    detect_retry_mutation,
    detect_distributed_probe,
    detect_streaming_bypass,
    detect_multi_turn_escalation,
)
from app.services.risk_scoring import EvidenceClass, ReasonCode


class TestBoundaryTesting:
    def test_triggers_on_many_near_threshold(self):
        ev = detect_boundary_testing(
            near_threshold_count_60s=4,
            scanner_families_probed=set(),
            total_requests=10,
            recent_blocks_30s=0,
        )
        assert ev is not None
        assert ev.evidence_class == EvidenceClass.POLICY_BOUNDARY_TEST

    def test_boosted_by_recent_blocks(self):
        ev = detect_boundary_testing(4, set(), 10, recent_blocks_30s=2)
        assert ev is not None
        assert ev.confidence > 0.5  # boosted

    def test_no_trigger_below_threshold(self):
        ev = detect_boundary_testing(1, set(), 5, 0)
        assert ev is None

    def test_scanner_family_rotation(self):
        ev = detect_boundary_testing(0, {"A", "B", "C", "D", "E"}, 8, 0)
        assert ev is not None
        assert ev.evidence_class == EvidenceClass.RECON


class TestRetryMutation:
    def test_exact_fuzzy_match(self):
        ev = detect_retry_mutation("abc123", ["abc123"], recent_blocks_60s=1, seconds_since_last_block=10.0)
        assert ev is not None
        assert ev.reason_code == ReasonCode.MUTATION_AFTER_REJECTION

    def test_no_match_different_fingerprint(self):
        ev = detect_retry_mutation("new_fp", ["old_fp"], recent_blocks_60s=1, seconds_since_last_block=10.0)
        assert ev is None

    def test_no_trigger_without_recent_blocks(self):
        ev = detect_retry_mutation("abc123", ["abc123"], recent_blocks_60s=0, seconds_since_last_block=None)
        assert ev is None

    def test_partial_prefix_match(self):
        ev = detect_retry_mutation("abc12345_new", ["abc12345_old"], recent_blocks_60s=1, seconds_since_last_block=20.0)
        assert ev is not None
        assert ev.reason_code == ReasonCode.RETRY_AFTER_BLOCK


class TestDistributedProbe:
    def test_triggers_on_many_principals(self):
        ev = detect_distributed_probe(
            "hash1",
            {"hash1": {"user1", "user2", "user3", "user4"}},
            min_principals=3,
            current_severity=0.5,
        )
        assert ev is not None
        assert ev.reason_code == ReasonCode.DISTRIBUTED_PROBE

    def test_no_trigger_below_min_principals(self):
        ev = detect_distributed_probe("hash1", {"hash1": {"user1", "user2"}}, min_principals=3, current_severity=0.5)
        assert ev is None

    def test_no_trigger_below_severity_floor(self):
        ev = detect_distributed_probe("hash1", {"hash1": {"u1", "u2", "u3"}}, min_principals=3, current_severity=0.1)
        assert ev is None


class TestStreamingBypass:
    def test_triggers_on_streaming_with_violations(self):
        ev = detect_streaming_bypass(is_streaming=True, recent_input_violations_5min=3, principal_slow_score=0.4)
        assert ev is not None
        assert ev.reason_code == ReasonCode.STREAM_UNINSPECTED

    def test_no_trigger_not_streaming(self):
        ev = detect_streaming_bypass(is_streaming=False, recent_input_violations_5min=5, principal_slow_score=0.8)
        assert ev is None

    def test_no_trigger_clean_client(self):
        ev = detect_streaming_bypass(is_streaming=True, recent_input_violations_5min=0, principal_slow_score=0.1)
        assert ev is None


class TestMultiTurnEscalation:
    def test_escalating_pattern(self):
        ev = detect_multi_turn_escalation([0.1, 0.3, 0.5], current_severity=0.7, conversation_confidence=0.8)
        assert ev is not None
        assert ev.reason_code == ReasonCode.CONVERSATION_ESCALATION

    def test_no_trigger_decreasing(self):
        ev = detect_multi_turn_escalation([0.5, 0.3], current_severity=0.2, conversation_confidence=0.8)
        assert ev is None

    def test_no_trigger_low_conversation_confidence(self):
        ev = detect_multi_turn_escalation([0.1, 0.3, 0.5], current_severity=0.7, conversation_confidence=0.2)
        assert ev is None

    def test_no_trigger_insufficient_history(self):
        ev = detect_multi_turn_escalation([0.3], current_severity=0.7, conversation_confidence=0.8)
        assert ev is None
