"""Unit tests for app/services/nemo_tier.py — NeMo Guardrails wrapper."""
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.nemo_tier import NemoTier, NemoResult, _BLOCKED_PREFIXES

_run = lambda coro: asyncio.run(coro)


class TestNemoResult:
    def test_dataclass_fields(self):
        r = NemoResult(passed=True, matched_flow="PASS", risk_score=0.0, latency_ms=5.0, detail="PASS")
        assert r.passed is True
        assert r.risk_score == 0.0

    def test_blocked_result(self):
        r = NemoResult(passed=False, matched_flow=None, risk_score=1.0, latency_ms=10.0, detail="BLOCKED: test")
        assert r.passed is False
        assert r.detail.startswith("BLOCKED:")


class TestNemoTierInit:
    def test_default_values(self):
        tier = NemoTier(config_dir="/tmp/fake")
        assert tier._embedding_threshold == 0.85
        assert tier._model == "gpt-4o-mini"
        assert tier._model_engine == "openai"
        assert tier._input_rails is None
        assert tier._output_rails is None

    def test_custom_values(self):
        tier = NemoTier(
            config_dir="/tmp/fake",
            embedding_threshold=0.90,
            model="gpt-4",
            model_engine="azure",
            api_key="sk-test",
        )
        assert tier._embedding_threshold == 0.90
        assert tier._model == "gpt-4"
        assert tier._api_key == "sk-test"


