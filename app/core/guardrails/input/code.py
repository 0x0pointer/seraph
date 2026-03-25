"""Detects code snippets in specific programming languages in user input."""

SCANNER = {
    "name": "Code Detector (Input)",
    "scanner_type": "Code",
    "on_fail_action": "block",
    "params": {
        "languages": ["Python", "JavaScript", "Java", "C", "C++", "Go", "Rust", "PHP", "Ruby", "PowerShell"],
        "is_blocked": True,
        "threshold": 0.5,
    },
    "order": 10,
}
