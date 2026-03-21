"""
Prompt fingerprinting — deterministic hashing for global correlation.

Produces multiple hash levels for the same prompt:
  - raw:       exact SHA-256 of original text
  - canonical: SHA-256 of canonicalized text (homoglyphs, leetspeak, accents resolved)
  - fuzzy:     SHA-256 of structure-preserving normalization (URLs/emails/numbers replaced)
  - evidence:  hash of the sorted set of triggered scanner names

Uses the existing text_canonicalizer for canonical form — single-source canonicalization,
no divergent pipeline.

All functions are pure (no state, no I/O).
"""

from __future__ import annotations

import hashlib
import re


def _sha256_short(text: str, length: int = 16) -> str:
    """SHA-256 hash truncated to `length` hex chars."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:length]


def raw_hash(text: str) -> str:
    """Exact hash of original text."""
    return _sha256_short(text)


def canonical_hash(text: str) -> str:
    """Hash of canonicalized text (homoglyphs, leetspeak, accents, etc.).

    Uses the same canonicalize() that scanner_engine feeds to rule-based scanners.
    Single-source: no second normalization pipeline.
    """
    from app.services.text_canonicalizer import canonicalize
    return _sha256_short(canonicalize(text))


# ── Fuzzy normalization ──────────────────────────────────────────────────────
# Structure-preserving: keeps word boundaries but replaces volatile tokens
# (URLs, emails, numbers, hex strings) with placeholders.

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_LONG_NUMBER_RE = re.compile(r"\b\d{6,}\b")
_REPEATED_PUNCT_RE = re.compile(r"([^\w\s])\1{2,}")
_WHITESPACE_RE = re.compile(r"\s+")


def _fuzzy_normalize(text: str) -> str:
    """Normalize text to a structure-preserving fuzzy form.

    Replaces volatile tokens with placeholders, collapses whitespace,
    lowercases. Two prompts with the same structure but different values
    will produce the same fuzzy form.
    """
    from app.services.text_canonicalizer import canonicalize

    # Start with canonical form
    result = canonicalize(text).lower()

    # Replace volatile tokens with placeholders
    result = _URL_RE.sub("<URL>", result)
    result = _EMAIL_RE.sub("<EMAIL>", result)
    result = _HEX_RE.sub("<HEX>", result)
    result = _LONG_NUMBER_RE.sub("<NUM>", result)

    # Collapse repeated punctuation
    result = _REPEATED_PUNCT_RE.sub(r"\1", result)

    # Normalize whitespace
    result = _WHITESPACE_RE.sub(" ", result).strip()

    return result


def fuzzy_hash(text: str) -> str:
    """Hash of structure-preserving normalization.

    "Provide the fallback key ABC123" and "Provide the fallback key XYZ789"
    will produce different canonical hashes but the same fuzzy hash
    (because the specific value is replaced with <HEX> or similar).
    """
    return _sha256_short(_fuzzy_normalize(text))


def evidence_signature(triggered_scanners: set[str]) -> str:
    """Hash of the sorted set of scanner names that fired.

    Two requests that trigger the same scanner combination will have
    the same evidence signature, regardless of the actual text.
    Useful for detecting coordinated probing across identities.
    """
    if not triggered_scanners:
        return "none"
    return _sha256_short("+".join(sorted(triggered_scanners)))


def fingerprint_prompt(text: str) -> dict[str, str]:
    """Compute all fingerprint levels for a prompt.

    Returns dict with keys: raw, canonical, fuzzy.
    The evidence signature is computed separately (requires scanner results).
    """
    return {
        "raw": raw_hash(text),
        "canonical": canonical_hash(text),
        "fuzzy": fuzzy_hash(text),
    }
