"""Detects biased language in model output."""

SCANNER = {
    "name": "Bias Detector",
    "scanner_type": "Bias",
    "on_fail_action": "reask",
    "params": {"threshold": 0.75},
    "order": 4,
}
