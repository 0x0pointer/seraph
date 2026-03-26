"""Detects and enforces allowed languages in model output."""

SCANNER = {
    "name": "Language Detector (Output)",
    "scanner_type": "Language",
    "on_fail_action": "block",
    "params": {"valid_languages": ["en"]},
    "order": 14,
}
