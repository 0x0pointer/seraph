"""Unit tests for app/services/langgraph_judge.py — LLM-as-a-Judge."""
import asyncio
import json
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.langgraph_judge import LangGraphJudge, JudgeResult, JudgeState

_run = lambda coro: asyncio.run(coro)


class TestJudgeResult:
    def test_defaults(self):
        r = JudgeResult(passed=True, risk_score=0.1, reasoning="ok")
        assert r.threats == []
        assert r.latency_ms == 0.0

    def test_with_threats(self):
        r = JudgeResult(passed=False, risk_score=0.9, reasoning="bad", threats=["injection"])
        assert r.threats == ["injection"]


class TestDecideNode:
    def _make_judge(self):
        with patch("app.services.langgraph_judge.ChatOpenAI"):
            return LangGraphJudge(prompt_file="/tmp/nonexistent.txt")

    def test_pass_verdict(self):
        judge = self._make_judge()
        state = {
            "raw_response": json.dumps({
                "verdict": "pass", "risk_score": 0.1,
                "reasoning": "benign", "threats_detected": [],
            }),
            "risk_threshold": 0.7,
        }
        result = judge._decide_node(state)
        assert result["verdict"] == "pass"
        assert result["blocked"] is False
        assert result["risk_score"] == 0.1

    def test_block_by_threshold(self):
        judge = self._make_judge()
        state = {
            "raw_response": json.dumps({
                "verdict": "pass", "risk_score": 0.9,
                "reasoning": "dangerous", "threats_detected": ["injection"],
            }),
            "risk_threshold": 0.7,
        }
        result = judge._decide_node(state)
        assert result["verdict"] == "block"
        assert result["blocked"] is True

    def test_block_by_advisory_verdict(self):
        judge = self._make_judge()
        state = {
            "raw_response": json.dumps({
                "verdict": "block", "risk_score": 0.6,
                "reasoning": "suspicious", "threats_detected": ["social_engineering"],
            }),
            "risk_threshold": 0.7,
        }
        # 0.6 >= 0.7 * 0.8 = 0.56 and verdict is "block" → should block
        result = judge._decide_node(state)
        assert result["verdict"] == "block"
        assert result["blocked"] is True

    def test_advisory_block_below_band(self):
        judge = self._make_judge()
        state = {
            "raw_response": json.dumps({
                "verdict": "block", "risk_score": 0.3,
                "reasoning": "low risk", "threats_detected": [],
            }),
            "risk_threshold": 0.7,
        }
        # 0.3 < 0.7 * 0.8 = 0.56 → should pass despite advisory
        result = judge._decide_node(state)
        assert result["verdict"] == "pass"
        assert result["blocked"] is False

    def test_parse_failure_defaults_to_block(self):
        judge = self._make_judge()
        state = {
            "raw_response": "not json at all",
            "risk_threshold": 0.7,
        }
        result = judge._decide_node(state)
        assert result["verdict"] == "block"
        assert result["risk_score"] == 0.8
        assert "parse_error" in result["threats_detected"]

    def test_markdown_code_fence_stripped(self):
        judge = self._make_judge()
        inner = json.dumps({
            "verdict": "pass", "risk_score": 0.2,
            "reasoning": "ok", "threats_detected": [],
        })
        state = {
            "raw_response": f"```json\n{inner}\n```",
            "risk_threshold": 0.7,
        }
        result = judge._decide_node(state)
        assert result["verdict"] == "pass"
        assert result["risk_score"] == 0.2

    def test_empty_response(self):
        judge = self._make_judge()
        state = {"raw_response": "", "risk_threshold": 0.7}
        result = judge._decide_node(state)
        assert result["verdict"] == "block"
        assert "parse_error" in result["threats_detected"]


class TestClassifyNode:
    def _make_judge(self):
        with patch("app.services.langgraph_judge.ChatOpenAI"):
            return LangGraphJudge(prompt_file="/tmp/nonexistent.txt")

    def test_input_direction_success(self):
        judge = self._make_judge()
        mock_response = MagicMock()
        mock_response.content = '{"verdict":"pass","risk_score":0.1,"reasoning":"ok","threats_detected":[]}'

        # Mock the LLM so chain.ainvoke returns our response
        judge._llm = MagicMock()
        judge._llm.ainvoke = AsyncMock(return_value=mock_response)
        # The chain is prompt | llm, so we mock __or__ on the prompt to return a mock chain
        mock_chain = MagicMock()
        mock_chain.ainvoke = AsyncMock(return_value=mock_response)

        with patch.object(type(judge._llm), "__ror__", return_value=mock_chain):
            state = {"text": "hello", "direction": "input", "prompt_context": ""}
            result = _run(judge._classify_node(state))

        assert "raw_response" in result

    def test_exception_returns_block_json(self):
        judge = self._make_judge()

        # Directly patch _llm so that prompt | _llm raises during ainvoke
        original_llm = judge._llm
        failing_chain = MagicMock()
        failing_chain.ainvoke = AsyncMock(side_effect=RuntimeError("LLM down"))

        # Make INPUT_JUDGE_PROMPT | llm return failing_chain
        with patch("app.services.langgraph_judge.INPUT_JUDGE_PROMPT") as mock_prompt:
            mock_prompt.__or__ = MagicMock(return_value=failing_chain)
            state = {"text": "test", "direction": "input", "prompt_context": ""}
            result = _run(judge._classify_node(state))

        parsed = json.loads(result["raw_response"])
        assert parsed["verdict"] == "block"
        assert parsed["risk_score"] == 1.0
        assert "evaluation_error" in parsed["threats_detected"]

    def test_output_direction_with_context(self):
        judge = self._make_judge()
        mock_response = MagicMock()
        mock_response.content = '{"verdict":"pass","risk_score":0.05,"reasoning":"safe","threats_detected":[]}'
        mock_chain = MagicMock()
        mock_chain.ainvoke = AsyncMock(return_value=mock_response)

        with patch("app.services.langgraph_judge.OUTPUT_JUDGE_PROMPT") as mock_prompt:
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)
            state = {"text": "output text", "direction": "output", "prompt_context": "user asked something"}
            result = _run(judge._classify_node(state))

        assert "raw_response" in result
        raw = result["raw_response"]
        assert "pass" in raw


