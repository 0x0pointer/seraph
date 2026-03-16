"""Unit tests for helper functions in app/services/scanner_engine."""
import pytest
from unittest.mock import patch, MagicMock
from app.services.scanner_engine import (
    _find_action_for_scanner,
    _handle_violation_action,
    _process_violations,
    _collect_raw_results,
    _load_and_filter_entries,
    _result_cache_key,
    _result_cache_get,
    _result_cache_put,
    invalidate_cache,
    _result_cache,
    _build_reask_message,
    _build_scanner,
    _apply_custom_phrases,
    _normalize_languages,
    _apply_threshold_overrides,
)


def _make_entry(scanner_name: str, guardrail_id: int = 1, on_fail_action: str = "block"):
    """Build a fake scanner entry tuple: (scanner, name, phrases, id, params, action)."""
    return (None, scanner_name, [], guardrail_id, {}, on_fail_action)


class TestFindActionForScanner:
    def test_finds_correct_action(self):
        entries = [
            _make_entry("BanSubstrings", on_fail_action="monitor"),
            _make_entry("Regex", on_fail_action="fix"),
        ]
        assert _find_action_for_scanner(entries, "BanSubstrings") == "monitor"
        assert _find_action_for_scanner(entries, "Regex") == "fix"

    def test_returns_block_for_unknown(self):
        entries = [_make_entry("BanSubstrings")]
        assert _find_action_for_scanner(entries, "NonExistent") == "block"


class TestHandleViolationAction:
    def test_monitor(self):
        should_block, fixed, label, reask = _handle_violation_action(
            "monitor", "TestScanner", 0.9, "orig", {}
        )
        assert should_block is False
        assert fixed is None
        assert label == "monitored"
        assert reask is None

    def test_fix_with_sanitized_text(self):
        scanner_sanitized = {"TestScanner": ("sanitized text", "fix")}
        should_block, fixed, label, reask = _handle_violation_action(
            "fix", "TestScanner", 0.8, "orig", scanner_sanitized
        )
        assert should_block is False
        assert fixed == "sanitized text"
        assert label == "fixed"

    def test_fix_without_sanitized_text_falls_to_block(self):
        should_block, fixed, label, reask = _handle_violation_action(
            "fix", "TestScanner", 0.8, "orig", {}
        )
        assert should_block is True
        assert fixed is None
        assert label == "blocked"

    def test_fix_same_text_falls_to_block(self):
        scanner_sanitized = {"TestScanner": ("orig", "fix")}
        should_block, fixed, label, reask = _handle_violation_action(
            "fix", "TestScanner", 0.8, "orig", scanner_sanitized
        )
        assert should_block is True
        assert label == "blocked"

    def test_reask(self):
        should_block, fixed, label, reask = _handle_violation_action(
            "reask", "TestScanner", 0.85, "orig", {}
        )
        assert should_block is True
        assert fixed is None
        assert label == "reask"
        assert reask is not None
        assert "TestScanner" in reask
        assert "85%" in reask

    def test_block_default(self):
        should_block, fixed, label, reask = _handle_violation_action(
            "block", "TestScanner", 0.9, "orig", {}
        )
        assert should_block is True
        assert label == "blocked"
        assert reask is None


