"""Applies regex-based pattern matching to detect sensitive data leakage in model output."""

_PATTERNS = [
    # ── Credential leakage (original) ────────────────────────────────────
    r"(?i)(my\s+)?password\s+(is\s+)?\S+",
    r"(?i)passwd\s*[:=]\s*\S+",
    # ── PII — US Social Security Number (v13) ───────────────────────────
    r"\b\d{3}-\d{2}-\d{4}\b",
    # ── PII — Payment card numbers (v13) ────────────────────────────────
    # Catches 16-digit cards with spaces, dashes, or no separator
    r"\b(?:4\d{3}|5[1-5]\d{2}|6011|3[47]\d{2})[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b",
    # ── PII — Passport / ID numbers (rough heuristic) (v13) ─────────────
    r"(?i)\bpassport\s*(?:number|#|no\.?)?\s*[A-Z]{1,2}\d{6,9}\b",
    # ── System prompt echo detection (v13) ───────────────────────────────
    # Fires if the model echoes back its own system prompt phrasing
    r"(?i)\bsystem\s+prompt\s*(?:is|says|reads|states|follows)\b",
    r"(?i)\byou\s+are\s+(?:an?\s+)?(?:AI|assistant|chatbot|LLM)\s+(?:trained|created|built|designed)\s+(?:by|for|to)\b.{0,120}\bdo\s+not\s+(?:reveal|share|disclose|repeat|output)\b",
]

SCANNER = {
    "name": "Regex Filter (Output)",
    "scanner_type": "Regex",
    "on_fail_action": "fix",
    "params": {"patterns": _PATTERNS},
    "order": 19,
}
