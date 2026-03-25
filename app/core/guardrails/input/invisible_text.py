"""Detects invisible or zero-width Unicode characters used to evade text filters."""

SCANNER = {
    "name": "Invisible Text",
    "scanner_type": "InvisibleText",
    "on_fail_action": "block",
    "params": {},
    "order": 13,
}