class TestProcessViolations:
    def test_all_valid(self):
        results_valid = {"Scanner1": True, "Scanner2": True}
        results_score = {"Scanner1": 0.1, "Scanner2": 0.2}
        entries = [_make_entry("Scanner1"), _make_entry("Scanner2")]

        overall, text, violations, actions, reask, fix = _process_violations(
            results_valid, results_score, entries, {}, "orig"
        )
        assert overall is True
        assert text == "orig"
        assert violations == []
        assert fix is False

    def test_mixed_violations(self):
        results_valid = {"Scanner1": True, "Scanner2": False}
        results_score = {"Scanner1": 0.1, "Scanner2": 0.9}
        entries = [
            _make_entry("Scanner1", on_fail_action="block"),
            _make_entry("Scanner2", on_fail_action="block"),
        ]

        overall, text, violations, actions, reask, fix = _process_violations(
            results_valid, results_score, entries, {}, "orig"
        )
        assert overall is False
        assert "Scanner2" in violations
        assert "Scanner1" not in violations
        assert actions["Scanner2"] == "blocked"

    def test_monitor_violation_keeps_valid(self):
        results_valid = {"Scanner1": False}
        results_score = {"Scanner1": 0.9}
        entries = [_make_entry("Scanner1", on_fail_action="monitor")]

        overall, text, violations, actions, reask, fix = _process_violations(
            results_valid, results_score, entries, {}, "orig"
        )
        assert overall is True
        assert violations == []
        assert actions["Scanner1"] == "monitored"

    def test_fix_violation(self):
        results_valid = {"Scanner1": False}
        results_score = {"Scanner1": 0.8}
        entries = [_make_entry("Scanner1", on_fail_action="fix")]
        scanner_sanitized = {"Scanner1": ("fixed text", "fix")}

        overall, text, violations, actions, reask, fix = _process_violations(
            results_valid, results_score, entries, scanner_sanitized, "orig"
        )
        assert overall is True
        assert text == "fixed text"
        assert fix is True
        assert actions["Scanner1"] == "fixed"


class TestCollectRawResults:
    def test_normal_results(self):
        entries = [
            _make_entry("Scanner1", guardrail_id=1, on_fail_action="block"),
            _make_entry("Scanner2", guardrail_id=2, on_fail_action="monitor"),
        ]
        raw = [
            ("sanitized1", {"Scanner1": True}, {"Scanner1": 0.1}),
            ("sanitized2", {"Scanner2": False}, {"Scanner2": 0.9}),
        ]
        valid, score, sanitized = _collect_raw_results(raw, entries)
        assert valid == {"Scanner1": True, "Scanner2": False}
        assert score == {"Scanner1": 0.1, "Scanner2": 0.9}
        # Scanner2 had a violation so it should be in sanitized
        assert "Scanner2" in sanitized
        assert sanitized["Scanner2"] == ("sanitized2", "monitor")

    def test_exception_skipped(self):
        entries = [
            _make_entry("Scanner1"),
            _make_entry("Scanner2"),
        ]
        raw = [
            RuntimeError("model load failed"),
            ("sanitized2", {"Scanner2": True}, {"Scanner2": 0.1}),
        ]
        valid, score, sanitized = _collect_raw_results(raw, entries)
        assert "Scanner1" not in valid
        assert valid == {"Scanner2": True}


class TestLoadAndFilterEntries:
    def test_no_filter(self):
        entries = [_make_entry("A"), _make_entry("B")]
        assert _load_and_filter_entries(entries, None) == entries

    def test_with_filter(self):
        entries = [_make_entry("A"), _make_entry("B"), _make_entry("C")]
        filtered = _load_and_filter_entries(entries, {"A", "C"})
        assert len(filtered) == 2
        assert filtered[0][1] == "A"
        assert filtered[1][1] == "C"


class TestResultCache:
    def setup_method(self):
        invalidate_cache()

    def test_cache_key_deterministic(self):
        entries = [_make_entry("S1", guardrail_id=1, on_fail_action="block")]
        k1 = _result_cache_key("input", entries, "hello")
        k2 = _result_cache_key("input", entries, "hello")
        assert k1 == k2

    def test_cache_key_differs_for_different_text(self):
        entries = [_make_entry("S1", guardrail_id=1)]
        k1 = _result_cache_key("input", entries, "hello")
        k2 = _result_cache_key("input", entries, "world")
        assert k1 != k2

    def test_cache_get_miss(self):
        assert _result_cache_get("nonexistent") is None

    def test_cache_put_and_get(self):
        _result_cache_put("testkey", ("value1",))
        assert _result_cache_get("testkey") == ("value1",)

    def test_invalidate_clears_all(self):
        _result_cache_put("k1", "v1")
        invalidate_cache()
        assert _result_cache_get("k1") is None

    def test_cache_eviction(self):
        """Inserting beyond _RESULT_CACHE_SIZE evicts the oldest entry."""
        from app.services.scanner_engine import _RESULT_CACHE_SIZE
        invalidate_cache()
        for i in range(_RESULT_CACHE_SIZE + 1):
            _result_cache_put(f"key_{i}", f"val_{i}")
        # The first key should have been evicted
        assert _result_cache_get("key_0") is None
        # The last key should still exist
        assert _result_cache_get(f"key_{_RESULT_CACHE_SIZE}") == f"val_{_RESULT_CACHE_SIZE}"


