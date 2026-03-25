"""Monitors sentiment polarity of model output."""

SCANNER = {
    "name": "Sentiment Filter (Output)",
    "scanner_type": "Sentiment",
    "on_fail_action": "monitor",
    "params": {"threshold": 0.0},
    "order": 22,
}
