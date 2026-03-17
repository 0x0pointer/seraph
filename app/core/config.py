"""
YAML-based configuration for Seraph guardrail proxy.

Reads from the path in SERAPH_CONFIG env var (default: config.yaml).
Supports hot-reload via SIGHUP or POST /reload.
"""
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_CONFIG_PATH_ENV = "SERAPH_CONFIG"
_DEFAULT_CONFIG_PATH = "config.yaml"


class LoggingConfig(BaseModel):
    level: str = "info"
    audit: bool = True
    audit_file: str | None = None  # None = stdout JSON, path = SQLite


class ScannerConfig(BaseModel):
    type: str
    threshold: float | None = None
    params: dict[str, Any] = {}
    on_fail: str = "block"  # block | fix | monitor | reask


class ScannersConfig(BaseModel):
    input: list[ScannerConfig] = []
    output: list[ScannerConfig] = []


class Config(BaseModel):
    listen: str = "0.0.0.0:8000"
    upstream: str = ""
    api_keys: list[str] = []
    logging: LoggingConfig = LoggingConfig()
    scanners: ScannersConfig | None = None  # None = use guardrail_catalog defaults


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
    logger.info("Loaded config from %s", path)
    return _config


def reload_config() -> Config:
    """Reload config from the same path (for SIGHUP / /reload)."""
    path = os.environ.get(_CONFIG_PATH_ENV, _DEFAULT_CONFIG_PATH)
    config = load_config(path)
    logger.info("Config reloaded from %s", path)
    return config
