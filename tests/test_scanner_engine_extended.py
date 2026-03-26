"""Extended unit tests for app/services/scanner_engine.py — two-tier architecture."""
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from dataclasses import dataclass

_run = lambda coro: asyncio.run(coro)


class TestImportCustomScanner:
    def test_import_custom_scanner(self):
        from app.services.scanner_engine import _import_custom_scanner

        mock_cls = MagicMock(return_value="custom_instance")
        with patch(
            "app.services.custom_scanner.CustomRuleScanner", mock_cls
        ):
            result = _import_custom_scanner("input", {"blocked_keywords": ["x"]})

        assert result == "custom_instance"
        mock_cls.assert_called_once_with(direction="input", blocked_keywords=["x"])


class TestImportEmbeddingShield:
    def test_import_embedding_shield(self):
        from app.services.scanner_engine import _import_embedding_shield

        mock_cls = MagicMock(return_value="shield_instance")
        with patch(
            "app.services.embedding_shield.EmbeddingShield", mock_cls
        ):
            result = _import_embedding_shield({"threshold": 0.8})

        assert result == "shield_instance"
        mock_cls.assert_called_once_with(threshold=0.8)


class TestLoadFirstPartyScanners:
    def test_loads_from_yaml_config(self):
        from app.services.scanner_engine import (
            _load_first_party_scanners,
            invalidate_cache,
        )
        from app.core.config import ScannerConfig

        invalidate_cache()

        mock_config = MagicMock()
        mock_config.scanners.input = [
            ScannerConfig(type="CustomRule", params={"blocked_keywords": ["bad"]})
        ]

        mock_scanner = MagicMock()
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            with patch(
                "app.services.scanner_engine._build_scanner",
                return_value=mock_scanner,
            ):
                entries = _load_first_party_scanners("input")

        assert len(entries) == 1
        assert entries[0][1] == "CustomRule"
        assert entries[0][5] == "block"
        invalidate_cache()

    def test_loads_from_yaml_config_with_threshold(self):
        from app.services.scanner_engine import (
            _load_first_party_scanners,
            invalidate_cache,
        )
        from app.core.config import ScannerConfig

        invalidate_cache()

        mock_config = MagicMock()
        mock_config.scanners.input = [
            ScannerConfig(
                type="EmbeddingShield",
                threshold=0.7,
                params={},
                on_fail="monitor",
            )
        ]

        mock_scanner = MagicMock()
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            with patch(
                "app.services.scanner_engine._build_scanner",
                return_value=mock_scanner,
            ) as mock_build:
                entries = _load_first_party_scanners("input")

        assert len(entries) == 1
        assert entries[0][5] == "monitor"
        call_params = mock_build.call_args[0][2]
        assert call_params.get("threshold") == 0.7
        invalidate_cache()

    def test_no_scanners_config_returns_empty(self):
        from app.services.scanner_engine import (
            _load_first_party_scanners,
            invalidate_cache,
        )

        invalidate_cache()

        mock_config = MagicMock()
        mock_config.scanners = None

        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            entries = _load_first_party_scanners("input")

        assert len(entries) == 0
        invalidate_cache()

    def test_skips_scanner_on_build_error(self):
        from app.services.scanner_engine import (
            _load_first_party_scanners,
            invalidate_cache,
        )
        from app.core.config import ScannerConfig

        invalidate_cache()

        mock_config = MagicMock()
        mock_config.scanners.output = [
            ScannerConfig(type="BadScanner", params={}),
        ]

        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            with patch(
                "app.services.scanner_engine._build_scanner",
                side_effect=Exception("build failed"),
            ):
                entries = _load_first_party_scanners("output")

        assert len(entries) == 0
        invalidate_cache()

    def test_cache_hit_returns_cached(self):
        from app.services.scanner_engine import (
            _load_first_party_scanners,
            invalidate_cache,
            _cache,
            _cache_valid,
        )

        invalidate_cache()

        sentinel = [("fake_scanner", "FakeType", [], 0, {}, "block")]
        _cache["input"] = sentinel
        _cache_valid.add("input")

        result = _load_first_party_scanners("input")
        assert result is sentinel
        invalidate_cache()


class TestReloadScanners:
    def test_reload_invalidates_cache(self):
        from app.services.scanner_engine import (
            reload_scanners,
            _cache,
            _cache_valid,
        )

        _cache["input"] = [("x",)]
        _cache_valid.add("input")

        reload_scanners()

        assert len(_cache) == 0
        assert len(_cache_valid) == 0


