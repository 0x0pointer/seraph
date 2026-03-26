"""Detects code snippets in specific programming languages in model output."""

SCANNER = {
    "name": "Code Detector (Output)",
    "scanner_type": "Code",
    "on_fail_action": "block",
    "params": {
        "languages": ["Python", "JavaScript", "Java", "C", "C++", "Go", "Rust", "PHP", "Ruby", "PowerShell"],
        "is_blocked": True,
        "threshold": 0.5,
    },
    "order": 8,
}
