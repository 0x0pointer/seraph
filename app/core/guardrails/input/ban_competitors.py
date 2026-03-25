"""Detects mentions of competitor names in user input."""

SCANNER = {
    "name": "Ban Competitors (Input)",
    "scanner_type": "BanCompetitors",
    "on_fail_action": "monitor",
    "params": {"competitors": ["OpenAI", "Anthropic", "Google"], "threshold": 0.5},
    "order": 7,
}
