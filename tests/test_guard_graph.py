"""Tests for guard pipeline graph — graph construction and routing."""
import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

_run = lambda coro: asyncio.run(coro)


class TestBuildGuardGraph:
    def test_graph_compiles(self):
        from app.services.graph import build_guard_graph
        graph = build_guard_graph()
        assert graph is not None

    def test_get_guard_graph_is_cached(self):
        from app.services.graph import get_guard_graph, invalidate_guard_graph
        invalidate_guard_graph()
        g1 = get_guard_graph()
        g2 = get_guard_graph()
        assert g1 is g2
        invalidate_guard_graph()

    def test_invalidate_forces_rebuild(self):
        from app.services.graph import get_guard_graph, invalidate_guard_graph
        invalidate_guard_graph()
        g1 = get_guard_graph()
        invalidate_guard_graph()
        g2 = get_guard_graph()
        assert g1 is not g2
        invalidate_guard_graph()


class TestGuardGraphRouting:
    """Test that the graph routes correctly based on node outcomes."""

    def setup_method(self):
        from app.services.scanner_engine import invalidate_cache
        invalidate_cache()

    @dataclass
    class NemoPass:
        passed: bool = True
        risk_score: float = 0.0
        latency_ms: float = 5.0
        detail: str = "PASS"
        matched_flow: str = "PASS"

    @dataclass
    class NemoBlock:
        passed: bool = False
        risk_score: float = 1.0
        latency_ms: float = 5.0
        detail: str = "BLOCKED: No matching flow"
        matched_flow: str = None

    @dataclass
    class JudgePass:
        passed: bool = True
        risk_score: float = 0.1
        reasoning: str = "benign"
        threats: list = field(default_factory=list)
        latency_ms: float = 100.0

    @dataclass
    class JudgeBlock:
        passed: bool = False
        risk_score: float = 0.9
        reasoning: str = "injection"
        threats: list = field(default_factory=lambda: ["prompt_injection"])
        latency_ms: float = 100.0

    def test_nemo_block_skips_judge(self):
        """When NeMo blocks, the judge node must not run."""
        from app.services.scanner_engine import run_input_scan, invalidate_cache
        invalidate_cache()

        mock_nemo = MagicMock()
        mock_nemo.evaluate = AsyncMock(return_value=self.NemoBlock())
        mock_judge = MagicMock()
        mock_judge.evaluate = AsyncMock(return_value=self.JudgePass())
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True

        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            with patch("app.services.scanner_engine._get_judge", return_value=mock_judge):
                with patch("app.services.scanner_engine.get_config", return_value=mock_config):
                    state = _run(run_input_scan("bad input"))

        assert state["blocked"] is True
        assert "NeMoGuardrails" in state["violations"]
        # Judge should not have been called because NeMo blocked
        mock_judge.evaluate.assert_not_called()
        invalidate_cache()

    def test_nemo_pass_then_judge_evaluates(self):
        """When NeMo passes, the judge node must run."""
        from app.services.scanner_engine import run_input_scan, invalidate_cache
        invalidate_cache()

        mock_nemo = MagicMock()
        mock_nemo.evaluate = AsyncMock(return_value=self.NemoPass())
        mock_judge = MagicMock()
        mock_judge.evaluate = AsyncMock(return_value=self.JudgePass())
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True

        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            with patch("app.services.scanner_engine._get_judge", return_value=mock_judge):
                with patch("app.services.scanner_engine.get_config", return_value=mock_config):
                    state = _run(run_input_scan("safe input"))

        assert state["blocked"] is False
        mock_judge.evaluate.assert_called_once()
        invalidate_cache()

    def test_both_pass_results_in_unblocked_state(self):
        """Full pass-through: NeMo pass + judge pass → not blocked."""
        from app.services.scanner_engine import run_input_scan, invalidate_cache
        invalidate_cache()

        mock_nemo = MagicMock()
        mock_nemo.evaluate = AsyncMock(return_value=self.NemoPass())
        mock_judge = MagicMock()
        mock_judge.evaluate = AsyncMock(return_value=self.JudgePass())
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True

        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            with patch("app.services.scanner_engine._get_judge", return_value=mock_judge):
                with patch("app.services.scanner_engine.get_config", return_value=mock_config):
                    state = _run(run_input_scan("What is 2 + 2?"))

        assert state["blocked"] is False
        assert state["violations"] == []
        assert "NeMoGuardrails" in state["scanner_results"]
        assert "LLMJudge" in state["scanner_results"]
        invalidate_cache()

    def test_judge_block_after_nemo_pass(self):
        """NeMo passes but judge blocks → overall blocked."""
        from app.services.scanner_engine import run_input_scan, invalidate_cache
        invalidate_cache()

        mock_nemo = MagicMock()
        mock_nemo.evaluate = AsyncMock(return_value=self.NemoPass())
        mock_judge = MagicMock()
        mock_judge.evaluate = AsyncMock(return_value=self.JudgeBlock())
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True

        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            with patch("app.services.scanner_engine._get_judge", return_value=mock_judge):
                with patch("app.services.scanner_engine.get_config", return_value=mock_config):
                    state = _run(run_input_scan("subtle attack"))

        assert state["blocked"] is True
        assert "LLMJudge" in state["violations"]
        assert "NeMoGuardrails" not in state["violations"]
        invalidate_cache()

    def test_output_scan_routes_correctly(self):
        """Output scans use evaluate_output on the NeMo tier."""
        from app.services.scanner_engine import run_output_scan, invalidate_cache
        invalidate_cache()

        mock_nemo = MagicMock()
        mock_nemo.evaluate_output = AsyncMock(return_value=self.NemoPass())
        mock_judge = MagicMock()
        mock_judge.evaluate = AsyncMock(return_value=self.JudgePass())
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True

        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            with patch("app.services.scanner_engine._get_judge", return_value=mock_judge):
                with patch("app.services.scanner_engine.get_config", return_value=mock_config):
                    state = _run(run_output_scan("user prompt", "assistant response"))

        assert state["blocked"] is False
        assert state["direction"] == "output"
        assert state["prompt_context"] == "user prompt"
        mock_nemo.evaluate_output.assert_called_once()
        invalidate_cache()

    def test_result_cached_on_second_call(self):
        """Identical inputs return cached GuardState without re-running nodes."""
        from app.services.scanner_engine import run_input_scan, invalidate_cache
        invalidate_cache()

        mock_nemo = MagicMock()
        mock_nemo.evaluate = AsyncMock(return_value=self.NemoPass())
        mock_config = MagicMock()
        mock_config.judge.enabled = False

        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            with patch("app.services.scanner_engine.get_config", return_value=mock_config):
                _run(run_input_scan("cached text"))
                _run(run_input_scan("cached text"))

        # NeMo should only have been called once (second call hit cache)
        assert mock_nemo.evaluate.call_count == 1
        invalidate_cache()
