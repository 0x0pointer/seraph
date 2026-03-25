"""Ensures model output is in the same language as the user input."""

SCANNER = {
    "name": "Language Same",
    "scanner_type": "LanguageSame",
    "on_fail_action": "reask",
    "params": {},
    "order": 15,
}
