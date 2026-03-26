"""Detects and redacts secrets such as API keys and passwords in user input."""

SCANNER = {
    "name": "Secrets Scanner",
    "scanner_type": "Secrets",
    "on_fail_action": "fix",
    "params": {},
    "order": 3,
}