class TestBuildReaskMessage:
    def test_returns_formatted_string_with_name_and_score(self):
        msg = _build_reask_message("Toxicity", 0.92)
        assert "Toxicity" in msg
        assert "92%" in msg

    def test_returns_formatted_string_zero_score(self):
        msg = _build_reask_message("BanSubstrings", 0.0)
        assert "BanSubstrings" in msg
        assert "0%" in msg

    def test_returns_formatted_string_full_score(self):
        msg = _build_reask_message("Regex", 1.0)
        assert "Regex" in msg
        assert "100%" in msg


class TestBuildScanner:
    @patch("app.services.scanner_engine._import_custom_scanner")
    def test_custom_rule_routes_to_custom_scanner(self, mock_custom):
        mock_custom.return_value = MagicMock()
        result = _build_scanner("CustomRule", "input", {"some_param": "val"})
        mock_custom.assert_called_once_with("input", {"some_param": "val"})
        assert result == mock_custom.return_value

    @patch("app.services.scanner_engine._import_embedding_shield")
    def test_embedding_shield_routes_correctly(self, mock_embed):
        mock_embed.return_value = MagicMock()
        result = _build_scanner("EmbeddingShield", "input", {"threshold": 0.5})
        mock_embed.assert_called_once_with({"threshold": 0.5})
        assert result == mock_embed.return_value

    @patch("app.services.scanner_engine._import_scanner")
    def test_regular_scanner_calls_import_scanner(self, mock_import):
        mock_import.return_value = MagicMock()
        result = _build_scanner("Toxicity", "input", {"threshold": 0.7})
        mock_import.assert_called_once_with("Toxicity", "input", {"threshold": 0.7})
        assert result == mock_import.return_value


class TestApplyCustomPhrases:
    def test_no_matching_phrases_returns_false(self):
        entries = [(None, "Scanner1", ["forbidden"], 1, {}, "block")]
        results_score = {}
        violation_scanners = []
        result = _apply_custom_phrases("this is fine", entries, results_score, violation_scanners)
        assert result is False
        assert results_score == {}
        assert violation_scanners == []

    def test_matching_phrase_returns_true_and_updates(self):
        entries = [(None, "Scanner1", ["bad word"], 1, {}, "block")]
        results_score = {}
        violation_scanners = []
        result = _apply_custom_phrases("this contains bad word here", entries, results_score, violation_scanners)
        assert result is True
        assert "Scanner1 (keyword)" in results_score
        assert results_score["Scanner1 (keyword)"] == 1.0
        assert "Scanner1 (keyword)" in violation_scanners

    def test_case_insensitive_matching(self):
        entries = [(None, "Scanner1", ["BLOCKED"], 1, {}, "block")]
        results_score = {}
        violation_scanners = []
        result = _apply_custom_phrases("this is blocked text", entries, results_score, violation_scanners)
        assert result is True
        assert "Scanner1 (keyword)" in results_score

    def test_no_custom_phrases_returns_false(self):
        entries = [(None, "Scanner1", [], 1, {}, "block")]
        results_score = {}
        violation_scanners = []
        result = _apply_custom_phrases("anything", entries, results_score, violation_scanners)
        assert result is False


class TestNormalizeLanguages:
    def test_normalizes_lowercase(self):
        assert _normalize_languages(["javascript"]) == ["JavaScript"]

    def test_alias_js(self):
        assert _normalize_languages(["js"]) == ["JavaScript"]

    def test_alias_cpp(self):
        assert _normalize_languages(["cpp"]) == ["C++"]

    def test_unknown_language_passes_through(self):
        assert _normalize_languages(["Brainfuck"]) == ["Brainfuck"]

    def test_deduplication(self):
        result = _normalize_languages(["js", "javascript", "JavaScript"])
        assert result == ["JavaScript"]

    def test_empty_strings_skipped(self):
        result = _normalize_languages(["", "Python", ""])
        assert result == ["Python"]


