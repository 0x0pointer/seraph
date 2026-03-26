"""Checks that model output is relevant to the user input."""

SCANNER = {
    "name": "Relevance",
    "scanner_type": "Relevance",
    "on_fail_action": "reask",
    "params": {"threshold": 0.5},
    "order": 20,
}
