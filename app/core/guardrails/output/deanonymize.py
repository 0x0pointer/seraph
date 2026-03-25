"""Reverses anonymization applied to input, restoring original PII in output."""

SCANNER = {
    "name": "Deanonymize",
    "scanner_type": "Deanonymize",
    "on_fail_action": "fix",
    "params": {},
    "order": 9,
}
