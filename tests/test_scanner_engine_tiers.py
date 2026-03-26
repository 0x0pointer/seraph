"""Tests for scanner_engine.py tier helpers and two-tier pipeline functions."""
import asyncio
from dataclasses import dataclass
from unittest.mock import patch, MagicMock, AsyncMock

_run = lambda coro: asyncio.run(coro)


# ── Tier singleton tests ────────────────────────────────────────────────────

class TestGetNemoTier:
    def setup_method(self):
        from app.services.scanner_engine import invalidate_cache
        invalidate_cache()

    def test_returns_none_when_disabled(self):
        from app.services.scanner_engine import _get_nemo_tier
        mock_config = MagicMock()
        mock_config.nemo_tier.enabled = False
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            assert _get_nemo_tier() is None

    def test_creates_and_caches_instance(self):
        from app.services.scanner_engine import _get_nemo_tier, invalidate_cache
        invalidate_cache()
        mock_config = MagicMock()
        mock_config.nemo_tier.enabled = True
        mock_config.nemo_tier.config_dir = "/tmp"
        mock_config.nemo_tier.embedding_threshold = 0.85
        mock_config.nemo_tier.model = "gpt-4o-mini"
        mock_config.nemo_tier.model_engine = "openai"
        mock_config.nemo_tier.api_key = "key"
        mock_config.upstream_api_key = ""

        mock_nemo_cls = MagicMock()
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            with patch("app.services.nemo_tier.NemoTier", mock_nemo_cls):
                tier1 = _get_nemo_tier()
                tier2 = _get_nemo_tier()  # Should return cached
        assert tier1 is tier2
        mock_nemo_cls.assert_called_once()
        invalidate_cache()


class TestGetJudge:
    def setup_method(self):
        from app.services.scanner_engine import invalidate_cache
        invalidate_cache()

    def test_returns_none_when_disabled(self):
        from app.services.scanner_engine import _get_judge
        mock_config = MagicMock()
        mock_config.judge.enabled = False
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            assert _get_judge() is None

    def test_creates_and_caches_instance(self):
        from app.services.scanner_engine import _get_judge, invalidate_cache
        invalidate_cache()
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.model = "gpt-4o-mini"
        mock_config.judge.base_url = None
        mock_config.judge.api_key = "key"
        mock_config.judge.temperature = 0.0
        mock_config.judge.max_tokens = 512
        mock_config.judge.risk_threshold = 0.7
        mock_config.judge.prompt_file = "/tmp/prompt.txt"
        mock_config.upstream_api_key = ""

        mock_judge_cls = MagicMock()
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            with patch("app.services.langgraph_judge.LangGraphJudge", mock_judge_cls):
                j1 = _get_judge()
                j2 = _get_judge()
        assert j1 is j2
        mock_judge_cls.assert_called_once()
        invalidate_cache()


# ── Helper function tests ───────────────────────────────────────────────────

class TestUnpackNemoResult:
    def test_none_nemo_returns_pass(self):
        from app.services.scanner_engine import _unpack_nemo_result
        passed, score = _unpack_nemo_result([MagicMock()], None)
        assert passed is True
        assert score == 0.0

    def test_no_nemo_in_gathered(self):
        from app.services.scanner_engine import _unpack_nemo_result
        passed, score = _unpack_nemo_result([MagicMock()], MagicMock())
        assert passed is True
        assert score == 0.0

    def test_exception_returns_block(self):
        from app.services.scanner_engine import _unpack_nemo_result
        passed, score = _unpack_nemo_result([MagicMock(), RuntimeError("fail")], MagicMock())
        assert passed is False
        assert score == 1.0

    def test_successful_result(self):
        from app.services.scanner_engine import _unpack_nemo_result

        @dataclass
        class FakeNemo:
            passed: bool = True
            risk_score: float = 0.1

        passed, score = _unpack_nemo_result([MagicMock(), FakeNemo()], MagicMock())
        assert passed is True
        assert score == 0.1


class TestUnpackFpResult:
    def test_exception_returns_fallback(self):
        from app.services.scanner_engine import _unpack_fp_result
        result = _unpack_fp_result(RuntimeError("fail"), "fallback")
        assert result == (True, "fallback", {}, [], {}, [], False)

    def test_normal_result_passed_through(self):
        from app.services.scanner_engine import _unpack_fp_result
        fp = (True, "text", {"S": 0.1}, [], {}, [], False)
        assert _unpack_fp_result(fp, "fallback") == fp


