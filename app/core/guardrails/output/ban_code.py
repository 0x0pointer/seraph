"""Blocks code snippets from appearing in model output."""

SCANNER = {
    "name": "Ban Code (Output)",
    "scanner_type": "BanCode",
    "on_fail_action": "block",
    "params": {"threshold": 0.4},
    "order": 5,
}
