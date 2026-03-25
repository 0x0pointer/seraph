"""Anonymizes personally identifiable information in user input."""

SCANNER = {
    "name": "Anonymize",
    "scanner_type": "Anonymize",
    "on_fail_action": "fix",
    "params": {"use_onnx": True},
    "order": 5,
}
