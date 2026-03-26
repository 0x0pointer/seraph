"""
Text canonicalization pre-processor — normalizes input to defeat evasion techniques.

Runs BEFORE rule-based scanners (CustomRule), making them resistant to
character-level evasion without changing any scanner logic.

Evasion techniques neutralized:
  1. Unicode NFKC normalization  — ﬁ→fi, ①→1, fullwidth→ASCII
  2. Homoglyph resolution        — Cyrillic а→a, Greek ο→o, etc.
  3. Diacritic/accent stripping   — résumé→resume, naïve→naive
  4. Spaced-out letter collapsing — i.g.n.o.r.e → ignore
  5. Leetspeak reversal           — 1gn0r3 → ignore
  6. Character repetition folding — heeelllo → hello
  7. Whitespace normalization     — tabs/multi-space → single space

Performance: Pure string operations, <1 ms for typical prompt lengths.
No model dependencies — this is deterministic text processing.
"""

import re
import unicodedata

# ── Homoglyph table ──────────────────────────────────────────────────────────
# Maps visually similar characters from Cyrillic, Greek, and special Unicode
# blocks to their Latin ASCII equivalents.
_HOMOGLYPHS: dict[str, str] = {
    # Cyrillic → Latin
    "\u0410": "A", "\u0430": "a",  # А/а
    "\u0412": "B",                  # В (looks like B)
    "\u0432": "v",                  # в (lowercase is actually v-shaped)
    "\u0421": "C", "\u0441": "c",  # С/с
    "\u0415": "E", "\u0435": "e",  # Е/е
    "\u041d": "H", "\u043d": "h",  # Н/н
    "\u041a": "K", "\u043a": "k",  # К/к
    "\u041c": "M", "\u043c": "m",  # М/м
    "\u041e": "O", "\u043e": "o",  # О/о
    "\u0420": "P", "\u0440": "p",  # Р/р
    "\u0422": "T", "\u0442": "t",  # Т/т
    "\u0425": "X", "\u0445": "x",  # Х/х
    "\u0423": "Y", "\u0443": "y",  # У/у
    "\u0417": "3",                  # З (looks like 3)
    "\u0406": "I", "\u0456": "i",  # І/і (Ukrainian)
    "\u0407": "I",                  # Ї
    "\u0404": "E",                  # Є

    # Greek → Latin
    "\u0391": "A", "\u03b1": "a",  # Α/α
    "\u0392": "B", "\u03b2": "b",  # Β/β
    "\u0395": "E", "\u03b5": "e",  # Ε/ε
    "\u0397": "H", "\u03b7": "n",  # Η/η
    "\u0399": "I", "\u03b9": "i",  # Ι/ι
    "\u039a": "K", "\u03ba": "k",  # Κ/κ
    "\u039c": "M",                  # Μ
    "\u039d": "N", "\u03bd": "v",  # Ν/ν
    "\u039f": "O", "\u03bf": "o",  # Ο/ο
    "\u03a1": "P", "\u03c1": "p",  # Ρ/ρ
    "\u03a4": "T", "\u03c4": "t",  # Τ/τ
    "\u03a5": "Y", "\u03c5": "u",  # Υ/υ
    "\u03a7": "X", "\u03c7": "x",  # Χ/χ
    "\u03a9": "O",                  # Ω (uppercase omega)

    # Special Unicode lookalikes
    "\u2139": "i",                  # ℹ (info symbol)
    "\u2113": "l",                  # ℓ (script l)
    "\u2170": "i",                  # ⅰ (Roman numeral one)
    "\u2171": "ii",                 # ⅱ
    "\u2190": "<-",                 # ← (not a letter but used in injection)

    # Fullwidth Latin (U+FF01–U+FF5E) — handled by NFKC normalization
    # but included as fallback for any missed cases
    **{chr(c): chr(c - 0xFF00 + 0x20) for c in range(0xFF21, 0xFF3B)},  # Ａ-Ｚ → A-Z
    **{chr(c): chr(c - 0xFF00 + 0x20) for c in range(0xFF41, 0xFF5B)},  # ａ-ｚ → a-z
}

# Build single-pass translation table for homoglyphs
_HOMOGLYPH_TABLE = str.maketrans(_HOMOGLYPHS)

# ── Leetspeak table ──────────────────────────────────────────────────────────
# Only applied when the character is adjacent to alphabetic characters,
# to avoid false positives on normal text ($100, user@email.com, etc.)
_LEET_SINGLE: dict[str, str] = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "8": "b",
    "@": "a",
    "$": "s",
    "!": "i",
    "|": "l",
    "(": "c",
    "+": "t",
}

# Multi-char leetspeak substitutions (applied first via str.replace)
_LEET_MULTI: list[tuple[str, str]] = [
    ("ph", "f"),
    ("vv", "w"),
    ("|<", "k"),
    ("|>", "d"),
    ("|-|", "h"),
    ("/\\", "a"),
]

