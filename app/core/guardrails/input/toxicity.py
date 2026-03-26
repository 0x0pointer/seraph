"""Filters toxic or harmful language from user input."""

SCANNER = {
    "name": "Toxicity Filter",
    "scanner_type": "Toxicity",
    "on_fail_action": "block",
    "params": {"threshold": 0.5, "use_onnx": True},
    "order": 2,
}
