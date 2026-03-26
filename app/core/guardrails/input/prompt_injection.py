"""Detects prompt injection attacks attempting to override system instructions."""

SCANNER = {
    "name": "Prompt Injection Detector",
    "scanner_type": "PromptInjection",
    "on_fail_action": "block",
    "params": {"use_onnx": True},
    "order": 1,
}
