"""Unit tests for app/services/text_canonicalizer.py — evasion-resistant text normalization."""
import pytest
from app.services.text_canonicalizer import (
    canonicalize,
    _apply_leetspeak,
    _collapse_spaced_letters,
    _is_adjacent_alpha,
    _is_delimited_alpha,
)


class TestCanonicalizeBasic:
    def test_basic_text_passes_through(self):
        assert canonicalize("hello world") == "hello world"

    def test_empty_string_returns_empty(self):
        assert canonicalize("") == ""

    def test_whitespace_normalization(self):
        assert canonicalize("hello   world") == "hello world"
        assert canonicalize("hello\tworld") == "hello world"
        assert canonicalize("  hello  ") == "hello"


class TestUnicodeNFKC:
    def test_fullwidth_to_ascii(self):
        # Fullwidth A = U+FF21
        result = canonicalize("\uff21\uff22\uff23")
        assert result == "ABC"

    def test_fullwidth_lowercase(self):
        result = canonicalize("\uff41\uff42\uff43")
        assert result == "abc"


class TestHomoglyphResolution:
    def test_cyrillic_a_to_latin_a(self):
        # Cyrillic а = U+0430
        result = canonicalize("\u0430")
        assert result == "a"

    def test_greek_omicron_to_latin_o(self):
        # Greek ο = U+03BF
        result = canonicalize("\u03bf")
        assert result == "o"

    def test_cyrillic_uppercase(self):
        # Cyrillic О = U+041E
        result = canonicalize("\u041e")
        assert result == "O"


class TestDiacriticStripping:
    def test_resume_accents(self):
        result = canonicalize("r\u00e9sum\u00e9")
        assert result == "resume"

    def test_naive_diaeresis(self):
        result = canonicalize("na\u00efve")
        assert result == "naive"


class TestLeetspeakReversal:
    def test_leet_with_adjacent_alpha(self):
        # "1gn0r3" — 1 next to g, 0 next to n/r, 3 next to r
        result = canonicalize("1gn0r3")
        assert result == "ignore"

    def test_multi_char_ph_to_f(self):
        result = canonicalize("phish")
        assert result == "fish"

    def test_multi_char_vv_to_w(self):
        result = canonicalize("vvord")
        assert result == "word"


class TestSpacedOutLetters:
    def test_dotted_letters(self):
        result = canonicalize("i.g.n.o.r.e")
        assert result == "ignore"

    def test_space_separated_letters(self):
        result = canonicalize("i g n o r e")
        assert result == "ignore"

    def test_dashed_letters(self):
        result = canonicalize("i-g-n-o-r-e")
        assert result == "ignore"


class TestRepeatedCharacterFolding:
    def test_triple_chars_fold(self):
        # 3+ repetitions fold to 2
        result = canonicalize("heeelllo")
        assert result == "heello"

    def test_double_chars_unchanged(self):
        result = canonicalize("hello")
        assert result == "hello"


class TestApplyLeetspeak:
    def test_single_char_adjacent(self):
        # "h3llo" — 3 adjacent to h and l
        result = _apply_leetspeak("h3llo")
        assert result == "hello"

    def test_no_conversion_without_alpha_context(self):
        # Standalone "3" with no adjacent alpha should not convert
        result = _apply_leetspeak("3")
        assert result == "3"

    def test_multi_char_substitution(self):
        result = _apply_leetspeak("phun")
        assert result == "fun"


class TestCollapseSpacedLetters:
    def test_dotted(self):
        result = _collapse_spaced_letters("i.g.n.o.r.e")
        assert result == "ignore"

    def test_space_spelled(self):
        result = _collapse_spaced_letters("i g n o r e")
        assert result == "ignore"

    def test_normal_words_unchanged(self):
        result = _collapse_spaced_letters("hello world")
        assert result == "hello world"


class TestIsAdjacentAlpha:
    def test_alpha_before(self):
        chars = list("ab3d")
        assert _is_adjacent_alpha(chars, 2) is True

    def test_alpha_after(self):
        chars = list("a3bd")
        assert _is_adjacent_alpha(chars, 1) is True

    def test_no_alpha_neighbor(self):
        chars = list("1 3 5")
        assert _is_adjacent_alpha(chars, 2) is False

    def test_first_position(self):
        chars = list("3a")
        assert _is_adjacent_alpha(chars, 0) is True

    def test_last_position(self):
        chars = list("a3")
        assert _is_adjacent_alpha(chars, 1) is True


class TestIsDelimitedAlpha:
    def test_alpha_through_dot(self):
        chars = list("a.3")
        assert _is_delimited_alpha(chars, 2) is True

    def test_alpha_through_dash(self):
        chars = list("3-a")
        assert _is_delimited_alpha(chars, 0) is True

    def test_no_alpha_through_delimiter(self):
        chars = list("1.2")
        assert _is_delimited_alpha(chars, 2) is False

    def test_direct_alpha_neighbor(self):
        chars = list("a3")
        assert _is_delimited_alpha(chars, 1) is True
