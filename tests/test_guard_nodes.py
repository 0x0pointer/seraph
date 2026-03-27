"""Tests for guard pipeline nodes — nemo_node and judge_node."""
import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.state import GuardState

_run = lambda coro: asyncio.run(coro)


def _make_state(**overrides) -> GuardState:
    base: GuardState = {
        "raw_text": "test input",
        "direction": "input",
        "prompt_context": "",
        "scanner_results": {},
        "violations": [],
        "on_fail_actions": {},
        "sanitized_text": "test input",
        "blocked": False,
        "block_reason": None,
        "nemo_risk_score": 0.0,
    }
    base.update(overrides)
    return base


# ── nemo_node tests ──────────────────────────────────────────────────────────

class TestNemoNode:
    @dataclass
    class PassResult:
        passed: bool = True
        matched_flow: str = "PASS"
        risk_score: float = 0.0
        latency_ms: float = 5.0
        detail: str = "PASS"

    @dataclass
    class BlockResult:
        passed: bool = False
        matched_flow: str = None
        risk_score: float = 1.0
        latency_ms: float = 5.0
        detail: str = "BLOCKED: No matching flow"

    def test_nemo_disabled_returns_zero_score(self):
        from app.services.nodes.nemo import nemo_node
        state = _make_state()
        with patch("app.services.scanner_engine._get_nemo_tier", return_value=None):
            result = _run(nemo_node(state))
        assert result == {"nemo_risk_score": 0.0}

    def test_nemo_pass_updates_score(self):
        from app.services.nodes.nemo import nemo_node
        mock_nemo = MagicMock()
        mock_nemo.evaluate = AsyncMock(return_value=self.PassResult())
        state = _make_state()
        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            result = _run(nemo_node(state))
        assert result["nemo_risk_score"] == 0.0
        assert result["scanner_results"]["NeMoGuardrails"] == 0.0
        assert "blocked" not in result or result.get("blocked") is False

    def test_nemo_block_sets_blocked_true(self):
        from app.services.nodes.nemo import nemo_node
        mock_nemo = MagicMock()
        mock_nemo.evaluate = AsyncMock(return_value=self.BlockResult())
        state = _make_state()
        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            result = _run(nemo_node(state))
        assert result["blocked"] is True
        assert "NeMoGuardrails" in result["violations"]
        assert result["on_fail_actions"]["NeMoGuardrails"] == "blocked"
        assert result["nemo_risk_score"] == 1.0

    def test_nemo_exception_sets_blocked_true(self):
        from app.services.nodes.nemo import nemo_node
        mock_nemo = MagicMock()
        mock_nemo.evaluate = AsyncMock(side_effect=RuntimeError("nemo crashed"))
        state = _make_state()
        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            result = _run(nemo_node(state))
        assert result["blocked"] is True
        assert result["scanner_results"]["NeMoGuardrails"] == 1.0

    def test_nemo_output_direction_calls_evaluate_output(self):
        from app.services.nodes.nemo import nemo_node
        mock_nemo = MagicMock()
        mock_nemo.evaluate_output = AsyncMock(return_value=self.PassResult())
        state = _make_state(direction="output", prompt_context="user asked", raw_text="response")
        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            _run(nemo_node(state))
        mock_nemo.evaluate_output.assert_called_once_with("user asked", "response")
        mock_nemo.evaluate.assert_not_called()

    def test_nemo_preserves_existing_scanner_results(self):
        from app.services.nodes.nemo import nemo_node
        mock_nemo = MagicMock()
        mock_nemo.evaluate = AsyncMock(return_value=self.PassResult())
        state = _make_state(scanner_results={"SomeOtherScanner": 0.3})
        with patch("app.services.scanner_engine._get_nemo_tier", return_value=mock_nemo):
            result = _run(nemo_node(state))
        assert "SomeOtherScanner" in result["scanner_results"]
        assert "NeMoGuardrails" in result["scanner_results"]


# ── judge_node tests ─────────────────────────────────────────────────────────

class TestJudgeNode:
    @dataclass
    class PassJudgeResult:
        passed: bool = True
        risk_score: float = 0.1
        reasoning: str = "benign"
        threats: list = field(default_factory=list)
        latency_ms: float = 100.0

    @dataclass
    class BlockJudgeResult:
        passed: bool = False
        risk_score: float = 0.9
        reasoning: str = "injection detected"
        threats: list = field(default_factory=lambda: ["prompt_injection"])
        latency_ms: float = 100.0

    def test_skips_when_judge_disabled(self):
        from app.services.nodes.judge import judge_node
        mock_config = MagicMock()
        mock_config.judge.enabled = False
        state = _make_state()
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            result = _run(judge_node(state))
        assert result == {}

    def test_skips_when_score_outside_band(self):
        from app.services.nodes.judge import judge_node
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = False
        mock_config.judge.uncertainty_band_low = 0.70
        mock_config.judge.uncertainty_band_high = 0.85
        state = _make_state(nemo_risk_score=0.3)
        with patch("app.services.scanner_engine.get_config", return_value=mock_config):
            result = _run(judge_node(state))
        assert result == {}

    def test_judge_pass_updates_score(self):
        from app.services.nodes.judge import judge_node
        mock_judge = MagicMock()
        mock_judge.evaluate = AsyncMock(return_value=self.PassJudgeResult())
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True
        state = _make_state()
        with patch("app.services.scanner_engine._get_judge", return_value=mock_judge):
            with patch("app.services.scanner_engine.get_config", return_value=mock_config):
                result = _run(judge_node(state))
        assert result["scanner_results"]["LLMJudge"] == 0.1
        assert "blocked" not in result or not result.get("blocked")

    def test_judge_block_sets_blocked_true(self):
        from app.services.nodes.judge import judge_node
        mock_judge = MagicMock()
        mock_judge.evaluate = AsyncMock(return_value=self.BlockJudgeResult())
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True
        state = _make_state()
        with patch("app.services.scanner_engine._get_judge", return_value=mock_judge):
            with patch("app.services.scanner_engine.get_config", return_value=mock_config):
                result = _run(judge_node(state))
        assert result["blocked"] is True
        assert "LLMJudge" in result["violations"]
        assert result["scanner_results"]["LLMJudge"] == 0.9

    def test_judge_exception_sets_blocked_true(self):
        from app.services.nodes.judge import judge_node
        mock_judge = MagicMock()
        mock_judge.evaluate = AsyncMock(side_effect=RuntimeError("judge crashed"))
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True
        state = _make_state()
        with patch("app.services.scanner_engine._get_judge", return_value=mock_judge):
            with patch("app.services.scanner_engine.get_config", return_value=mock_config):
                result = _run(judge_node(state))
        assert result["blocked"] is True
        assert result["scanner_results"]["LLMJudge"] == 1.0

    def test_judge_skips_when_no_judge_instance(self):
        from app.services.nodes.judge import judge_node
        mock_config = MagicMock()
        mock_config.judge.enabled = True
        mock_config.judge.run_on_every_request = True
        state = _make_state()
        with patch("app.services.scanner_engine._get_judge", return_value=None):
            with patch("app.services.scanner_engine.get_config", return_value=mock_config):
                result = _run(judge_node(state))
        assert result == {}
