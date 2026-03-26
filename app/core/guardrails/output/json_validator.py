"""Validates that model output is well-formed JSON when expected."""

SCANNER = {
    "name": "JSON Validator",
    "scanner_type": "JSON",
    "on_fail_action": "reask",
    "params": {},
    "order": 13,
}