class TestApplyNemoBlock:
    def test_nemo_passed(self):
        from app.services.scanner_engine import _apply_nemo_block
        scores, violations, actions = {}, [], {}
        result = _apply_nemo_block(True, 0.0, scores, violations, actions)
        assert result is True
        assert "NeMoGuardrails" not in scores

    def test_nemo_blocked(self):
        from app.services.scanner_engine import _apply_nemo_block
        scores, violations, actions = {}, [], {}
        result = _apply_nemo_block(False, 1.0, scores, violations, actions)
        assert result is False
        assert scores["NeMoGuardrails"] == 1.0
        assert "NeMoGuardrails" in violations
        assert actions["NeMoGuardrails"] == "blocked"


class TestBuildScanResult:
    def test_with_reask(self):
        from app.services.scanner_engine import _build_scan_result
        result = _build_scan_result(False, "text", {}, ["S1"], {}, ["fix this"], False)
        assert result[5] == ["fix this"]

    def test_without_reask(self):
        from app.services.scanner_engine import _build_scan_result
        result = _build_scan_result(True, "text", {}, [], {}, [], False)
        assert result[5] is None


class TestShouldRunJudge:
    def test_disabled(self):
        from app.services.scanner_engine import _should_run_judge
        mock_config = MagicMock()
        mock_config.judge.enabled = False
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            assert _should_run_judge(0.5) is False

    def test_every_request(self):
        from app.services.scanner_engine import _should_run_judge
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            assert _should_run_judge(0.5) is True

    def test_uncertainty_band_inside(self):
        from app.services.scanner_engine import _should_run_judge
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = False
        mock_config.judge.uncertainty_band_low = 0.70
        mock_config.judge.uncertainty_band_high = 0.85
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            assert _should_run_judge(0.75) is True

    def test_uncertainty_band_outside(self):
        from app.services.scanner_engine import _should_run_judge
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = False
        mock_config.judge.uncertainty_band_low = 0.70
        mock_config.judge.uncertainty_band_high = 0.85
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            assert _should_run_judge(0.5) is False


class TestRunJudgeTier:
    def setup_method(self):
        from app.services.scanner_engine import invalidate_cache
        invalidate_cache()

    def test_skips_when_not_needed(self):
        from app.services.scanner_engine import _run_judge_tier
        mock_config = MagicMock()
        mock_config.judge.enabled = False
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            blocked = _run(_run_judge_tier("text", "input", 0.0, {}, [], {}))
        assert blocked is False

    def test_skips_when_no_judge(self):
        from app.services.scanner_engine import _run_judge_tier
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            with patch("app.services.scanner_engine._get_judge", return_value=None):
                blocked = _run(_run_judge_tier("text", "input", 0.0, {}, [], {}))
        assert blocked is False

    def test_judge_blocks(self):
        from app.services.scanner_engine import _run_judge_tier, invalidate_cache
        invalidate_cache()

        @dataclass
        class FakeJudgeResult:
            passed: bool = False
            risk_score: float = 0.9
            reasoning: str = "injection"
            threats: list = None
            latency_ms: float = 100.0
            def __post_init__(self):
                self.threats = self.threats or ["injection"]

        mock_judge = MagicMock()
        mock_judge.evaluate = AsyncMock(return_value=FakeJudgeResult())
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True

        scores, violations, actions = {}, [], {}
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            with patch("app.services.scanner_engine._get_judge", return_value=mock_judge):
                blocked = _run(_run_judge_tier("hack", "input", 0.0, scores, violations, actions))
        assert blocked is True
        assert "LLMJudge" in violations
        assert scores["LLMJudge"] == 0.9

    def test_judge_passes(self):
        from app.services.scanner_engine import _run_judge_tier, invalidate_cache
        invalidate_cache()

        @dataclass
        class FakeJudgeResult:
            passed: bool = True
            risk_score: float = 0.1
            reasoning: str = "benign"
            threats: list = None
            latency_ms: float = 100.0
            def __post_init__(self):
                self.threats = self.threats or []

        mock_judge = MagicMock()
        mock_judge.evaluate = AsyncMock(return_value=FakeJudgeResult())
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True

        scores, violations, actions = {}, [], {}
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            with patch("app.services.scanner_engine._get_judge", return_value=mock_judge):
                blocked = _run(_run_judge_tier("hello", "input", 0.0, scores, violations, actions))
        assert blocked is False
        assert scores["LLMJudge"] == 0.1

    def test_judge_exception(self):
        from app.services.scanner_engine import _run_judge_tier, invalidate_cache
        invalidate_cache()

        mock_judge = MagicMock()
        mock_judge.evaluate = AsyncMock(side_effect=RuntimeError("judge crashed"))
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True

        scores, violations, actions = {}, [], {}
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            with patch("app.services.scanner_engine._get_judge", return_value=mock_judge):
                blocked = _run(_run_judge_tier("test", "input", 0.0, scores, violations, actions))
        assert blocked is True
        assert scores["LLMJudge"] == 1.0


