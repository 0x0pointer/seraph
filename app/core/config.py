"""
YAML-based configuration for Seraph guardrail proxy.

Reads from the path in SERAPH_CONFIG env var (default: config.yaml).
Supports hot-reload via SIGHUP or POST /reload.
"""
import logging
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_CONFIG_PATH_ENV = "SERAPH_CONFIG"
_DEFAULT_CONFIG_PATH = "config.yaml"


class LoggingConfig(BaseModel):
    level: str = "info"
    audit: bool = True
    audit_file: str | None = None  # None = stdout JSON, path = SQLite


class StreamingConfig(BaseModel):
    output_scan_mode: Literal["buffer", "passthrough", "incremental"] = "buffer"
    buffer_timeout_seconds: float = 30.0


class NemoTierConfig(BaseModel):
    enabled: bool = True
    config_dir: str = "app/services/nemo_config"
    embedding_threshold: float = 0.85
    model: str = "mistral:7b-instruct"
    model_engine: str = "openai"
    base_url: str | None = "http://localhost:11434/v1"  # Ollama / vLLM endpoint
    scan_input: bool = True   # NeMo intent classification on user input
    scan_output: bool = True  # NeMo intent classification on LLM output
    api_key: str | None = None  # Falls back to upstream_api_key


class JudgeConfig(BaseModel):
    enabled: bool = True
    model: str = "mistral:7b-instruct"
    base_url: str | None = "http://localhost:11434/v1"  # Ollama / vLLM endpoint
    api_key: str | None = None  # Falls back to upstream_api_key; not needed for local Ollama
    temperature: float = 0.0
    max_tokens: int = 512
    risk_threshold: float = 0.7
    prompt_file: str = "app/services/judge_prompt.txt"
    scan_input: bool = True   # Judge evaluates user input
    scan_output: bool = True  # Judge evaluates LLM output
    run_on_every_request: bool = True
    uncertainty_band_low: float = 0.70
    uncertainty_band_high: float = 0.85


class Config(BaseModel):
    listen: str = "0.0.0.0:8000"
    upstream: str = ""
    upstream_api_key: str = ""  # LLM provider key — injected server-side, never from client
    api_keys: list[str] = []
    logging: LoggingConfig = LoggingConfig()
    nemo_tier: NemoTierConfig = NemoTierConfig()
    judge: JudgeConfig = JudgeConfig()
    streaming: StreamingConfig = StreamingConfig()


# Module-level singleton
_config: Config = Config()


def get_config() -> Config:
    return _config


def load_config(path: str | None = None) -> Config:
    """Load config from YAML file. Returns the Config and sets the module singleton."""
    global _config

    if path is None:
        path = os.environ.get(_CONFIG_PATH_ENV, _DEFAULT_CONFIG_PATH)

    config_path = Path(path)
    if not config_path.exists():
        logger.warning("Config file %s not found, using defaults", path)
        _config = Config()
        return _config

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    _config = Config(**raw)

    # Allow env var overrides (so secrets and deployment-specific values stay out of YAML)
    env_key = os.environ.get("UPSTREAM_API_KEY")
    if env_key:
        _config.upstream_api_key = env_key

    env_audit = os.environ.get("SERAPH_AUDIT_FILE")
    if env_audit:
        _config.logging.audit_file = env_audit

    env_nemo_base_url = os.environ.get("NEMO_BASE_URL")
    if env_nemo_base_url:
        _config.nemo_tier.base_url = env_nemo_base_url

    env_judge_base_url = os.environ.get("JUDGE_BASE_URL")
    if env_judge_base_url:
        _config.judge.base_url = env_judge_base_url

    logger.info("Loaded config from %s", path)
    return _config


def reload_config() -> Config:
    """Reload config from the same path (for SIGHUP / /reload)."""
    path = os.environ.get(_CONFIG_PATH_ENV, _DEFAULT_CONFIG_PATH)
    config = load_config(path)
    logger.info("Config reloaded from %s", path)
    return config
