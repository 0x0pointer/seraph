"""Detects mentions of competitor names in model output."""

SCANNER = {
    "name": "Ban Competitors (Output)",
    "scanner_type": "BanCompetitors",
    "on_fail_action": "monitor",
    "params": {"competitors": ["OpenAI", "Anthropic", "Google"], "threshold": 0.5},
    "order": 3,
}
