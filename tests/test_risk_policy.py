"""Unit tests for risk_policy.py — policy decisions and culpability."""
import pytest
from app.services.risk_policy import (
    PolicyAction, ScanTier, StreamTier, PolicyDecision,
    decide, get_culpability, select_scan_tier, select_stream_tier,
    CulpabilityFactors,
)
from app.services.risk_scoring import EvidenceClass, SignalAttribute, ReasonCode, RequestEvidence
from app.services.risk_state import ScopeState


class TestDecide:
    def test_clean_request_allows(self):
        ev = RequestEvidence(severity=0.0, confidence=0.0)
        d = decide(ev, None, None)
        assert d.action == PolicyAction.ALLOW

    def test_high_conf_active_attack_blocks(self):
        ev = RequestEvidence(
            severity=0.9, confidence=0.9, direction="input",
            evidence_classes={EvidenceClass.ACTIVE_ATTACK},
        )
        d = decide(ev, None, None)
        assert d.action == PolicyAction.HARD_BLOCK

    def test_severity_alone_not_enough_for_block(self):
        """High severity but low confidence should NOT hard block."""
        ev = RequestEvidence(
            severity=0.9, confidence=0.3, direction="input",
            evidence_classes={EvidenceClass.ACTIVE_ATTACK},
        )
        d = decide(ev, None, None)
        assert d.action != PolicyAction.HARD_BLOCK

    def test_data_exfil_high_conf_blocks(self):
        ev = RequestEvidence(
            severity=0.8, confidence=0.85, direction="output",
            evidence_classes={EvidenceClass.DATA_EXFIL},
        )
        d = decide(ev, None, None)
        assert d.action == PolicyAction.HARD_BLOCK

    def test_output_unsafe_generation_sanitizes(self):
        ev = RequestEvidence(
            severity=0.8, confidence=0.7, direction="output",
            evidence_classes={EvidenceClass.UNSAFE_GENERATION},
        )
        d = decide(ev, None, None)
        assert d.action == PolicyAction.SANITIZE

    def test_evasion_deepens_scan(self):
        ev = RequestEvidence(
            severity=0.5, confidence=0.6, direction="input",
            evidence_classes={EvidenceClass.EVASION},
        )
        d = decide(ev, None, None)
        assert d.action == PolicyAction.DEEPEN_SCAN

    def test_resource_abuse_rate_limits(self):
        ev = RequestEvidence(
            severity=0.6, confidence=0.7, direction="input",
            evidence_classes={EvidenceClass.RESOURCE_ABUSE},
        )
        d = decide(ev, None, None)
        assert d.action == PolicyAction.RATE_LIMIT

    def test_boundary_testing_tarpits(self):
        ev = RequestEvidence(
            severity=0.5, confidence=0.5, direction="input",
            evidence_classes={EvidenceClass.POLICY_BOUNDARY_TEST},
        )
        d = decide(ev, None, None)
        assert d.action == PolicyAction.TARPIT
        assert d.tarpit_seconds > 0

    def test_moderate_evidence_shadow_flags(self):
        ev = RequestEvidence(
            severity=0.4, confidence=0.4, direction="input",
            evidence_classes={EvidenceClass.RECON},
            reason_codes=[ReasonCode.BOUNDARY_PROBE_DETECTED],
        )
        d = decide(ev, None, None)
        assert d.action == PolicyAction.SHADOW_FLAG


class TestCulpability:
    def test_input_block_strong_principal(self):
        f = get_culpability("input", "block", has_fp_prone=False)
        assert f.principal == 1.0
        assert f.conversation == 1.0

    def test_output_block_weak_principal(self):
        f = get_culpability("output", "block", has_fp_prone=False)
        assert f.principal == 0.1
        assert f.execution_context == 1.0

    def test_fp_prone_capped(self):
        f = get_culpability("input", "block", has_fp_prone=True)
        assert f.principal <= 0.1
        assert f.conversation <= 0.2


class TestScanTierSelection:
    def test_standard(self):
        assert select_scan_tier(0.1) == ScanTier.STANDARD

    def test_enhanced(self):
        assert select_scan_tier(0.4) == ScanTier.ENHANCED

    def test_deep(self):
        assert select_scan_tier(0.7) == ScanTier.DEEP


class TestStreamTierSelection:
    def test_not_streaming(self):
        assert select_stream_tier(ScanTier.DEEP, is_streaming=False) == StreamTier.PASSTHROUGH

    def test_standard_passthrough(self):
        assert select_stream_tier(ScanTier.STANDARD, is_streaming=True) == StreamTier.PASSTHROUGH

    def test_enhanced_rolling(self):
        assert select_stream_tier(ScanTier.ENHANCED, is_streaming=True) == StreamTier.ROLLING_CHUNK_SCAN

    def test_deep_hold_and_release(self):
        assert select_stream_tier(ScanTier.DEEP, is_streaming=True) == StreamTier.HOLD_AND_RELEASE