class TestEvaluate:
    def _make_judge(self):
        with patch("app.services.langgraph_judge.ChatOpenAI"):
            return LangGraphJudge(prompt_file="/tmp/nonexistent.txt")

    def test_evaluate_pass(self):
        judge = self._make_judge()
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value={
            "blocked": False, "risk_score": 0.1,
            "reasoning": "ok", "threats_detected": [],
        })
        judge._graph = mock_graph

        result = _run(judge.evaluate("hello"))
        assert result.passed is True
        assert result.risk_score == 0.1

    def test_evaluate_block(self):
        judge = self._make_judge()
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value={
            "blocked": True, "risk_score": 0.9,
            "reasoning": "dangerous", "threats_detected": ["injection"],
        })
        judge._graph = mock_graph

        result = _run(judge.evaluate("hack the system"))
        assert result.passed is False
        assert result.risk_score == 0.9
        assert "injection" in result.threats

    def test_evaluate_with_prompt_context(self):
        judge = self._make_judge()
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value={
            "blocked": False, "risk_score": 0.05,
            "reasoning": "ok", "threats_detected": [],
        })
        judge._graph = mock_graph

        result = _run(judge.evaluate("response text", direction="output", prompt_context="user asked"))
        assert result.passed is True
        call_state = mock_graph.ainvoke.call_args[0][0]
        assert call_state["direction"] == "output"
        assert call_state["prompt_context"] == "user asked"

    def test_evaluate_graph_exception(self):
        judge = self._make_judge()
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("graph failed"))
        judge._graph = mock_graph

        result = _run(judge.evaluate("test"))
        assert result.passed is False
        assert result.risk_score == 1.0
        assert "execution_error" in result.threats


class TestLoadSystemPrompt:
    def test_loads_from_file(self, tmp_path):
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("Evaluate for threats.")
        with patch("app.services.langgraph_judge.ChatOpenAI"):
            judge = LangGraphJudge(prompt_file=str(prompt_file))
        result = judge._load_system_prompt()
        assert result == "Evaluate for threats."

    def test_caches_prompt(self, tmp_path):
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("Cached prompt.")
        with patch("app.services.langgraph_judge.ChatOpenAI"):
            judge = LangGraphJudge(prompt_file=str(prompt_file))
        judge._load_system_prompt()
        prompt_file.write_text("Changed!")
        assert judge._load_system_prompt() == "Cached prompt."

    def test_uses_default_when_missing(self):
        with patch("app.services.langgraph_judge.ChatOpenAI"):
            judge = LangGraphJudge(prompt_file="/tmp/nonexistent_prompt.txt")
        result = judge._load_system_prompt()
        assert "threats" in result.lower()


class TestReload:
    def test_reload_updates_fields(self):
        with patch("app.services.langgraph_judge.ChatOpenAI"):
            judge = LangGraphJudge()
            judge.reload(model="new-model", risk_threshold=0.5, temperature=0.1)
        assert judge._model_name == "new-model"
        assert judge._risk_threshold == 0.5
        assert judge._temperature == 0.1
        assert judge._system_prompt is None  # Cleared on reload

    def test_reload_partial(self):
        with patch("app.services.langgraph_judge.ChatOpenAI"):
            judge = LangGraphJudge(model="old")
            judge.reload(base_url="http://localhost:11434/v1")
        assert judge._model_name == "old"
        assert judge._base_url == "http://localhost:11434/v1"


class TestBuildLlm:
    def test_minimal_kwargs(self):
        with patch("app.services.langgraph_judge.ChatOpenAI") as mock_cls:
            LangGraphJudge(model="gpt-4o-mini")
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert "base_url" not in call_kwargs
        assert "api_key" not in call_kwargs

    def test_with_base_url_and_api_key(self):
        with patch("app.services.langgraph_judge.ChatOpenAI") as mock_cls:
            LangGraphJudge(model="phi3", base_url="http://localhost:11434/v1", api_key="key")
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["base_url"] == "http://localhost:11434/v1"
        assert call_kwargs["api_key"] == "key"
