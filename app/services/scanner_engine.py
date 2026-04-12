"""
Scanner engine — two-tier architecture: NeMo Guardrails + LLM-as-a-Judge.

Tier 1 (NeMo Guardrails):
  Semantic allow-list firewall. User input is matched against Colang flow
  definitions via embedding similarity. If no allowed flow matches, the
  request is blocked immediately.

Tier 2 (LLM-as-a-Judge via LangGraph):
  A small language model evaluates requests that pass Tier 1 for deeper
  threats: prompt injection, data exfiltration, social engineering, etc.
  Configurable to run on every request or only when Tier 1 is uncertain.
"""

import asyncio
import hashlib
import logging
from collections import OrderedDict
from typing import Any

from app.core.config import get_config

logger = logging.getLogger(__name__)

# ── Module-level singletons for tiers ────────────────────────────────────────

_nemo_tier = None  # Lazy init: NemoTier instance
_judge = None      # Lazy init: LangGraphJudge instance

# LRU result cache — avoids re-running scans on identical inputs.
_RESULT_CACHE_SIZE = 1000
_result_cache: OrderedDict = OrderedDict()


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


# ── Tier singletons ──────────────────────────────────────────────────────────

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
        base_url=config.nemo_tier.base_url,
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
    # Local models (Ollama/vLLM) don't need a real key, but ChatOpenAI requires one
    api_key = config.judge.api_key or config.upstream_api_key or None
    if not api_key and config.judge.base_url:
        api_key = "ollama"
    _judge = LangGraphJudge(
        model=config.judge.model,
        base_url=config.judge.base_url,
        api_key=api_key,
        temperature=config.judge.temperature,
        max_tokens=config.judge.max_tokens,
        risk_threshold=config.judge.risk_threshold,
        prompt_file=config.judge.prompt_file,
    )
    logger.info("LangGraph judge initialized (model=%s, threshold=%.2f)",
                config.judge.model, config.judge.risk_threshold)
    return _judge


# ── Tier helpers ─────────────────────────────────────────────────────────────

def _should_run_judge(nemo_risk_score: float, direction: str = "input") -> bool:
    """Determine if Tier 2 judge should run based on config and NeMo result."""
    config = get_config()
    if not config.judge.enabled:
        return False
    if direction == "input" and not config.judge.scan_input:
        return False
    if direction == "output" and not config.judge.scan_output:
        return False
    if config.judge.run_on_every_request:
        return True
    # Run only when NeMo is uncertain (score in uncertainty band)
    return config.judge.uncertainty_band_low <= nemo_risk_score <= config.judge.uncertainty_band_high


def _unpack_nemo_result(nemo_result) -> tuple[bool, float]:
    """Unpack NeMo tier result. Returns (nemo_passed, nemo_risk_score)."""
    if nemo_result is None:
        return True, 0.0
    if isinstance(nemo_result, Exception):
        logger.error("NeMo tier failed: %s", nemo_result)
        return False, 1.0
    return nemo_result.passed, nemo_result.risk_score


async def _run_judge_tier(
    text: str,
    direction: str,
    nemo_risk_score: float,
    results_score: dict[str, float],
    violation_scanners: list[str],
    on_fail_actions: dict[str, str],
    prompt_context: str | None = None,
) -> bool:
    """Run Tier 2 LLM-as-a-Judge if applicable. Returns True if judge blocked."""
    if not _should_run_judge(nemo_risk_score, direction):
        return False
    judge = _get_judge()
    if judge is None:
        return False
    try:
        judge_result = await judge.evaluate(text, direction=direction, prompt_context=prompt_context)
        results_score["LLMJudge"] = judge_result.risk_score
        if not judge_result.passed:
            violation_scanners.append("LLMJudge")
            on_fail_actions["LLMJudge"] = "blocked"
            logger.warning(
                "LLM Judge blocked %s: score=%.3f, threats=%s",
                direction, judge_result.risk_score, judge_result.threats,
            )
            return True
        logger.info(
            "LLM Judge passed %s: score=%.3f, reasoning=%s",
            direction, judge_result.risk_score, judge_result.reasoning,
        )
    except Exception as e:
        logger.error("LLM Judge (%s) failed: %s", direction, e)
        results_score["LLMJudge"] = 1.0
        violation_scanners.append("LLMJudge")
        on_fail_actions["LLMJudge"] = "blocked"
        return True
    return False


