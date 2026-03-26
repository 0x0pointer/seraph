"""Detects malicious or phishing URLs in model output."""

SCANNER = {
    "name": "Malicious URLs",
    "scanner_type": "MaliciousURLs",
    "on_fail_action": "block",
    "params": {},
    "order": 16,
}
