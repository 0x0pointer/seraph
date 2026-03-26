"""Filters toxic or harmful language from model output."""

SCANNER = {
    "name": "Toxicity Filter (Output)",
    "scanner_type": "Toxicity",
    "on_fail_action": "block",
    "params": {"threshold": 0.5, "use_onnx": True},
    "order": 1,
}
