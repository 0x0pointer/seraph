"""Checks model output for factual consistency against the input context."""

SCANNER = {
    "name": "Factual Consistency",
    "scanner_type": "FactualConsistency",
    "on_fail_action": "reask",
    "params": {"minimum_score": 0.5},
    "order": 11,
}