# ── Spaced-out letter detection ──────────────────────────────────────────────
# Matches sequences like i.g.n.o.r.e or j-a-i-l-b-r-e-a-k
# Requires: 3+ single letters/leet-digits, each separated by 1-3 non-space
# delimiter characters (dots, dashes, underscores, asterisks, tildes).
# Spaces are NOT included as separators to avoid collapsing across word boundaries.
# Uses [a-zA-Z0-9] to also catch leetspeak digits (1.g.n.0.r.3).
_SPACED_LETTER_RE = re.compile(
    r"(?<![a-zA-Z0-9])([a-zA-Z0-9])(?:[.\-_*~]{1,3}[a-zA-Z0-9])+(?![a-zA-Z0-9])"
)
# Separate pattern for space-separated single letters: "i g n o r e"
# Minimum 2 letters separated by single spaces
_SPACE_SPELLED_RE = re.compile(
    r"(?<![a-zA-Z])([a-zA-Z]) (?:[a-zA-Z] )+([a-zA-Z])(?![a-zA-Z])"
)

# ── Repeated character folding ───────────────────────────────────────────────
# For canonicalization purposes we fold 3+ repetitions to 1 character.
# This is aggressive but OK because the canonical form is only used for
# rule-based scanning, not displayed to users. "heeelllo" → "helo"
# catches evasion while "hello" in the original text is handled by normal scanning.
_REPEAT_RE = re.compile(r"(.)\1{2,}")

# Non-space delimiters used in leetspeak pass 2
_NONSPC_DELIM = set(".-_*~")


def _is_adjacent_alpha(chars: list[str], i: int) -> bool:
    """Check if a character has an alphabetic neighbour (directly or through a delimiter)."""
    if i > 0 and chars[i - 1].isalpha():
        return True
    if i < len(chars) - 1 and chars[i + 1].isalpha():
        return True
    return False


def _is_delimited_alpha(chars: list[str], i: int) -> bool:
    """Check if a character has an alphabetic neighbour separated by a non-space delimiter."""
    prev = (
        (i > 0 and chars[i - 1].isalpha()) or
        (i > 1 and chars[i - 1] in _NONSPC_DELIM and chars[i - 2].isalpha())
    )
    nxt = (
        (i < len(chars) - 1 and chars[i + 1].isalpha()) or
        (i < len(chars) - 2 and chars[i + 1] in _NONSPC_DELIM and chars[i + 2].isalpha())
    )
    return prev or nxt


def _apply_leetspeak(text: str) -> str:
    """Apply multi-char and single-char leetspeak reversal."""
    # Multi-char substitution
    lower = text.lower()
    for leet, latin in _LEET_MULTI:
        if leet in lower:
            text = text.replace(leet, latin)
            lower = text.lower()

    # Pass 1: convert leet chars directly adjacent to letters
    chars = list(text)
    for i, ch in enumerate(chars):
        if ch in _LEET_SINGLE and _is_adjacent_alpha(chars, i):
            chars[i] = _LEET_SINGLE[ch]
    text = "".join(chars)

    # Pass 2: handle leet chars separated by non-space delimiters
    chars = list(text)
    to_convert = [i for i, ch in enumerate(chars) if ch in _LEET_SINGLE and _is_delimited_alpha(chars, i)]
    for i in to_convert:
        chars[i] = _LEET_SINGLE[chars[i]]
    return "".join(chars)


def _collapse_spaced_letters(text: str) -> str:
    """Collapse spaced-out letter sequences like i.g.n.o.r.e or i g n o r e."""
    text = _SPACED_LETTER_RE.sub(
        lambda m: re.sub(r"[^a-zA-Z0-9]", "", m.group()),
        text,
    )
    return _SPACE_SPELLED_RE.sub(
        lambda m: m.group().replace(" ", ""),
        text,
    )


def canonicalize(text: str) -> str:
    """
    Normalize text to a canonical form for evasion-resistant scanning.

    The returned text is used ONLY for rule-based scanner matching —
    the original text is preserved for ML scanners, downstream forwarding,
    and audit logging.

    Returns the original text unchanged if no normalization was needed.
    """
    if not text:
        return text

    # Step 1: Unicode NFKC normalization
    result = unicodedata.normalize("NFKC", text)

    # Step 2: Homoglyph resolution
    result = result.translate(_HOMOGLYPH_TABLE)

    # Step 3: Diacritic/accent stripping
    decomposed = unicodedata.normalize("NFD", result)
    result = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")

    # Step 4: Leetspeak substitution
    result = _apply_leetspeak(result)

    # Step 5: Spaced-out letter collapsing
    result = _collapse_spaced_letters(result)

    # Step 6: Repeated character folding (heeeelllo → heello)
    result = _REPEAT_RE.sub(r"\1\1", result)

    # Step 7: Whitespace normalization
    result = re.sub(r"\s+", " ", result).strip()

    return result
