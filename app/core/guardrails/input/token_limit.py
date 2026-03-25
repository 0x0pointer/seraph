"""Enforces a maximum token count on user input to prevent abuse."""

SCANNER = {
    "name": "Token Limit",
    "scanner_type": "TokenLimit",
    "on_fail_action": "block",
    "params": {"limit": 4096},
    "order": 4,
}
