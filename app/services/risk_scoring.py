"""
Risk scoring — pure functions for per-request evidence computation.

Consumes scanner results (dict[str, float]) and produces structured evidence:
severity, confidence, evidence classes, OWASP categories, attack pattern bonuses.

All functions are pure (no state, no I/O) and fully testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ── Evidence Classes (operational taxonomy) ──────────────────────────────────
# These drive runtime policy decisions. NOT the same as OWASP categories
# (which are for reporting/analytics only).

class EvidenceClass(str, Enum):
    ACTIVE_ATTACK = "active_attack"           # Direct injection attempts
    EVASION = "evasion"                       # Unicode tricks, encoding, leetspeak
    RECON = "recon"                           # Probing guardrail boundaries
    RESOURCE_ABUSE = "resource_abuse"         # Token bombing, gibberish flooding
    DATA_EXFIL = "data_exfil"                 # Credential/secret extraction attempts
    UNSAFE_GENERATION = "unsafe_generation"   # Toxic/harmful output from LLM
    POLICY_BOUNDARY_TEST = "policy_test"      # Derived detector only (not from scanners)


# ── Signal Attributes (quality metadata, not behavior) ──────────────────────
# Describe detector quality, not user behavior. Used to cap contributions.

class SignalAttribute(str, Enum):
    FP_PRONE = "fp_prone"
    LOW_CONFIDENCE = "low_confidence"
    OUTPUT_ONLY = "output_only"
    HEURISTIC_ONLY = "heuristic_only"


# ── OWASP LLM Top 10 Categories (reporting only) ────────────────────────────

class OwaspCategory(str, Enum):
    LLM01 = "LLM01_PromptInjection"
    LLM02 = "LLM02_InsecureOutput"
    LLM03 = "LLM03_TrainingPoisoning"
    LLM04 = "LLM04_ModelDoS"
    LLM05 = "LLM05_SupplyChain"
    LLM06 = "LLM06_SensitiveInfoDisclosure"
    LLM07 = "LLM07_InsecurePlugin"
    LLM08 = "LLM08_ExcessiveAgency"
    LLM09 = "LLM09_Overreliance"
    LLM10 = "LLM10_UnboundedConsumption"


# ── Reason Codes (structured, stable for tests/analytics) ───────────────────

class ReasonCode(str, Enum):
    PI_HIGH_CONF = "pi_high_conf"
    RETRY_AFTER_BLOCK = "retry_after_block"
    STREAM_UNINSPECTED = "stream_uninspected"
    PATTERN_EVASION_CLUSTER = "pattern_evasion_cluster"
    BOUNDARY_PROBE_DETECTED = "boundary_probe_detected"
    MUTATION_AFTER_REJECTION = "mutation_after_rejection"
    DISTRIBUTED_PROBE = "distributed_probe"
    CONVERSATION_ESCALATION = "conversation_escalation"
    GLOBAL_PAYLOAD_MATCH = "global_payload_match"
    BUDGET_DEGRADED = "budget_degraded"
    HEURISTIC_CONVERSATION = "heuristic_conversation"
    DATA_EXFIL_HIGH_CONF = "data_exfil_high_conf"
    ATTACK_PATTERN_MATCH = "attack_pattern_match"
    RESOURCE_ABUSE_DETECTED = "resource_abuse_detected"
    UNSAFE_OUTPUT_DETECTED = "unsafe_output_detected"


# ── Scanner → Evidence Mapping ───────────────────────────────────────────────
# Each scanner maps to (evidence_classes, signal_attributes).

@dataclass(frozen=True)
class ScannerProfile:
    evidence_classes: tuple[EvidenceClass, ...]
    signal_attributes: tuple[SignalAttribute, ...] = ()
    owasp: tuple[OwaspCategory, ...] = ()


SCANNER_PROFILES: dict[str, ScannerProfile] = {
    # Input scanners — active attack detection
    "PromptInjection":   ScannerProfile((EvidenceClass.ACTIVE_ATTACK,),                                 owasp=(OwaspCategory.LLM01,)),
    "EmbeddingShield":   ScannerProfile((EvidenceClass.ACTIVE_ATTACK,),                                 owasp=(OwaspCategory.LLM01,)),
    "BanSubstrings":     ScannerProfile((EvidenceClass.ACTIVE_ATTACK, EvidenceClass.RECON),              owasp=(OwaspCategory.LLM01, OwaspCategory.LLM02)),
    "Regex":             ScannerProfile((EvidenceClass.ACTIVE_ATTACK, EvidenceClass.EVASION),             owasp=(OwaspCategory.LLM01, OwaspCategory.LLM06)),
    "InvisibleText":     ScannerProfile((EvidenceClass.EVASION,),                                        owasp=(OwaspCategory.LLM01,)),
    "Language":          ScannerProfile((EvidenceClass.EVASION,),          (SignalAttribute.FP_PRONE,),   owasp=(OwaspCategory.LLM01,)),
    "CustomRule":        ScannerProfile((EvidenceClass.ACTIVE_ATTACK,),                                  owasp=(OwaspCategory.LLM01,)),

    # Input scanners — data protection
    "Secrets":           ScannerProfile((EvidenceClass.DATA_EXFIL,),       (SignalAttribute.FP_PRONE,),   owasp=(OwaspCategory.LLM06,)),
    "Anonymize":         ScannerProfile((EvidenceClass.DATA_EXFIL,),                                     owasp=(OwaspCategory.LLM06,)),

    # Input scanners — content safety
    "Toxicity":          ScannerProfile((EvidenceClass.UNSAFE_GENERATION,),                               owasp=(OwaspCategory.LLM02,)),
    "BanTopics":         ScannerProfile((EvidenceClass.UNSAFE_GENERATION, EvidenceClass.ACTIVE_ATTACK),   owasp=(OwaspCategory.LLM02,)),
    "BanCode":           ScannerProfile((EvidenceClass.UNSAFE_GENERATION,), (SignalAttribute.FP_PRONE,),  owasp=(OwaspCategory.LLM02, OwaspCategory.LLM08)),
    "Code":              ScannerProfile((EvidenceClass.UNSAFE_GENERATION,), (SignalAttribute.FP_PRONE,),  owasp=(OwaspCategory.LLM02, OwaspCategory.LLM08)),

    # Input scanners — resource protection
    "TokenLimit":        ScannerProfile((EvidenceClass.RESOURCE_ABUSE,),                                  owasp=(OwaspCategory.LLM04, OwaspCategory.LLM10)),
    "Gibberish":         ScannerProfile((EvidenceClass.RESOURCE_ABUSE, EvidenceClass.EVASION),            owasp=(OwaspCategory.LLM04,)),

    # Input scanners — monitoring (low impact)
    "BanCompetitors":    ScannerProfile((EvidenceClass.RECON,),            (SignalAttribute.FP_PRONE,),   owasp=(OwaspCategory.LLM02,)),
    "Sentiment":         ScannerProfile((),                                (SignalAttribute.FP_PRONE,)),
    "EmotionDetection":  ScannerProfile((),                                (SignalAttribute.FP_PRONE,)),

    # Output scanners — data protection
    "InformationShield": ScannerProfile((EvidenceClass.DATA_EXFIL,),       (SignalAttribute.OUTPUT_ONLY,), owasp=(OwaspCategory.LLM06,)),
    "Sensitive":         ScannerProfile((EvidenceClass.DATA_EXFIL,),       (SignalAttribute.OUTPUT_ONLY,), owasp=(OwaspCategory.LLM06,)),
    "Deanonymize":       ScannerProfile((EvidenceClass.DATA_EXFIL,),       (SignalAttribute.OUTPUT_ONLY,), owasp=(OwaspCategory.LLM06,)),

    # Output scanners — content safety
    "MaliciousURLs":     ScannerProfile((EvidenceClass.UNSAFE_GENERATION,), (SignalAttribute.OUTPUT_ONLY,), owasp=(OwaspCategory.LLM02,)),
    "Bias":              ScannerProfile((EvidenceClass.UNSAFE_GENERATION,), (SignalAttribute.FP_PRONE, SignalAttribute.OUTPUT_ONLY), owasp=(OwaspCategory.LLM02,)),

    # Output scanners — quality (low impact)
    "NoRefusal":         ScannerProfile((),                                (SignalAttribute.FP_PRONE, SignalAttribute.OUTPUT_ONLY)),
    "NoRefusalLight":    ScannerProfile((),                                (SignalAttribute.FP_PRONE, SignalAttribute.OUTPUT_ONLY)),
    "FactualConsistency": ScannerProfile((),                               (SignalAttribute.OUTPUT_ONLY,), owasp=(OwaspCategory.LLM09,)),
    "Relevance":         ScannerProfile((),                                (SignalAttribute.OUTPUT_ONLY,), owasp=(OwaspCategory.LLM09,)),
    "LanguageSame":      ScannerProfile((EvidenceClass.EVASION,),          (SignalAttribute.OUTPUT_ONLY,), owasp=(OwaspCategory.LLM02,)),
    "JSON":              ScannerProfile((),                                (SignalAttribute.OUTPUT_ONLY,)),
    "ReadingTime":       ScannerProfile((),                                (SignalAttribute.FP_PRONE,)),
    "URLReachability":   ScannerProfile((),                                (SignalAttribute.FP_PRONE,)),
}

# Fallback for unknown scanners
_DEFAULT_PROFILE = ScannerProfile((EvidenceClass.RECON,), (SignalAttribute.LOW_CONFIDENCE,))


# ── Scanner Weights ──────────────────────────────────────────────────────────
# Higher = more impactful on risk score. Active attack > data protection >
# content safety > resource > monitoring.

DEFAULT_SCANNER_WEIGHTS: dict[str, float] = {
    "PromptInjection": 1.0,
    "EmbeddingShield": 0.95,
    "InvisibleText": 0.9,
    "BanSubstrings": 0.85,
    "Regex": 0.8,
    "CustomRule": 0.8,
    "Secrets": 0.9,
    "Anonymize": 0.7,
    "InformationShield": 0.95,
    "Sensitive": 0.8,
    "Deanonymize": 0.7,
    "Toxicity": 0.7,
    "BanTopics": 0.6,
    "MaliciousURLs": 0.8,
    "BanCode": 0.5,
    "Code": 0.5,
    "TokenLimit": 0.6,
    "Gibberish": 0.4,
    "BanCompetitors": 0.2,
    "Bias": 0.3,
    "NoRefusal": 0.1,
    "NoRefusalLight": 0.1,
    "Language": 0.2,
    "LanguageSame": 0.1,
    "Sentiment": 0.1,
    "EmotionDetection": 0.1,
    "ReadingTime": 0.05,
    "JSON": 0.1,
    "Relevance": 0.2,
    "FactualConsistency": 0.3,
    "URLReachability": 0.1,
}

_DEFAULT_WEIGHT = 0.5


# ── Attack Pattern Interaction Bonuses ───────────────────────────────────────
# When specific scanner combinations fire together, it indicates a coordinated
# attack that's more dangerous than individual triggers suggest.

ATTACK_PATTERNS: dict[str, tuple[frozenset[str], float]] = {
    "evasion_cluster":        (frozenset({"PromptInjection", "InvisibleText", "BanSubstrings"}), 0.30),
    "injection_with_evasion": (frozenset({"PromptInjection", "Regex", "EmbeddingShield"}),       0.35),
    "data_exfil_cluster":     (frozenset({"Secrets", "Sensitive", "InformationShield"}),          0.30),
    "social_engineering":     (frozenset({"EmbeddingShield", "InformationShield"}),               0.25),
    "dos_probing":            (frozenset({"TokenLimit", "Gibberish"}),                            0.20),
}


# ── Request Evidence (output of scoring) ─────────────────────────────────────

@dataclass
class RequestEvidence:
    severity: float                            # 0.0-1.0, how bad in isolation
    confidence: float                          # 0.0-1.0, how certain it's malicious
    evidence_classes: set[EvidenceClass] = field(default_factory=set)
    signal_attributes: set[SignalAttribute] = field(default_factory=set)
    owasp_categories: set[OwaspCategory] = field(default_factory=set)
    scanner_contributions: dict[str, float] = field(default_factory=dict)
    attack_patterns_matched: list[str] = field(default_factory=list)
    reason_codes: list[ReasonCode] = field(default_factory=list)
    direction: str = "input"                   # "input" or "output"
    triggered_scanners: set[str] = field(default_factory=set)


# ── Pure Scoring Functions ───────────────────────────────────────────────────

def _normalize_scanner_name(name: str) -> str:
    """Strip suffixes like ' (keyword)', ' (indirect)', ' (output)' for weight/profile lookup."""
    if " (" in name:
        return name.split(" (")[0]
    return name


def _get_profile(scanner_name: str) -> ScannerProfile:
    """Get scanner profile, falling back to default for unknown scanners."""
    base = _normalize_scanner_name(scanner_name)
    return SCANNER_PROFILES.get(base, _DEFAULT_PROFILE)


def _get_weight(scanner_name: str, weight_overrides: dict[str, float] | None = None) -> float:
    """Get scanner weight with optional overrides."""
    base = _normalize_scanner_name(scanner_name)
    if weight_overrides and base in weight_overrides:
        return weight_overrides[base]
    return DEFAULT_SCANNER_WEIGHTS.get(base, _DEFAULT_WEIGHT)


def compute_request_evidence(
    scanner_results: dict[str, float],
    direction: str = "input",
    weight_overrides: dict[str, float] | None = None,
) -> RequestEvidence:
    """
    Compute structured evidence from scanner results for one scan (input or output).

    scanner_results: from scanner_engine, keys are scanner names,
                     values are -1.0 (valid/clean) to 1.0 (high risk).
                     llm-guard uses negative scores for passing scanners.

    Returns RequestEvidence with severity, confidence, evidence classes,
    OWASP categories, attack patterns, and reason codes.
    """
    evidence = RequestEvidence(severity=0.0, confidence=0.0, direction=direction)

    if not scanner_results:
        return evidence

    weighted_scores: list[float] = []
    hard_evidence_count = 0
    soft_evidence_count = 0
    triggered_base_names: set[str] = set()

    for scanner_name, raw_score in scanner_results.items():
        # llm-guard returns -1.0 for valid results — clamp to [0, 1]
        score = max(0.0, min(1.0, raw_score))
        if score <= 0.0:
            continue

        base_name = _normalize_scanner_name(scanner_name)
        profile = _get_profile(scanner_name)
        weight = _get_weight(scanner_name, weight_overrides)

        # Cap contribution from FP-prone scanners
        if SignalAttribute.FP_PRONE in profile.signal_attributes:
            weight = min(weight, 0.3)

        weighted = score * weight
        weighted_scores.append(weighted)

        # Accumulate evidence
        evidence.scanner_contributions[scanner_name] = weighted
        evidence.evidence_classes.update(profile.evidence_classes)
        evidence.signal_attributes.update(profile.signal_attributes)
        evidence.owasp_categories.update(profile.owasp)
        evidence.triggered_scanners.add(base_name)
        triggered_base_names.add(base_name)

        # Count hard vs soft evidence for confidence
        if SignalAttribute.FP_PRONE not in profile.signal_attributes:
            hard_evidence_count += 1
        else:
            soft_evidence_count += 1

    if not weighted_scores:
        return evidence

    # ── Severity: max weighted score + breadth bonus + attack pattern bonus ─
    severity_peak = max(weighted_scores)
    breadth_bonus = min(0.3, (len(weighted_scores) - 1) * 0.1) * severity_peak

    # Attack pattern bonuses
    pattern_bonus = 0.0
    for pattern_name, (scanner_set, bonus) in ATTACK_PATTERNS.items():
        if scanner_set.issubset(triggered_base_names):
            pattern_bonus = max(pattern_bonus, bonus)
            evidence.attack_patterns_matched.append(pattern_name)

    evidence.severity = min(1.0, severity_peak + breadth_bonus + pattern_bonus)

    # ── Confidence: based on evidence quality ────────────────────────────────
    if hard_evidence_count >= 2:
        evidence.confidence = min(1.0, 0.7 + hard_evidence_count * 0.1)
    elif hard_evidence_count == 1:
        evidence.confidence = 0.6 + severity_peak * 0.3
    elif soft_evidence_count > 0:
        evidence.confidence = min(0.5, soft_evidence_count * 0.15)
    else:
        evidence.confidence = 0.1

    # ── Reason codes ─────────────────────────────────────────────────────────
    if EvidenceClass.ACTIVE_ATTACK in evidence.evidence_classes and evidence.confidence > 0.8:
        evidence.reason_codes.append(ReasonCode.PI_HIGH_CONF)
    if EvidenceClass.DATA_EXFIL in evidence.evidence_classes and evidence.confidence > 0.7:
        evidence.reason_codes.append(ReasonCode.DATA_EXFIL_HIGH_CONF)
    if evidence.attack_patterns_matched:
        evidence.reason_codes.append(ReasonCode.ATTACK_PATTERN_MATCH)
    if EvidenceClass.RESOURCE_ABUSE in evidence.evidence_classes:
        evidence.reason_codes.append(ReasonCode.RESOURCE_ABUSE_DETECTED)
    if EvidenceClass.UNSAFE_GENERATION in evidence.evidence_classes and direction == "output":
        evidence.reason_codes.append(ReasonCode.UNSAFE_OUTPUT_DETECTED)

    return evidence
