"""
Scanner engine — public API over the guard LangGraph pipeline.

Thin orchestration layer that:
  - manages NeMo and judge singletons
  - maintains an LRU result cache
  - exposes run_input_scan / run_output_scan returning GuardState
  - exposes run_guard_scan for conversation-level scanning

The actual scan logic lives in app/services/graph.py and the nodes under
app/services/nodes/.  This file is intentionally kept small: it only handles
lifecycle (init, cache, reload, warmup) and builds the initial GuardState.
"""
from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict

from app.core.config import get_config
from app.services.state import GuardState

logger = logging.getLogger(__name__)

# ── Module-level singletons ───────────────────────────────────────────────────

_nemo_tier = None
_judge = None

# LRU result cache — avoids re-running scans on identical inputs.
_RESULT_CACHE_SIZE = 1000
_result_cache: OrderedDict = OrderedDict()


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _result_cache_key(direction: str, text: str) -> str:
    raw = f"{direction}:{text}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _result_cache_get(key: str):
    if key in _result_cache:
        _result_cache.move_to_end(key)
        return _result_cache[key]
    return None


def _result_cache_put(key: str, value) -> None:
    _result_cache[key] = value
    _result_cache.move_to_end(key)
    if len(_result_cache) > _RESULT_CACHE_SIZE:
        _result_cache.popitem(last=False)


def invalidate_cache() -> None:
    global _nemo_tier, _judge
    _result_cache.clear()
    _nemo_tier = None
    _judge = None
    from app.services.graph import invalidate_guard_graph
    invalidate_guard_graph()


# ── Tier singletons ───────────────────────────────────────────────────────────

def _get_nemo_tier():
    """Lazily initialize the NeMo Guardrails tier."""
    global _nemo_tier
    if _nemo_tier is not None:
        return _nemo_tier

    config = get_config()
    if not config.nemo_tier.enabled:
        return None

    from app.services.nemo_tier import NemoTier
    _nemo_tier = NemoTier(
        config_dir=config.nemo_tier.config_dir,
        embedding_threshold=config.nemo_tier.embedding_threshold,
        model=config.nemo_tier.model,
        model_engine=config.nemo_tier.model_engine,
        api_key=config.nemo_tier.api_key or config.upstream_api_key or None,
    )
    logger.info("NeMo tier initialized (model=%s, threshold=%.2f)",
                config.nemo_tier.model, config.nemo_tier.embedding_threshold)
    return _nemo_tier


def _get_judge():
    """Lazily initialize the LangGraph judge."""
    global _judge
    if _judge is not None:
        return _judge

    config = get_config()
    if not config.judge.enabled:
        return None

    from app.services.langgraph_judge import LangGraphJudge
    _judge = LangGraphJudge(
        model=config.judge.model,
        base_url=config.judge.base_url,
        api_key=config.judge.api_key or config.upstream_api_key or None,
        temperature=config.judge.temperature,
        max_tokens=config.judge.max_tokens,
        risk_threshold=config.judge.risk_threshold,
        prompt_file=config.judge.prompt_file,
    )
    logger.info("LangGraph judge initialized (model=%s, threshold=%.2f)",
                config.judge.model, config.judge.risk_threshold)
    return _judge


def _should_run_judge(nemo_risk_score: float) -> bool:
    """Determine if Tier 2 judge should run based on config and NeMo score."""
    config = get_config()
    if not config.judge.enabled:
        return False
    if config.judge.run_on_every_request:
        return True
    return config.judge.uncertainty_band_low <= nemo_risk_score <= config.judge.uncertainty_band_high


# ── Initial state builder ─────────────────────────────────────────────────────

def _build_initial_state(
    text: str,
    direction: str,
    prompt_context: str = "",
) -> GuardState:
    """Build a clean GuardState to feed into the guard graph."""
    return GuardState(
        raw_text=text,
        direction=direction,
        prompt_context=prompt_context,
        scanner_results={},
        violations=[],
        on_fail_actions={},
        sanitized_text=text,
        blocked=False,
        block_reason=None,
        nemo_risk_score=0.0,
    )


# ── Public API ────────────────────────────────────────────────────────────────

async def run_input_scan(text: str) -> GuardState:
    """Run the guard pipeline on user input. Returns a GuardState."""
    cache_key = _result_cache_key("input", text)
    cached = _result_cache_get(cache_key)
    if cached is not None:
        return cached

    from app.services.graph import get_guard_graph
    state = await get_guard_graph().ainvoke(_build_initial_state(text, "input"))
    _result_cache_put(cache_key, state)
    return state


async def run_output_scan(prompt: str, output: str) -> GuardState:
    """Run the guard pipeline on LLM output. Returns a GuardState."""
    cache_key = _result_cache_key("output", f"{prompt}\x00{output}")
    cached = _result_cache_get(cache_key)
    if cached is not None:
        return cached

    from app.services.graph import get_guard_graph
    state = await get_guard_graph().ainvoke(
        _build_initial_state(output, "output", prompt_context=prompt)
    )
    _result_cache_put(cache_key, state)
    return state


async def run_guard_scan(
    messages: list[dict],
) -> tuple[bool, dict[str, float], list[str]]:
    """Run guard scan on a conversation (input + output)."""
    user_text = "\n".join(m["content"] for m in messages if m["role"] == "user")
    assistant_text = "\n".join(m["content"] for m in messages if m["role"] == "assistant")

    merged_results: dict[str, float] = {}
    merged_violations: list[str] = []

    if user_text.strip():
        state = await run_input_scan(user_text)
        merged_results.update(state["scanner_results"])
        merged_violations.extend(state["violations"])

    if assistant_text.strip():
        state = await run_output_scan(user_text or "", assistant_text)
        for k, v in state["scanner_results"].items():
            key = f"{k} (output)" if k in merged_results else k
            merged_results[key] = v
        for v in state["violations"]:
            name = f"{v} (output)" if v in merged_violations else v
            if name not in merged_violations:
                merged_violations.append(name)

    return len(merged_violations) > 0, merged_results, merged_violations


def reload_scanners() -> None:
    """Reload tiers (call after config reload)."""
    invalidate_cache()
    logger.info("Scanner cache invalidated — tiers will be reloaded on next scan")


async def warmup() -> None:
    """Pre-load all tier components."""
    nemo = _get_nemo_tier()
    if nemo is not None:
        try:
            await nemo.warmup()
        except Exception as e:
            logger.warning("NeMo tier warm-up failed: %s", e)

    judge = _get_judge()
    if judge is not None:
        logger.info("LangGraph judge initialized during warm-up")

    _result_cache.clear()
    logger.info("Scanner engine warm-up complete")
