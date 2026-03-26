"""Detects and enforces allowed languages in user input."""

SCANNER = {
    "name": "Language Detector (Input)",
    "scanner_type": "Language",
    "on_fail_action": "monitor",
    "params": {"valid_languages": ["en"]},
    "order": 14,
}
