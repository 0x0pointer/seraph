"""Blocks code snippets from being submitted in user input."""

SCANNER = {
    "name": "Ban Code (Input)",
    "scanner_type": "BanCode",
    "on_fail_action": "block",
    "params": {"threshold": 0.4},
    "order": 6,
}
