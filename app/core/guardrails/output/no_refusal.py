"""Detects when the model refuses to answer and triggers a reask."""

SCANNER = {
    "name": "No Refusal",
    "scanner_type": "NoRefusal",
    "on_fail_action": "reask",
    "params": {},
    "order": 2,
}