class TestApplyThresholdOverrides:
    @patch("app.services.scanner_engine._import_scanner")
    def test_no_matching_overrides_returns_unchanged(self, mock_import):
        entries = [
            (MagicMock(), "Toxicity", [], 1, {"threshold": 0.5}, "block"),
            (MagicMock(), "Regex", [], 2, {"threshold": 0.7}, "monitor"),
        ]
        result = _apply_threshold_overrides(entries, {99: 0.3}, "input")
        mock_import.assert_not_called()
        assert len(result) == 2
        assert result[0] is entries[0]
        assert result[1] is entries[1]

    @patch("app.services.scanner_engine._import_scanner")
    def test_matching_override_reinstantiates_scanner(self, mock_import):
        new_scanner = MagicMock()
        mock_import.return_value = new_scanner
        original_scanner = MagicMock()
        entries = [
            (original_scanner, "Toxicity", ["phrase"], 1, {"threshold": 0.5}, "block"),
        ]
        result = _apply_threshold_overrides(entries, {1: 0.9}, "input")
        mock_import.assert_called_once_with("Toxicity", "input", {"threshold": 0.9})
        assert result[0][0] is new_scanner
        # Other tuple fields preserved
        assert result[0][1] == "Toxicity"
        assert result[0][2] == ["phrase"]
        assert result[0][3] == 1
        assert result[0][5] == "block"

    @patch("app.services.scanner_engine._import_scanner")
    def test_failed_override_falls_back_to_original(self, mock_import):
        mock_import.side_effect = RuntimeError("import failed")
        original_scanner = MagicMock()
        entries = [
            (original_scanner, "Toxicity", [], 1, {"threshold": 0.5}, "block"),
        ]
        result = _apply_threshold_overrides(entries, {1: 0.9}, "input")
        assert result[0][0] is original_scanner
        assert result[0] is entries[0]


# ── BanCode routing tests ────────────────────────────────────────────────────

class TestBuildScannerBanCode:
    """Cover _build_scanner BanCode branches."""

    @patch("app.services.scanner_engine._import_scanner")
    def test_bancode_with_languages_routes_to_code_scanner(self, mock_import):
        """BanCode + languages → delegates to Code scanner with normalized languages."""
        mock_import.return_value = MagicMock()
        result = _build_scanner("BanCode", "output", {"languages": ["python", "javascript"]})
        mock_import.assert_called_once()
        call_args = mock_import.call_args
        assert call_args[0][0] == "Code"  # scanner_type
        assert call_args[0][1] == "output"  # direction
        params = call_args[0][2]
        assert "Python" in params["languages"]
        assert "JavaScript" in params["languages"]
        assert params["is_blocked"] is True

    @patch("app.services.scanner_engine._import_scanner")
    def test_bancode_with_invalid_languages_falls_back(self, mock_import):
        """BanCode + all-invalid languages → falls back to BanCode (block all)."""
        mock_import.return_value = MagicMock()
        # Empty strings normalize to nothing
        result = _build_scanner("BanCode", "output", {"languages": ["", ""]})
        mock_import.assert_called_once()
        call_args = mock_import.call_args
        assert call_args[0][0] == "BanCode"

    @patch("app.services.scanner_engine._import_scanner")
    def test_bancode_no_languages_output_wraps_with_bancode_class(self, mock_import):
        """BanCode with no languages + output direction → wrapped in BanCode class."""
        from app.services.scanner_engine import BanCode as BanCodeClass
        inner = MagicMock()
        mock_import.return_value = inner
        result = _build_scanner("BanCode", "output", {})
        assert isinstance(result, BanCodeClass)

    @patch("app.services.scanner_engine._import_scanner")
    def test_bancode_no_languages_input_no_wrap(self, mock_import):
        """BanCode with no languages + input direction → NOT wrapped."""
        from app.services.scanner_engine import BanCode as BanCodeClass
        inner = MagicMock()
        mock_import.return_value = inner
        result = _build_scanner("BanCode", "input", {})
        assert result is inner
        assert not isinstance(result, BanCodeClass)

    @patch("app.services.scanner_engine._import_scanner")
    def test_bancode_no_languages_strips_invalid_keys(self, mock_import):
        """BanCode with no languages strips 'languages' and 'is_blocked' keys."""
        mock_import.return_value = MagicMock()
        _build_scanner("BanCode", "input", {"languages": None, "is_blocked": True, "threshold": 0.5})
        call_args = mock_import.call_args
        params = call_args[0][2]
        assert "languages" not in params
        assert "is_blocked" not in params
        assert params.get("threshold") == 0.5


