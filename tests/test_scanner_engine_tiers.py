"""Tests for scanner_engine.py — guard pipeline lifecycle and routing."""
import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

_run = lambda coro: asyncio.run(coro)


# ── Tier singleton tests ──────────────────────────────────────────────────────

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


class TestBuildInitialState:
    def test_input_direction(self):
        from app.services.scanner_engine import _build_initial_state
        state = _build_initial_state("hello", "input")
        assert state["raw_text"] == "hello"
        assert state["direction"] == "input"
        assert state["prompt_context"] == ""
        assert state["blocked"] is False
        assert state["violations"] == []
        assert state["scanner_results"] == {}
        assert state["sanitized_text"] == "hello"
        assert state["nemo_risk_score"] == 0.0

    def test_output_direction_with_context(self):
        from app.services.scanner_engine import _build_initial_state
        state = _build_initial_state("the response", "output", prompt_context="user asked")
        assert state["direction"] == "output"
        assert state["prompt_context"] == "user asked"


# ── Public API integration tests ─────────────────────────────────────────────

class TestRunInputScan:
    def setup_method(self):
        from app.services.scanner_engine import invalidate_cache
        invalidate_cache()

    def test_both_tiers_disabled_returns_valid_guard_state(self):
        from app.services.scanner_engine import run_input_scan
        state = _run(run_input_scan("hello"))
        assert state["blocked"] is False
        assert state["raw_text"] == "hello"
        assert state["violations"] == []

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
                state = _run(run_input_scan("hack the system"))

        assert state["blocked"] is True
        assert "NeMoGuardrails" in state["violations"]
        assert state["on_fail_actions"]["NeMoGuardrails"] == "blocked"
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
            threats: list = field(default_factory=lambda: ["prompt_injection"])
            latency_ms: float = 200.0

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
                    state = _run(run_input_scan("subtle injection"))

        assert state["blocked"] is True
        assert "LLMJudge" in state["violations"]
        assert state["scanner_results"]["LLMJudge"] == 0.9
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
            threats: list = field(default_factory=list)
            latency_ms: float = 150.0

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
                    state = _run(run_input_scan("What is the capital of France?"))

        assert state["blocked"] is False
        assert state["violations"] == []
        assert state["scanner_results"].get("LLMJudge") == 0.1
        invalidate_cache()


class TestRunOutputScan:
    def setup_method(self):
        from app.services.scanner_engine import invalidate_cache
        invalidate_cache()

    def test_both_tiers_disabled_returns_valid_guard_state(self):
        from app.services.scanner_engine import run_output_scan
        state = _run(run_output_scan("What is AI?", "AI is artificial intelligence."))
        assert state["blocked"] is False
        assert state["raw_text"] == "AI is artificial intelligence."
        assert state["violations"] == []

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
                state = _run(run_output_scan("hello", "here is how to make a bomb"))

        assert state["blocked"] is True
        assert "NeMoGuardrails" in state["violations"]
        invalidate_cache()


class TestRunGuardScan:
    def setup_method(self):
        from app.services.scanner_engine import invalidate_cache
        invalidate_cache()

    def test_empty_messages_not_flagged(self):
        from app.services.scanner_engine import run_guard_scan
        flagged, results, violations = _run(run_guard_scan([]))
        assert flagged is False

    def test_user_only_messages(self):
        from app.services.scanner_engine import run_guard_scan
        flagged, results, violations = _run(run_guard_scan([{"role": "user", "content": "hello"}]))
        assert flagged is False

    def test_user_and_assistant_messages(self):
        from app.services.scanner_engine import run_guard_scan
        flagged, results, violations = _run(run_guard_scan([
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]))
        assert flagged is False


class TestReloadScanners:
    def test_reload_invalidates_cache(self):
        from app.services.scanner_engine import reload_scanners, _result_cache_put, _result_cache_get
        _result_cache_put("test_key", "test_value")
        reload_scanners()
        assert _result_cache_get("test_key") is None


class TestWarmup:
    def setup_method(self):
        from app.services.scanner_engine import invalidate_cache
        invalidate_cache()

    def test_warmup_completes_with_disabled_tiers(self):
        from app.services.scanner_engine import warmup
        _run(warmup())

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
