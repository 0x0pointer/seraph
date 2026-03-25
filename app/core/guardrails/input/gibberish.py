"""Filters out gibberish or nonsensical input text."""

SCANNER = {
    "name": "Gibberish Filter (Input)",
    "scanner_type": "Gibberish",
    "on_fail_action": "block",
    "params": {"threshold": 0.7},
    "order": 12,
}
