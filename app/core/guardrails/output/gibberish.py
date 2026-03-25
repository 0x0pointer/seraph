"""Filters out gibberish or nonsensical text from model output."""

SCANNER = {
    "name": "Gibberish Filter (Output)",
    "scanner_type": "Gibberish",
    "on_fail_action": "block",
    "params": {"threshold": 0.7},
    "order": 12,
}
