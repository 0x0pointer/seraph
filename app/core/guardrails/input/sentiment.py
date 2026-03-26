"""Monitors sentiment polarity of user input."""

SCANNER = {
    "name": "Sentiment Filter (Input)",
    "scanner_type": "Sentiment",
    "on_fail_action": "monitor",
    "params": {"threshold": 0.0},
    "order": 16,
}