class TestMergeKeyedScores:
    def test_no_collision(self):
        from app.services.scanner_engine import _merge_keyed_scores
        merged = {"A": 0.1}
        _merge_keyed_scores(merged, {"B": 0.2}, "")
        assert merged == {"A": 0.1, "B": 0.2}

    def test_with_suffix_on_collision(self):
        from app.services.scanner_engine import _merge_keyed_scores
        merged = {"S1": 0.5}
        _merge_keyed_scores(merged, {"S1": 0.7}, "output")
        assert "S1 (output)" in merged
        assert merged["S1 (output)"] == 0.7


class TestMergeKeyedViolations:
    def test_no_collision(self):
        from app.services.scanner_engine import _merge_keyed_violations
        merged = ["A"]
        _merge_keyed_violations(merged, ["B"], "")
        assert merged == ["A", "B"]

    def test_with_suffix_on_collision(self):
        from app.services.scanner_engine import _merge_keyed_violations
        merged = ["S1"]
        _merge_keyed_violations(merged, ["S1"], "output")
        assert "S1 (output)" in merged


class TestMergeGuardResults:
    def test_merges_input_and_output(self):
        from app.services.scanner_engine import _merge_guard_results
        gathered = [
            (True, "t", {"S1": 0.1}, [], {}, None, False),
            (True, "t", {"S2": 0.2}, ["S2"], {}, None, False),
        ]
        coros = [("input", None), ("output", None)]
        results, violations = _merge_guard_results(gathered, coros)
        assert "S1" in results
        assert "S2" in results
        assert "S2" in violations


class TestProcessFpViolations:
    def test_all_valid(self):
        from app.services.scanner_engine import _process_fp_violations
        entries = [(None, "S1", [], 0, {}, "block")]
        valid, violations, actions, reask, fix, text = _process_fp_violations(
            {"S1": True}, {"S1": 0.1}, entries, "orig", {},
        )
        assert valid is True
        assert violations == []

    def test_block_violation(self):
        from app.services.scanner_engine import _process_fp_violations
        entries = [(None, "S1", [], 0, {}, "block")]
        valid, violations, actions, reask, fix, text = _process_fp_violations(
            {"S1": False}, {"S1": 0.9}, entries, "orig", {},
        )
        assert valid is False
        assert "S1" in violations
        assert actions["S1"] == "blocked"


class TestCollectScannerResults:
    def test_normal_results(self):
        from app.services.scanner_engine import _collect_scanner_results
        entries = [(None, "S1", [], 0, {}, "block"), (None, "S2", [], 1, {}, "monitor")]
        raw = [("san1", True, 0.1), ("san2", False, 0.9)]
        valid, score, sanitized = _collect_scanner_results(raw, entries)
        assert valid == {"S1": True, "S2": False}
        assert "S2" in sanitized

    def test_exception_skipped(self):
        from app.services.scanner_engine import _collect_scanner_results
        entries = [(None, "S1", [], 0, {}, "block")]
        raw = [RuntimeError("fail")]
        valid, score, sanitized = _collect_scanner_results(raw, entries)
        assert valid == {}


class TestWarmupWithTiers:
    def setup_method(self):
        from app.services.scanner_engine import invalidate_cache
        invalidate_cache()

    def test_warmup_with_nemo_enabled(self):
        from app.services.scanner_engine import warmup, invalidate_cache
        invalidate_cache()

        mock_nemo = MagicMock()
        mock_nemo.warmup = AsyncMock()

        mock_judge = MagicMock()

        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            with patch("app.services.scanner_engine._get_judge", return_value=mock_judge):
                _run(warmup())

        mock_nemo.warmup.assert_called_once()
        invalidate_cache()

    def test_warmup_nemo_failure(self):
        from app.services.scanner_engine import warmup, invalidate_cache
        invalidate_cache()

        mock_nemo = MagicMock()
        mock_nemo.warmup = AsyncMock(side_effect=RuntimeError("nemo broke"))

        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            with patch("app.services.scanner_engine._get_judge", return_value=None):
                _run(warmup())  # Should not raise

        invalidate_cache()