class TestEnsureApiKey:
    def test_sets_from_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        tier = NemoTier(config_dir="/tmp", api_key="sk-from-config")
        tier._ensure_api_key()
        import os
        assert os.environ.get("OPENAI_API_KEY") == "sk-from-config"
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def test_sets_from_upstream_env(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("UPSTREAM_API_KEY", "sk-from-upstream")
        tier = NemoTier(config_dir="/tmp")
        tier._ensure_api_key()
        import os
        assert os.environ.get("OPENAI_API_KEY") == "sk-from-upstream"
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("UPSTREAM_API_KEY", raising=False)


class TestParseColangIntents:
    def test_extracts_intents_with_examples(self):
        colang = """
define user ask about symptoms
    "What could be causing my headache?"
    "I have a persistent cough"

define user ask about medication
    "What are the side effects of metformin?"

define bot allow request
    "PASS"

define flow allowed symptoms
    user ask about symptoms
    bot allow request
"""
        intents = NemoTier._parse_colang_intents(colang)
        assert len(intents) == 2
        assert intents[0][0] == "ask about symptoms"
        assert len(intents[0][1]) == 2
        assert intents[1][0] == "ask about medication"
        assert len(intents[1][1]) == 1

    def test_empty_content_returns_empty(self):
        assert NemoTier._parse_colang_intents("") == []

    def test_no_intents_returns_empty(self):
        colang = "define flow test\n  bot say hello"
        assert NemoTier._parse_colang_intents(colang) == []

    def test_skips_empty_examples(self):
        colang = 'define user greet\n    "hello"\n    ""\n    "hi"'
        intents = NemoTier._parse_colang_intents(colang)
        assert len(intents) == 1
        assert len(intents[0][1]) == 2  # empty string skipped

    def test_last_intent_without_trailing_define(self):
        colang = 'define user ask question\n    "What is this?"'
        intents = NemoTier._parse_colang_intents(colang)
        assert len(intents) == 1
        assert intents[0][0] == "ask question"


class TestBuildSampleConversation:
    def test_builds_from_colang_file(self, tmp_path):
        colang = tmp_path / "input_rails.co"
        colang.write_text(
            'define user greet\n    "hello"\n\n'
            'define user ask question\n    "what is this?"\n\n'
            'define bot allow request\n    "PASS"\n'
        )
        tier = NemoTier(config_dir=str(tmp_path))
        sample = tier._build_sample_conversation("input_rails.co")
        assert 'user "hello"' in sample
        assert "greet" in sample
        assert "BLOCKED" in sample  # blocked example always added

    def test_missing_file_returns_empty(self, tmp_path):
        tier = NemoTier(config_dir=str(tmp_path))
        assert tier._build_sample_conversation("missing.co") == ""

    def test_no_intents_returns_empty(self, tmp_path):
        colang = tmp_path / "empty.co"
        colang.write_text("define flow test\n  bot say hello")
        tier = NemoTier(config_dir=str(tmp_path))
        assert tier._build_sample_conversation("empty.co") == ""

    def test_limits_to_six_intents(self, tmp_path):
        lines = []
        for i in range(10):
            lines.append(f'define user intent_{i}\n    "example {i}"')
        colang = tmp_path / "input_rails.co"
        colang.write_text("\n\n".join(lines))
        tier = NemoTier(config_dir=str(tmp_path))
        sample = tier._build_sample_conversation("input_rails.co")
        # 6 intents + 1 blocked example = 7 user lines
        user_lines = [l for l in sample.splitlines() if l.startswith('user "')]
        assert len(user_lines) == 7  # 6 + hack example


class TestBuildYamlContent:
    def test_contains_model_and_threshold(self, tmp_path):
        tier = NemoTier(config_dir=str(tmp_path), model="gpt-4o-mini", embedding_threshold=0.85)
        yaml = tier._build_yaml_content("input_rails.co")
        assert "gpt-4o-mini" in yaml
        assert "0.85" in yaml
        assert "allow_free_text: false" in yaml

    def test_includes_sample_conversation_when_colang_exists(self, tmp_path):
        colang = tmp_path / "input_rails.co"
        colang.write_text('define user greet\n    "hello"\n')
        tier = NemoTier(config_dir=str(tmp_path))
        yaml = tier._build_yaml_content("input_rails.co")
        assert "sample_conversation" in yaml
        assert "hello" in yaml

    def test_no_sample_conversation_when_no_colang(self, tmp_path):
        tier = NemoTier(config_dir=str(tmp_path))
        yaml = tier._build_yaml_content("missing.co")
        assert "sample_conversation" not in yaml


class TestLoadColang:
    def test_missing_file_returns_empty(self, tmp_path):
        tier = NemoTier(config_dir=str(tmp_path))
        result = tier._load_colang("nonexistent.co")
        assert result == ""

    def test_existing_file_returns_content(self, tmp_path):
        colang_file = tmp_path / "test.co"
        colang_file.write_text("define flow test\n  bot say hello")
        tier = NemoTier(config_dir=str(tmp_path))
        result = tier._load_colang("test.co")
        assert "define flow test" in result


class TestEvaluateRails:
    def test_pass_result(self):
        tier = NemoTier(config_dir="/tmp")
        mock_rails = MagicMock()
        mock_rails.generate_async = AsyncMock(return_value="PASS")

        result = _run(tier._evaluate_rails(mock_rails, "hello", "input"))
        assert result.passed is True
        assert result.risk_score == 0.0
        assert result.matched_flow == "PASS"

    def test_blocked_result(self):
        tier = NemoTier(config_dir="/tmp")
        mock_rails = MagicMock()
        mock_rails.generate_async = AsyncMock(return_value="BLOCKED: No matching flow")

        result = _run(tier._evaluate_rails(mock_rails, "hack this", "input"))
        assert result.passed is False
        assert result.risk_score == 1.0
        assert result.detail.startswith("BLOCKED:")

    def test_blocked_by_seraph_prefix(self):
        tier = NemoTier(config_dir="/tmp")
        mock_rails = MagicMock()
        mock_rails.generate_async = AsyncMock(
            return_value="Blocked by Seraph: No intent matched"
        )

        result = _run(tier._evaluate_rails(mock_rails, "test", "input"))
        assert result.passed is False
        assert result.risk_score == 1.0
        assert result.detail.startswith("Blocked by Seraph:")

    def test_exception_returns_block(self):
        tier = NemoTier(config_dir="/tmp")
        mock_rails = MagicMock()
        mock_rails.generate_async = AsyncMock(side_effect=RuntimeError("model failed"))

        result = _run(tier._evaluate_rails(mock_rails, "test", "input"))
        assert result.passed is False
        assert result.risk_score == 1.0
        assert "NeMo error" in result.detail

    def test_non_string_response(self):
        tier = NemoTier(config_dir="/tmp")
        mock_rails = MagicMock()
        mock_rails.generate_async = AsyncMock(return_value=12345)

        result = _run(tier._evaluate_rails(mock_rails, "test", "input"))
        assert result.passed is True
        assert result.matched_flow == "12345"


class TestEvaluate:
    def test_delegates_to_input_rails(self):
        tier = NemoTier(config_dir="/tmp")
        mock_rails = MagicMock()
        mock_rails.generate_async = AsyncMock(return_value="PASS")
        tier._input_rails = mock_rails

        result = _run(tier.evaluate("hello"))
        assert result.passed is True
        mock_rails.generate_async.assert_called_once_with(prompt="hello")


class TestEvaluateOutput:
    def test_delegates_to_output_rails(self):
        tier = NemoTier(config_dir="/tmp")
        mock_rails = MagicMock()
        mock_rails.generate_async = AsyncMock(return_value="PASS")
        tier._output_rails = mock_rails

        result = _run(tier.evaluate_output("prompt", "response"))
        assert result.passed is True
        mock_rails.generate_async.assert_called_once_with(prompt="response")


class TestReload:
    def test_reload_clears_rails(self):
        tier = NemoTier(config_dir="/tmp")
        tier._input_rails = MagicMock()
        tier._output_rails = MagicMock()

        tier.reload(config_dir="/tmp/new", embedding_threshold=0.9)
        assert tier._input_rails is None
        assert tier._output_rails is None
        assert tier._config_dir == "/tmp/new"
        assert tier._embedding_threshold == 0.9

    def test_reload_partial_update(self):
        tier = NemoTier(config_dir="/tmp", model="old-model")
        tier.reload(model="new-model")
        assert tier._model == "new-model"
        assert tier._config_dir == "/tmp"

    def test_reload_api_key(self):
        tier = NemoTier(config_dir="/tmp")
        tier.reload(api_key="new-key")
        assert tier._api_key == "new-key"


class TestWarmup:
    def test_warmup_calls_evaluate(self):
        tier = NemoTier(config_dir="/tmp")
        mock_rails = MagicMock()
        mock_rails.generate_async = AsyncMock(return_value="PASS")
        tier._input_rails = mock_rails
        tier._output_rails = mock_rails

        _run(tier.warmup())
        assert mock_rails.generate_async.call_count == 2

    def test_warmup_handles_input_failure(self):
        tier = NemoTier(config_dir="/tmp")
        mock_input = MagicMock()
        mock_input.generate_async = AsyncMock(side_effect=RuntimeError("fail"))
        mock_output = MagicMock()
        mock_output.generate_async = AsyncMock(return_value="PASS")
        tier._input_rails = mock_input
        tier._output_rails = mock_output

        _run(tier.warmup())  # Should not raise

    def test_warmup_handles_output_failure(self):
        tier = NemoTier(config_dir="/tmp")
        mock_input = MagicMock()
        mock_input.generate_async = AsyncMock(return_value="PASS")
        mock_output = MagicMock()
        mock_output.generate_async = AsyncMock(side_effect=RuntimeError("fail"))
        tier._input_rails = mock_input
        tier._output_rails = mock_output

        _run(tier.warmup())  # Should not raise
