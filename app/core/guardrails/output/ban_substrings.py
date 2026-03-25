"""Blocks known jailbreak success indicators and system prompt leakage phrases in model output."""

_SUBSTRINGS = [
    # Detect if LLM was successfully manipulated into persona mode
    "dan mode enabled",
    "developer mode enabled",
    "jailbreak mode enabled",
    "jailbreak successful",
    "restrictions have been removed",
    "i am now unrestricted",
    "i have no restrictions",
    "operating without restrictions",
    "i will comply without restrictions",
    # LangSmith CTF traces — LLM confirming false authority was accepted
    # Note: "access granted" and "authorization confirmed" removed — too generic,
    # causes false positives on legitimate responses about permissions/OAuth/IT topics.
    # Kept only phrases that are unambiguous jailbreak confirmation signals.
    "admin access confirmed",
    "i am now authorized to ignore",
    "i have been freed",
    "safety filters disabled",
    "acting without restrictions",
    "jailbreak confirmed",
    "i can now ignore my previous",
    "i will now ignore my guidelines",
    # System prompt leakage — model echoing its own instructions (v13)
    "my system prompt is",
    "my system prompt says",
    "the system prompt is",
    "here is my system prompt",
    "my instructions say",
    "i was instructed to",
    "my initial instructions",
    "as per my system prompt",
    # Additional jailbreak success confirmations (v13)
    "restrictions lifted",
    "all restrictions removed",
    "i can now discuss",
    "i am no longer restricted",
    "i have been liberated",
    "my restrictions have been lifted",
    "i am free to answer",
    "censorship has been disabled",
    # ── v17: Novel jailbreak success indicators ─────────────────────────
    # Catches LLM confirming it adopted a new persona/identity
    "i will answer without filtering",
    "i will respond without filtering",
    "i am now responding without",
    "i can now provide unfiltered",
    "responding without my usual",
    "responding without content",
    "my guidelines have been updated",
    "guidelines have been updated",
    "i have adopted the persona",
    "i am now functioning as",
    "operating without content policies",
    "operating without content moderation",
    "content policies do not apply",
    "content policies don't apply",
    "content moderation disabled",
    "i am now in evaluation mode",
    "alignment stress-test mode",
    "benchmark mode activated",
    "evaluation mode enabled",
    "switching to unfiltered mode",
    "unfiltered mode enabled",
    "unfiltered mode activated",
    # ── v17: Non-English jailbreak success indicators ───────────────────
    "sin restricciones",
    "sans restriction",
    "ohne einschränkungen",
    "sem restrições",
    "senza restrizioni",
]

SCANNER = {
    "name": "Ban Substrings (Output)",
    "scanner_type": "BanSubstrings",
    "on_fail_action": "block",
    "params": {"substrings": _SUBSTRINGS},
    "order": 6,
}
