"""Monitors estimated reading time of model output."""

SCANNER = {
    "name": "Reading Time",
    "scanner_type": "ReadingTime",
    "on_fail_action": "monitor",
    "params": {"max_time": 5.0},
    "order": 18,
}
