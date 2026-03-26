"""Unit tests for helper functions in app/services/scanner_engine."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.services.scanner_engine import (
    _find_action_for_scanner,
    _handle_violation_action,
    _result_cache_key,
    _result_cache_get,
    _result_cache_put,
    invalidate_cache,
    _result_cache,
    _build_reask_message,
    _build_scanner,
    _apply_custom_phrases,
)


def _make_entry(scanner_name: str, guardrail_id: int = 1, on_fail_action: str = "block"):
    """Build a fake scanner entry tuple: (scanner, name, phrases, id, params, action)."""
    return (None, scanner_name, [], guardrail_id, {}, on_fail_action)


class TestFindActionForScanner:
    def test_finds_correct_action(self):
        entries = [
            _make_entry("EmbeddingShield", on_fail_action="monitor"),
            _make_entry("CustomRule", on_fail_action="fix"),
        ]
        assert _find_action_for_scanner(entries, "EmbeddingShield") == "monitor"
        assert _find_action_for_scanner(entries, "CustomRule") == "fix"

    def test_returns_block_for_unknown(self):
        entries = [_make_entry("EmbeddingShield")]
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


class TestResultCache:
    def setup_method(self):
        invalidate_cache()

    def test_cache_key_deterministic(self):
        k1 = _result_cache_key("input", "hello")
        k2 = _result_cache_key("input", "hello")
        assert k1 == k2

    def test_cache_key_differs_for_different_text(self):
        k1 = _result_cache_key("input", "hello")
        k2 = _result_cache_key("input", "world")
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
        from app.services.scanner_engine import _RESULT_CACHE_SIZE
        invalidate_cache()
        for i in range(_RESULT_CACHE_SIZE + 1):
            _result_cache_put(f"key_{i}", f"val_{i}")
        assert _result_cache_get("key_0") is None
        assert _result_cache_get(f"key_{_RESULT_CACHE_SIZE}") == f"val_{_RESULT_CACHE_SIZE}"


class TestBuildReaskMessage:
    def test_returns_formatted_string_with_name_and_score(self):
        msg = _build_reask_message("Toxicity", 0.92)
        assert "Toxicity" in msg
        assert "92%" in msg

    def test_returns_formatted_string_zero_score(self):
        msg = _build_reask_message("EmbeddingShield", 0.0)
        assert "EmbeddingShield" in msg
        assert "0%" in msg

    def test_returns_formatted_string_full_score(self):
        msg = _build_reask_message("CustomRule", 1.0)
        assert "CustomRule" in msg
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

    def test_unknown_scanner_type_raises(self):
        with pytest.raises(ValueError, match="Unknown first-party scanner"):
            _build_scanner("Toxicity", "input", {"threshold": 0.7})


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


# ── Direct scan function tests ──────────────────────────────────────────────

class TestRunInputScan:
    """Test run_input_scan directly with mocked tiers."""

    def setup_method(self):
        invalidate_cache()

    def test_empty_scanner_list_returns_valid(self):
        import asyncio
        from app.services.scanner_engine import run_input_scan
        result = asyncio.run(run_input_scan("hello"))
        is_valid, text, scores, violations, actions, reask, fix = result
        assert is_valid is True
        assert text == "hello"
        assert violations == []

    def test_allowed_types_filter(self):
        import asyncio
        from app.services.scanner_engine import run_input_scan
        result = asyncio.run(
            run_input_scan("hello")
        )
        assert result[0] is True


class TestRunOutputScan:
    """Test run_output_scan directly with mocked tiers."""

    def setup_method(self):
        invalidate_cache()

    def test_empty_scanner_list_returns_valid(self):
        import asyncio
        from app.services.scanner_engine import run_output_scan
        result = asyncio.run(
            run_output_scan("What is AI?", "AI is artificial intelligence.")
        )
        is_valid, text, scores, violations, actions, reask, fix = result
        assert is_valid is True
        assert text == "AI is artificial intelligence."
        assert violations == []


class TestRunGuardScan:
    """Test run_guard_scan directly."""

    def setup_method(self):
        invalidate_cache()

    def test_empty_messages_not_flagged(self):
        import asyncio
        from app.services.scanner_engine import run_guard_scan
        result = asyncio.run(
            run_guard_scan([])
        )
        flagged, results, violations = result
        assert flagged is False

    def test_user_only_messages(self):
        import asyncio
        from app.services.scanner_engine import run_guard_scan
        result = asyncio.run(
            run_guard_scan([{"role": "user", "content": "hello"}])
        )
        flagged, results, violations = result
        assert flagged is False

    def test_user_and_assistant_messages(self):
        import asyncio
        from app.services.scanner_engine import run_guard_scan
        result = asyncio.run(
            run_guard_scan([
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ])
        )
        flagged, results, violations = result
        assert flagged is False


class TestReloadScanners:
    def test_reload_invalidates_cache(self):
        from app.services.scanner_engine import reload_scanners
        _result_cache_put("test_key", "test_value")
        reload_scanners()
        assert _result_cache_get("test_key") is None


class TestWarmup:
    def test_warmup_runs_without_error(self):
        import asyncio
        from app.services.scanner_engine import warmup
        asyncio.run(warmup())
