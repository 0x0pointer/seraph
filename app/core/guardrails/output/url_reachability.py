"""Checks that URLs in model output are reachable and not broken."""

SCANNER = {
    "name": "URL Reachability",
    "scanner_type": "URLReachability",
    "on_fail_action": "monitor",
    "params": {},
    "order": 23,
}
