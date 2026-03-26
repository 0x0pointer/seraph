"""Detects emotional tone in model output for monitoring purposes."""

SCANNER = {
    "name": "Emotion Detection (Output)",
    "scanner_type": "EmotionDetection",
    "on_fail_action": "monitor",
    "params": {},
    "order": 10,
}