def _build_scan_result(
    overall_valid: bool, current_text: str, results_score: dict,
    violation_scanners: list, on_fail_actions: dict,
) -> tuple[bool, str, dict, list, dict, list[str] | None, bool]:
    """Build the 7-tuple scan result."""
    return (overall_valid, current_text, results_score, violation_scanners,
            on_fail_actions, None, False)


# ── Two-tier scan pipeline ───────────────────────────────────────────────────

async def _run_two_tier_scan(
    text: str, direction: str, nemo_result,
    prompt_context: str | None = None,
) -> tuple[bool, str, dict, list, dict, list[str] | None, bool]:
    """Two-tier pipeline: NeMo Guardrails then LLM-as-a-Judge."""
    nemo_passed, nemo_risk_score = _unpack_nemo_result(nemo_result)

    results_score: dict[str, float] = {}
    violation_scanners: list[str] = []
    on_fail_actions: dict[str, str] = {}

    if not nemo_passed:
        results_score["NeMoGuardrails"] = nemo_risk_score
        violation_scanners.append("NeMoGuardrails")
        on_fail_actions["NeMoGuardrails"] = "blocked"
        return _build_scan_result(False, text, results_score, violation_scanners, on_fail_actions)

    judge_blocked = await _run_judge_tier(
        text, direction, nemo_risk_score, results_score, violation_scanners, on_fail_actions,
        prompt_context=prompt_context,
    )

    overall_valid = not judge_blocked
    return _build_scan_result(overall_valid, text, results_score, violation_scanners, on_fail_actions)


# ── Public API ───────────────────────────────────────────────────────────────

async def run_input_scan(
    text: str,
) -> tuple[bool, str, dict, list, dict, list[str] | None, bool]:
    """Run the two-tier scanning pipeline on user input."""
    cache_key = _result_cache_key("input", text)
    cached = _result_cache_get(cache_key)
    if cached is not None:
        return cached

    config = get_config()
    nemo_result = None
    if config.nemo_tier.scan_input:
        nemo = _get_nemo_tier()
        if nemo is not None:
            nemo_result = await asyncio.gather(nemo.evaluate(text), return_exceptions=True)
            nemo_result = nemo_result[0]

    result = await _run_two_tier_scan(text, "input", nemo_result)
    _result_cache_put(cache_key, result)
    return result


async def run_output_scan(
    prompt: str,
    output: str,
) -> tuple[bool, str, dict, list, dict, list[str] | None, bool]:
    """Run the two-tier scanning pipeline on LLM output."""
    cache_key = _result_cache_key("output", f"{prompt}\x00{output}")
    cached = _result_cache_get(cache_key)
    if cached is not None:
        return cached

    config = get_config()
    nemo_result = None
    if config.nemo_tier.scan_output:
        nemo = _get_nemo_tier()
        if nemo is not None:
            nemo_result = await asyncio.gather(nemo.evaluate_output(prompt, output), return_exceptions=True)
            nemo_result = nemo_result[0]

    result = await _run_two_tier_scan(output, "output", nemo_result, prompt_context=prompt)
    _result_cache_put(cache_key, result)
    return result


async def run_guard_scan(
    messages: list[dict],
) -> tuple[bool, dict[str, float], list[str]]:
    """Run guard scan on a conversation (input + output)."""
    user_text = "\n".join(m["content"] for m in messages if m["role"] == "user")
    assistant_text = "\n".join(m["content"] for m in messages if m["role"] == "assistant")

    merged_results: dict[str, float] = {}
    merged_violations: list[str] = []

    if user_text.strip():
        _, _, scores, violations, *_ = await run_input_scan(user_text)
        merged_results.update(scores)
        merged_violations.extend(violations)

    if assistant_text.strip():
        _, _, scores, violations, *_ = await run_output_scan(user_text or "", assistant_text)
        for k, v in scores.items():
            key = f"{k} (output)" if k in merged_results else k
            merged_results[key] = v
        for v in violations:
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
    # Warm up NeMo tier
    nemo = _get_nemo_tier()
    if nemo is not None:
        try:
            await nemo.warmup()
        except Exception as e:
            logger.warning("NeMo tier warm-up failed: %s", e)

    # Warm up LangGraph judge (just initialize, no dummy call needed)
    judge = _get_judge()
    if judge is not None:
        logger.info("LangGraph judge initialized during warm-up")

    # Clear warmup results from cache
    _result_cache.clear()
    logger.info("Scanner engine warm-up complete")