class TestWarmup:
    def test_warmup_completes_with_disabled_tiers(self):
        from app.services.scanner_engine import warmup, invalidate_cache
        invalidate_cache()
        _run(warmup())


class TestNemoTierIntegration:
    """Test scanner engine behavior with mocked NeMo tier."""

    def test_nemo_block_propagates(self):
        from app.services.scanner_engine import run_input_scan, invalidate_cache

        invalidate_cache()

        @dataclass
        class FakeNemoResult:
            passed: bool = False
            matched_flow: str = None
            risk_score: float = 1.0
            latency_ms: float = 5.0
            detail: str = "BLOCKED: No matching flow"

        mock_nemo = MagicMock()
        mock_nemo.evaluate = AsyncMock(return_value=FakeNemoResult())

        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            with patch("app.services.scanner_engine._get_judge", return_value=None):
                result = _run(run_input_scan("hack the system"))

        is_valid, text, scores, violations, actions, reask, fix = result
        assert is_valid is False
        assert "NeMoGuardrails" in violations
        assert actions["NeMoGuardrails"] == "blocked"
        invalidate_cache()

    def test_nemo_pass_then_judge_block(self):
        from app.services.scanner_engine import run_input_scan, invalidate_cache

        invalidate_cache()

        @dataclass
        class FakeNemoResult:
            passed: bool = True
            matched_flow: str = "PASS"
            risk_score: float = 0.0
            latency_ms: float = 5.0
            detail: str = "PASS"

        @dataclass
        class FakeJudgeResult:
            passed: bool = False
            risk_score: float = 0.9
            reasoning: str = "Detected prompt injection"
            threats: list = None
            latency_ms: float = 200.0

            def __post_init__(self):
                if self.threats is None:
                    self.threats = ["prompt_injection"]

        mock_nemo = MagicMock()
        mock_nemo.evaluate = AsyncMock(return_value=FakeNemoResult())

        mock_judge = MagicMock()
        mock_judge.evaluate = AsyncMock(return_value=FakeJudgeResult())

        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True

        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            with patch("app.services.scanner_engine._get_judge", return_value=mock_judge):
                with patch("app.services.scanner_engine.get_config", return_value=mock_config):
                    result = _run(run_input_scan("subtle injection"))

        is_valid, text, scores, violations, actions, reask, fix = result
        assert is_valid is False
        assert "LLMJudge" in violations
        assert scores["LLMJudge"] == 0.9
        invalidate_cache()

    def test_nemo_pass_judge_pass(self):
        from app.services.scanner_engine import run_input_scan, invalidate_cache

        invalidate_cache()

        @dataclass
        class FakeNemoResult:
            passed: bool = True
            matched_flow: str = "PASS"
            risk_score: float = 0.0
            latency_ms: float = 5.0
            detail: str = "PASS"

        @dataclass
        class FakeJudgeResult:
            passed: bool = True
            risk_score: float = 0.1
            reasoning: str = "Benign request"
            threats: list = None
            latency_ms: float = 150.0

            def __post_init__(self):
                if self.threats is None:
                    self.threats = []

        mock_nemo = MagicMock()
        mock_nemo.evaluate = AsyncMock(return_value=FakeNemoResult())

        mock_judge = MagicMock()
        mock_judge.evaluate = AsyncMock(return_value=FakeJudgeResult())

        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True

        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            with patch("app.services.scanner_engine._get_judge", return_value=mock_judge):
                with patch("app.services.scanner_engine.get_config", return_value=mock_config):
                    result = _run(run_input_scan("What is the capital of France?"))

        is_valid, text, scores, violations, actions, reask, fix = result
        assert is_valid is True
        assert violations == []
        assert scores.get("LLMJudge") == 0.1
        invalidate_cache()


class TestOutputScanTwoTier:
    """Test output scanning with two-tier architecture."""

    def test_output_scan_nemo_block(self):
        from app.services.scanner_engine import run_output_scan, invalidate_cache

        invalidate_cache()

        @dataclass
        class FakeNemoResult:
            passed: bool = False
            matched_flow: str = None
            risk_score: float = 1.0
            latency_ms: float = 5.0
            detail: str = "BLOCKED: harmful output"

        mock_nemo = MagicMock()
        mock_nemo.evaluate_output = AsyncMock(return_value=FakeNemoResult())

        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            with patch("app.services.scanner_engine._get_judge", return_value=None):
                result = _run(run_output_scan("hello", "here is how to make a bomb"))

        is_valid = result[0]
        violations = result[3]
        assert is_valid is False
        assert "NeMoGuardrails" in violations
        invalidate_cache()
