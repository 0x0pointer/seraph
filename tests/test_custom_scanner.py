"""Unit tests for app/services/custom_scanner.py — CustomRuleScanner."""
from unittest.mock import patch, MagicMock


class TestCustomRuleScannerInit:
    def test_init_defaults(self):
        from app.services.custom_scanner import CustomRuleScanner

        scanner = CustomRuleScanner()
        assert scanner._direction == "input"
        assert scanner._keywords == []
        assert scanner._patterns == []
        assert scanner._topics == []
        assert scanner._topics_threshold == 0.5
        assert scanner._ban_topics_scanner is None

    def test_init_with_keywords(self):
        from app.services.custom_scanner import CustomRuleScanner

        scanner = CustomRuleScanner(blocked_keywords=["secret", " ", "", "password"])
        assert scanner._keywords == ["secret", "password"]

    def test_init_with_valid_patterns(self):
        from app.services.custom_scanner import CustomRuleScanner

        scanner = CustomRuleScanner(blocked_patterns=[r"\d{3}-\d{4}", r"SSN\s*:"])
        assert len(scanner._patterns) == 2

    def test_init_with_invalid_regex_skipped(self):
        from app.services.custom_scanner import CustomRuleScanner

        scanner = CustomRuleScanner(blocked_patterns=[r"[invalid", r"good.*pattern"])
        # invalid regex is skipped, only the valid one remains
        assert len(scanner._patterns) == 1

    def test_init_with_empty_and_blank_patterns(self):
        from app.services.custom_scanner import CustomRuleScanner

        scanner = CustomRuleScanner(blocked_patterns=["", "  ", r"\d+"])
        assert len(scanner._patterns) == 1

    def test_init_with_topics_builds_ban_topics(self):
        from app.services.custom_scanner import CustomRuleScanner

        mock_bt = MagicMock()
        with patch.object(
            CustomRuleScanner, "_build_ban_topics", return_value=mock_bt
        ):
            scanner = CustomRuleScanner(
                blocked_topics=["violence", " ", "drugs"],
                topics_threshold=0.7,
            )
        assert scanner._topics == ["violence", "drugs"]
        assert scanner._topics_threshold == 0.7
        assert scanner._ban_topics_scanner is mock_bt

    def test_init_with_empty_topics_no_build(self):
        from app.services.custom_scanner import CustomRuleScanner

        scanner = CustomRuleScanner(blocked_topics=[])
        assert scanner._ban_topics_scanner is None


class TestTargetText:
    def test_input_direction_returns_prompt(self):
        from app.services.custom_scanner import CustomRuleScanner

        scanner = CustomRuleScanner(direction="input")
        assert scanner._target_text("prompt text", "output text") == "prompt text"

    def test_output_direction_returns_output(self):
        from app.services.custom_scanner import CustomRuleScanner

        scanner = CustomRuleScanner(direction="output")
        assert scanner._target_text("prompt text", "output text") == "output text"

    def test_output_direction_empty_output_returns_prompt(self):
        from app.services.custom_scanner import CustomRuleScanner

        scanner = CustomRuleScanner(direction="output")
        assert scanner._target_text("prompt text", "") == "prompt text"


class TestScan:
    def test_keyword_match_returns_invalid(self):
        from app.services.custom_scanner import CustomRuleScanner

        scanner = CustomRuleScanner(blocked_keywords=["secret"])
        text, is_valid, score = scanner.scan("this is a Secret message")
        assert is_valid is False
        assert score == 1.0

    def test_pattern_match_returns_invalid(self):
        from app.services.custom_scanner import CustomRuleScanner

        scanner = CustomRuleScanner(blocked_patterns=[r"\d{3}-\d{2}-\d{4}"])
        text, is_valid, score = scanner.scan("SSN: 123-45-6789")
        assert is_valid is False
        assert score == 1.0

    def test_topic_match_returns_invalid(self):
        from app.services.custom_scanner import CustomRuleScanner

        mock_bt = MagicMock()
        mock_bt.scan.return_value = ("text", False, 0.85)

        scanner = CustomRuleScanner()
        scanner._ban_topics_scanner = mock_bt

        text, is_valid, score = scanner.scan("violent content")
        assert is_valid is False
        assert score == 0.85
        mock_bt.scan.assert_called_once_with("violent content")

    def test_topic_valid_passes_through(self):
        from app.services.custom_scanner import CustomRuleScanner

        mock_bt = MagicMock()
        mock_bt.scan.return_value = ("text", True, 0.1)

        scanner = CustomRuleScanner()
        scanner._ban_topics_scanner = mock_bt

        text, is_valid, score = scanner.scan("normal content")
        assert is_valid is True
        assert score == 0.0

    def test_all_clear_returns_valid(self):
        from app.services.custom_scanner import CustomRuleScanner

        scanner = CustomRuleScanner(
            blocked_keywords=["secret"],
            blocked_patterns=[r"SSN"],
        )
        text, is_valid, score = scanner.scan("hello world")
        assert is_valid is True
        assert score == 0.0

    def test_output_mode_scans_output_text(self):
        from app.services.custom_scanner import CustomRuleScanner

        scanner = CustomRuleScanner(
            direction="output",
            blocked_keywords=["forbidden"],
        )
        text, is_valid, score = scanner.scan("safe prompt", "this is forbidden output")
        assert is_valid is False
        assert score == 1.0

    def test_scan_prompt_only_no_output(self):
        from app.services.custom_scanner import CustomRuleScanner

        scanner = CustomRuleScanner(blocked_keywords=["bad"])
        text, is_valid, score = scanner.scan("bad input")
        assert is_valid is False
