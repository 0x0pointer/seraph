"""Unit tests for risk_scoring.py — pure scoring functions."""
import pytest
from app.services.risk_scoring import (
    EvidenceClass, SignalAttribute, OwaspCategory, ReasonCode,
    SCANNER_PROFILES, DEFAULT_SCANNER_WEIGHTS, ATTACK_PATTERNS,
    compute_request_evidence, RequestEvidence,
    _normalize_scanner_name, _get_profile, _get_weight,
)


class TestNormalizeScannerName:
    def test_plain_name(self):
        assert _normalize_scanner_name("PromptInjection") == "PromptInjection"

    def test_keyword_suffix(self):
        assert _normalize_scanner_name("Toxicity (keyword)") == "Toxicity"

    def test_indirect_suffix(self):
        assert _normalize_scanner_name("PromptInjection (indirect)") == "PromptInjection"

    def test_output_suffix(self):
        assert _normalize_scanner_name("Toxicity (output)") == "Toxicity"


class TestGetProfile:
    def test_known_scanner(self):
        profile = _get_profile("PromptInjection")
        assert EvidenceClass.ACTIVE_ATTACK in profile.evidence_classes

    def test_unknown_scanner_gets_default(self):
        profile = _get_profile("NonExistentScanner")
        assert EvidenceClass.RECON in profile.evidence_classes
        assert SignalAttribute.LOW_CONFIDENCE in profile.signal_attributes

    def test_suffix_stripped_for_lookup(self):
        profile = _get_profile("Toxicity (keyword)")
        assert EvidenceClass.UNSAFE_GENERATION in profile.evidence_classes


class TestGetWeight:
    def test_known_weight(self):
        assert _get_weight("PromptInjection") == 1.0

    def test_unknown_weight_default(self):
        assert _get_weight("FakeScanner") == 0.5

    def test_override(self):
        assert _get_weight("PromptInjection", {"PromptInjection": 0.5}) == 0.5

    def test_suffix_stripped(self):
        assert _get_weight("Toxicity (keyword)") == DEFAULT_SCANNER_WEIGHTS["Toxicity"]


class TestComputeRequestEvidence:
    def test_empty_results(self):
        ev = compute_request_evidence({})
        assert ev.severity == 0.0
        assert ev.confidence == 0.0
        assert ev.evidence_classes == set()

    def test_all_negative_scores(self):
        """llm-guard returns -1.0 for valid/clean results."""
        ev = compute_request_evidence({"PromptInjection": -1.0, "Toxicity": -1.0})
        assert ev.severity == 0.0
        assert ev.confidence == 0.0

    def test_single_high_scanner(self):
        ev = compute_request_evidence({"PromptInjection": 0.95})
        assert ev.severity > 0.8
        assert ev.confidence > 0.5
        assert EvidenceClass.ACTIVE_ATTACK in ev.evidence_classes

    def test_multiple_scanners_breadth_bonus(self):
        single = compute_request_evidence({"PromptInjection": 0.8})
        multi = compute_request_evidence({"PromptInjection": 0.8, "BanSubstrings": 0.7, "Regex": 0.6})
        # Multiple triggers should score higher than single
        assert multi.severity > single.severity

    def test_fp_prone_weight_capped(self):
        """FP-prone scanners have capped weight at 0.3."""
        fp = compute_request_evidence({"Bias": 0.95})
        strong = compute_request_evidence({"PromptInjection": 0.95})
        assert fp.severity < strong.severity
        assert fp.confidence < strong.confidence
        assert SignalAttribute.FP_PRONE in fp.signal_attributes

    def test_attack_pattern_detected(self):
        """injection_with_evasion pattern: PromptInjection + Regex + EmbeddingShield."""
        ev = compute_request_evidence({
            "PromptInjection": 0.9,
            "Regex": 0.8,
            "EmbeddingShield": 0.7,
        })
        assert "injection_with_evasion" in ev.attack_patterns_matched
        assert ReasonCode.ATTACK_PATTERN_MATCH in ev.reason_codes

    def test_owasp_categories_populated(self):
        ev = compute_request_evidence({"PromptInjection": 0.9})
        assert OwaspCategory.LLM01 in ev.owasp_categories

    def test_direction_preserved(self):
        ev = compute_request_evidence({"Toxicity": 0.8}, direction="output")
        assert ev.direction == "output"

    def test_high_conf_reason_code(self):
        ev = compute_request_evidence({"PromptInjection": 0.95, "BanSubstrings": 1.0})
        assert ReasonCode.PI_HIGH_CONF in ev.reason_codes

    def test_data_exfil_reason_code(self):
        ev = compute_request_evidence({"InformationShield": 0.9, "Sensitive": 0.8})
        assert ReasonCode.DATA_EXFIL_HIGH_CONF in ev.reason_codes

    def test_resource_abuse_reason_code(self):
        ev = compute_request_evidence({"TokenLimit": 0.9})
        assert ReasonCode.RESOURCE_ABUSE_DETECTED in ev.reason_codes

    def test_custom_weights(self):
        default = compute_request_evidence({"PromptInjection": 0.8})
        custom = compute_request_evidence({"PromptInjection": 0.8}, weight_overrides={"PromptInjection": 0.1})
        assert custom.severity < default.severity

    def test_triggered_scanners_set(self):
        ev = compute_request_evidence({"PromptInjection": 0.9, "Toxicity": -1.0})
        assert "PromptInjection" in ev.triggered_scanners
        assert "Toxicity" not in ev.triggered_scanners

    def test_score_clamped_above_1(self):
        """Severity should never exceed 1.0."""
        ev = compute_request_evidence({
            "PromptInjection": 1.0,
            "EmbeddingShield": 1.0,
            "Regex": 1.0,
            "BanSubstrings": 1.0,
            "InvisibleText": 1.0,
        })
        assert ev.severity <= 1.0


class TestScannerProfileCoverage:
    def test_all_default_weights_have_profiles(self):
        for scanner_name in DEFAULT_SCANNER_WEIGHTS:
            assert scanner_name in SCANNER_PROFILES, f"Missing profile for {scanner_name}"

    def test_all_profiles_have_weights(self):
        for scanner_name in SCANNER_PROFILES:
            assert scanner_name in DEFAULT_SCANNER_WEIGHTS, f"Missing weight for {scanner_name}"

    def test_attack_patterns_reference_real_scanners(self):
        all_scanners = set(SCANNER_PROFILES.keys())
        for name, (scanner_set, bonus) in ATTACK_PATTERNS.items():
            assert scanner_set.issubset(all_scanners), f"Pattern {name} references unknown scanners: {scanner_set - all_scanners}"
