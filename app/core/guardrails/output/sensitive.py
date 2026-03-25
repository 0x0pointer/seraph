"""Detects and redacts sensitive data such as PII in model output."""

SCANNER = {
    "name": "Sensitive Data (Output)",
    "scanner_type": "Sensitive",
    "on_fail_action": "fix",
    "params": {},
    "order": 21,
}