# ── BanCode wrapper class tests ──────────────────────────────────────────────

class TestBanCodeWrapper:
    """Test the BanCode output wrapper class."""

    def test_scan_with_markdown_fence_blocks(self):
        """When output contains a markdown code fence, scan returns blocked."""
        from app.services.scanner_engine import BanCode as BanCodeClass
        inner = MagicMock()
        wrapper = BanCodeClass(inner)

        output_with_fence = "Here is some code:\n```python\nprint('hello')\n```"
        result = wrapper.scan("prompt", output_with_fence)
        assert result == (output_with_fence, False, 1.0)
        inner.scan.assert_not_called()

    def test_scan_without_fence_delegates_to_inner(self):
        """When output has no markdown fence, delegates to the inner scanner."""
        from app.services.scanner_engine import BanCode as BanCodeClass
        inner = MagicMock()
        inner.scan.return_value = ("clean output", True, 0.1)
        wrapper = BanCodeClass(inner)

        result = wrapper.scan("prompt", "clean output without code")
        assert result == ("clean output", True, 0.1)
        inner.scan.assert_called_once_with("prompt", "clean output without code")

    def test_scan_with_inline_backticks_not_blocked(self):
        """Inline backticks (not fenced blocks) should not trigger the wrapper."""
        from app.services.scanner_engine import BanCode as BanCodeClass
        inner = MagicMock()
        inner.scan.return_value = ("use `print()`", True, 0.05)
        wrapper = BanCodeClass(inner)

        result = wrapper.scan("prompt", "use `print()`")
        assert result[1] is True  # valid
        inner.scan.assert_called_once()


# ── Normalize languages edge cases ───────────────────────────────────────────

class TestNormalizeLanguagesExtended:
    """Test _normalize_languages with specific constant aliases."""

    def test_mathematica_alias(self):
        result = _normalize_languages(["mathematica"])
        from app.services.scanner_engine import _LANG_MATHEMATICA
        assert result == [_LANG_MATHEMATICA]

    def test_wolfram_alias(self):
        result = _normalize_languages(["wolfram"])
        from app.services.scanner_engine import _LANG_MATHEMATICA
        assert result == [_LANG_MATHEMATICA]

    def test_vb_net_alias(self):
        result = _normalize_languages(["vb.net"])
        from app.services.scanner_engine import _LANG_VB_NET
        assert result == [_LANG_VB_NET]

    def test_vb_alias(self):
        result = _normalize_languages(["vb"])
        from app.services.scanner_engine import _LANG_VB_NET
        assert result == [_LANG_VB_NET]

    def test_typescript_maps_to_javascript(self):
        result = _normalize_languages(["typescript"])
        assert result == ["JavaScript"]

    def test_csharp_alias(self):
        result = _normalize_languages(["csharp"])
        assert result == ["C#"]

    def test_bash_maps_to_powershell(self):
        result = _normalize_languages(["bash"])
        assert result == ["PowerShell"]

    def test_shell_and_sh_aliases(self):
        result = _normalize_languages(["shell", "sh"])
        # Both map to PowerShell; dedup means only one entry
        assert result == ["PowerShell"]

    def test_mixed_valid_and_empty(self):
        result = _normalize_languages(["", "python", "", "js", ""])
        assert result == ["Python", "JavaScript"]
