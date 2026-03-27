"""Unit tests for app/core/config.py — YAML config loader."""
import os
import tempfile
import pytest
from app.core.config import (
    Config,
    LoggingConfig,
    load_config,
    get_config,
    reload_config,
)


class TestConfigDefaults:
    def test_default_config_has_expected_values(self):
        cfg = Config()
        assert cfg.listen == "0.0.0.0:8000"
        assert cfg.upstream == ""
        assert cfg.api_keys == []

    def test_default_logging_config(self):
        cfg = LoggingConfig()
        assert cfg.level == "info"
        assert cfg.audit is True
        assert cfg.audit_file is None


class TestLoadConfig:
    def test_load_from_yaml_file(self, tmp_path):
        cfg_file = tmp_path / "test.yaml"
        cfg_file.write_text(
            "listen: '127.0.0.1:9000'\n"
            "upstream: 'https://example.com'\n"
            "api_keys:\n"
            "  - key1\n"
            "  - key2\n"
            "logging:\n"
            "  level: debug\n"
            "  audit: false\n"
        )
        config = load_config(str(cfg_file))
        assert config.listen == "127.0.0.1:9000"
        assert config.upstream == "https://example.com"
        assert config.api_keys == ["key1", "key2"]
        assert config.logging.level == "debug"
        assert config.logging.audit is False

    def test_load_nonexistent_file_returns_defaults(self, tmp_path):
        config = load_config(str(tmp_path / "does_not_exist.yaml"))
        assert config.listen == "0.0.0.0:8000"
        assert config.api_keys == []

    def test_load_empty_yaml_returns_defaults(self, tmp_path):
        cfg_file = tmp_path / "empty.yaml"
        cfg_file.write_text("")
        config = load_config(str(cfg_file))
        assert config.listen == "0.0.0.0:8000"

    def test_get_config_returns_singleton(self, tmp_path):
        cfg_file = tmp_path / "singleton.yaml"
        cfg_file.write_text("upstream: 'https://singleton.test'\n")
        load_config(str(cfg_file))
        assert get_config().upstream == "https://singleton.test"

    def test_load_config_uses_env_var(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "env.yaml"
        cfg_file.write_text("upstream: 'https://env.test'\n")
        monkeypatch.setenv("SERAPH_CONFIG", str(cfg_file))
        config = load_config()
        assert config.upstream == "https://env.test"


class TestReloadConfig:
    def test_reload_re_reads_file(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "reload.yaml"
        cfg_file.write_text("upstream: 'https://v1.test'\n")
        monkeypatch.setenv("SERAPH_CONFIG", str(cfg_file))

        load_config()
        assert get_config().upstream == "https://v1.test"

        cfg_file.write_text("upstream: 'https://v2.test'\n")
        reload_config()
        assert get_config().upstream == "https://v2.test"


class TestUpstreamApiKey:
    def test_upstream_api_key_from_yaml(self, tmp_path):
        cfg_file = tmp_path / "key.yaml"
        cfg_file.write_text("upstream_api_key: 'sk-from-yaml'\n")
        config = load_config(str(cfg_file))
        assert config.upstream_api_key == "sk-from-yaml"

    def test_upstream_api_key_env_overrides_yaml(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "key_env.yaml"
        cfg_file.write_text("upstream_api_key: 'sk-from-yaml'\n")
        monkeypatch.setenv("UPSTREAM_API_KEY", "sk-from-env")
        config = load_config(str(cfg_file))
        assert config.upstream_api_key == "sk-from-env"

    def test_upstream_api_key_default_empty(self):
        config = Config()
        assert config.upstream_api_key == ""

    def test_config_with_audit_file(self, tmp_path):
        cfg_file = tmp_path / "audit.yaml"
        cfg_file.write_text(
            "logging:\n"
            "  audit_file: /tmp/seraph_audit.db\n"
        )
        config = load_config(str(cfg_file))
        assert config.logging.audit_file == "/tmp/seraph_audit.db"
