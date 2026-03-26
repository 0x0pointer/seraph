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

First-party scanners (EmbeddingShield, CustomRule):
  Run in parallel with Tier 1 for fast, deterministic checks.

Text canonicalization:
  Before first-party scanning, the engine produces a canonical form of the
  input (homoglyphs resolved, leetspeak reversed, etc.). First-party
  rule-based scanners run on the canonical text for evasion resistance.
"""

import asyncio
import hashlib
import logging
from collections import OrderedDict
from typing import Any

from app.core.config import get_config, ScannerConfig
from app.services.text_canonicalizer import canonicalize

logger = logging.getLogger(__name__)

# ── Module-level singletons for tiers ────────────────────────────────────────

_nemo_tier = None  # Lazy init: NemoTier instance
_judge = None      # Lazy init: LangGraphJudge instance

# Scanner types that benefit from text canonicalization.
_CANONICAL_SCANNERS = {"CustomRule"}

# Cache: direction -> list of (scanner_instance, scanner_name, custom_phrases, index, scanner_params, on_fail_action)
_cache: dict[str, list[tuple[Any, str, list[str], int, dict, str]]] = {}
_cache_valid: set[str] = set()

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
    global _cache_valid, _nemo_tier, _judge
    _cache_valid.clear()
    _cache.clear()
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


# ── First-party scanner loading ──────────────────────────────────────────────

# Keys consumed by the engine, never forwarded to scanner constructors.
_META_PARAMS = {"custom_blocked_phrases", "_description"}


def _import_custom_scanner(direction: str, params: dict) -> Any:
    """Instantiate the first-party CustomRuleScanner."""
    from app.services.custom_scanner import CustomRuleScanner
    return CustomRuleScanner(direction=direction, **params)


def _import_embedding_shield(params: dict) -> Any:
    """Instantiate the first-party EmbeddingShield scanner."""
    from app.services.embedding_shield import EmbeddingShield
    return EmbeddingShield(**params)


def _build_scanner(scanner_type: str, direction: str, params: dict) -> Any:
    """Instantiate a first-party scanner by type."""
    if scanner_type == "CustomRule":
        return _import_custom_scanner(direction, params)
    if scanner_type == "EmbeddingShield":
        return _import_embedding_shield(params)
    raise ValueError(f"Unknown first-party scanner type: {scanner_type}")


def _prepare_scanner_params(sc: ScannerConfig) -> tuple[dict, list[str], str]:
    """Extract clean params, custom phrases, and on_fail from a ScannerConfig."""
    raw_params = dict(sc.params)
    if sc.threshold is not None and "threshold" not in raw_params:
        raw_params["threshold"] = sc.threshold
    custom_phrases = [
        str(p).strip()
        for p in raw_params.pop("custom_blocked_phrases", [])
        if str(p).strip()
    ]
    scanner_params = {k: v for k, v in raw_params.items() if k not in _META_PARAMS}
    return scanner_params, custom_phrases, sc.on_fail


def _load_first_party_scanners(
    direction: str,
) -> list[tuple[Any, str, list[str], int, dict, str]]:
    """
    Load first-party scanners (EmbeddingShield, CustomRule) from YAML config.
    Returns list of (scanner_instance, scanner_name, custom_blocked_phrases,
                     index, scanner_params, on_fail_action).
    """
    if direction in _cache_valid and direction in _cache:
        return _cache[direction]

    config = get_config()

    scanner_configs: list[ScannerConfig] = []
    if config.scanners is not None:
        scanner_configs = (
            config.scanners.input if direction == "input" else config.scanners.output
        )

    entries: list[tuple[Any, str, list[str], int, dict, str]] = []
    for idx, sc in enumerate(scanner_configs):
        scanner_params, custom_phrases, on_fail_action = _prepare_scanner_params(sc)
        try:
            scanner = _build_scanner(sc.type, direction, scanner_params)
            entries.append((scanner, sc.type, custom_phrases, idx, scanner_params, on_fail_action))
            logger.info("Loaded first-party scanner: %s (direction=%s, on_fail=%s)",
                        sc.type, direction, on_fail_action)
        except Exception as e:
            logger.warning("Skipping scanner %s: %s", sc.type, e)

    _cache[direction] = entries
    _cache_valid.add(direction)
    return entries


# ── First-party scanner execution ────────────────────────────────────────────

def _run_one_scanner(scanner: Any, text: str, output: str = "") -> tuple[str, bool, float]:
    """Run a single first-party scanner (sync, called in thread pool or directly)."""
    return scanner.scan(text, output) if output else scanner.scan(text)


async def _run_first_party_scanners(
    text: str, canonical_text: str, direction: str, prompt: str = "",
) -> tuple[bool, str, dict[str, float], list[str], dict[str, str], list[str], bool]:
    """
    Run all first-party scanners and return aggregated results.
    Returns the same shape as the 7-tuple but scoped to first-party scanners.
    """
    entries = _load_first_party_scanners(direction)
    if not entries:
        return True, text, {}, [], {}, [], False

    has_canonical = canonical_text != text

    results_valid: dict[str, bool] = {}
    results_score: dict[str, float] = {}
    scanner_sanitized: dict[str, tuple[str, str]] = {}

    loop = asyncio.get_event_loop()
    tasks = []
    for e in entries:
        scanner, scanner_name = e[0], e[1]
        scan_text = canonical_text if has_canonical and scanner_name in _CANONICAL_SCANNERS else text
        if direction == "output" and prompt:
            tasks.append(loop.run_in_executor(None, _run_one_scanner, scanner, scan_text, prompt))
        else:
            tasks.append(loop.run_in_executor(None, _run_one_scanner, scanner, scan_text))

    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, res in enumerate(raw_results):
        scanner_name = entries[i][1]
        on_fail_action = entries[i][5]
        if isinstance(res, Exception):
            logger.warning("First-party scanner %s failed: %s", scanner_name, res)
            continue
        sanitized, is_valid, risk_score = res
        results_valid[scanner_name] = is_valid
        results_score[scanner_name] = risk_score
        if not is_valid:
            scanner_sanitized[scanner_name] = (sanitized, on_fail_action)

    overall_valid, violation_scanners, on_fail_actions, reask_msgs, fix_applied, current_text = (
        _process_fp_violations(results_valid, results_score, entries, text, scanner_sanitized)
    )

    # Custom phrase checking
    phrase_hit = _apply_custom_phrases(text, entries, results_score, violation_scanners)
    if has_canonical and not phrase_hit:
        phrase_hit = _apply_custom_phrases(canonical_text, entries, results_score, violation_scanners)
    if phrase_hit:
        overall_valid = False

    return overall_valid, current_text, results_score, violation_scanners, on_fail_actions, reask_msgs, fix_applied


# ── Shared helpers ───────────────────────────────────────────────────────────

def _process_fp_violations(
    results_valid: dict[str, bool],
    results_score: dict[str, float],
    entries: list[tuple[Any, str, list[str], int, dict, str]],
    text: str,
    scanner_sanitized: dict[str, tuple[str, str]],
) -> tuple[bool, list[str], dict[str, str], list[str], bool, str]:
    """
    Process first-party scanner violations into aggregated results.
    Returns (overall_valid, violation_scanners, on_fail_actions, reask_msgs, fix_applied, current_text).
    """
    overall_valid = True
    violation_scanners: list[str] = []
    on_fail_actions: dict[str, str] = {}
    reask_msgs: list[str] = []
    fix_applied = False
    current_text = text

    for scanner_name, is_valid_flag in results_valid.items():
        if is_valid_flag:
            continue
        action = _find_action_for_scanner(entries, scanner_name)
        score = results_score.get(scanner_name, 1.0)

        should_block, fixed_text, label, reask_msg = _handle_violation_action(
            action, scanner_name, score, text, scanner_sanitized,
        )

        on_fail_actions[scanner_name] = label
        if should_block:
            overall_valid = False
            violation_scanners.append(scanner_name)
        if fixed_text is not None:
            current_text = fixed_text
            fix_applied = True
        if reask_msg:
            reask_msgs.append(reask_msg)

    return overall_valid, violation_scanners, on_fail_actions, reask_msgs, fix_applied, current_text


def _apply_custom_phrases(
    text: str,
    entries: list[tuple[Any, str, list[str], int, dict, str]],
    results_score: dict,
    violation_scanners: list,
) -> bool:
    """Check custom_blocked_phrases. Returns True if any phrase matched."""
    text_lower = text.lower()
    matched = False
    for _, scanner_name, custom_phrases, _, _, _ in entries:
        for phrase in custom_phrases:
            if phrase.lower() in text_lower:
                matched = True
                key = f"{scanner_name} (keyword)"
                results_score[key] = 1.0
                if key not in violation_scanners:
                    violation_scanners.append(key)
                logger.warning(
                    "Custom blocked phrase matched: scanner=%s phrase=%s",
                    scanner_name, phrase,
                )
    return matched


def _build_reask_message(scanner_name: str, score: float) -> str:
    return (
        f"Your response was flagged by the '{scanner_name}' guardrail "
        f"(confidence: {score:.0%}). Please revise your message to comply with the policy."
    )


def _find_action_for_scanner(entries: list, scanner_name: str) -> str:
    for e in entries:
        if e[1] == scanner_name:
            return e[5]
    return "block"


def _handle_violation_action(
    action: str,
    scanner_name: str,
    score: float,
    original_text: str,
    scanner_sanitized: dict[str, tuple[str, str]],
) -> tuple[bool, str | None, str, str | None]:
    """
    Process a single scanner violation.
    Returns (should_block, fixed_text_or_None, action_label, reask_msg_or_None).
    """
    if action == "monitor":
        logger.info("Scanner %s: violation monitored (score=%.3f)", scanner_name, score)
        return False, None, "monitored", None

    if action == "fix":
        san_info = scanner_sanitized.get(scanner_name)
        if san_info and san_info[0] != original_text:
            logger.info("Scanner %s: violation fixed via sanitization (score=%.3f)", scanner_name, score)
            return False, san_info[0], "fixed", None
        logger.warning("Scanner %s: fix action but no sanitized text — blocked (score=%.3f)", scanner_name, score)
        return True, None, "blocked", None

    if action == "reask":
        return True, None, "reask", _build_reask_message(scanner_name, score)

    return True, None, "blocked", None


def _should_run_judge(nemo_risk_score: float) -> bool:
    """Determine if Tier 2 judge should run based on config and NeMo result."""
    config = get_config()
    if not config.judge.enabled:
        return False
    if config.judge.run_on_every_request:
        return True
    # Run only when NeMo is uncertain (score in uncertainty band)
    return config.judge.uncertainty_band_low <= nemo_risk_score <= config.judge.uncertainty_band_high


# ── Tier result helpers ──────────────────────────────────────────────────────

def _unpack_nemo_result(gathered: list, nemo: Any) -> tuple[bool, float]:
    """Unpack NeMo tier result from gathered async results.
    Returns (nemo_passed, nemo_risk_score)."""
    if nemo is None or len(gathered) <= 1:
        return True, 0.0
    nemo_result = gathered[1]
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
    if not _should_run_judge(nemo_risk_score):
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
        logger.debug(
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


def _merge_guard_results(
    gathered: list,
    coros: list[tuple[str, Any]],
) -> tuple[dict[str, float], list[str]]:
    """Merge results from input and output scans into combined dicts."""
    merged_results: dict[str, float] = {}
    merged_violations: list[str] = []
    for i, (label, _) in enumerate(coros):
        _, _, results, violations, *_ = gathered[i]
        suffix = "output" if label == "output" else ""
        for k, v in results.items():
            key = f"{k} ({suffix})" if suffix and k in merged_results else k
            merged_results[key] = v
        for v in violations:
            name = f"{v} ({suffix})" if suffix and v in merged_violations else v
            if name not in merged_violations:
                merged_violations.append(name)
    return merged_results, merged_violations


# ── Public API ───────────────────────────────────────────────────────────────

async def run_input_scan(
    text: str,
) -> tuple[bool, str, dict, list, dict, list[str] | None, bool]:
    """
    Run the two-tier scanning pipeline on user input.

    Returns:
        (is_valid, sanitized_text, scanner_results, violation_scanners,
         on_fail_actions, reask_context, fix_applied)
    """
    # Check result cache
    cache_key = _result_cache_key("input", text)
    cached = _result_cache_get(cache_key)
    if cached is not None:
        return cached

    # Canonicalize for first-party scanners
    canonical_text = canonicalize(text)

    # ── Concurrent: first-party scanners + NeMo Tier 1 ──────────────────────
    nemo = _get_nemo_tier()
    tasks = [_run_first_party_scanners(text, canonical_text, "input")]
    if nemo is not None:
        tasks.append(nemo.evaluate(text))

    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    # Unpack first-party results
    fp_result = gathered[0]
    if isinstance(fp_result, Exception):
        logger.error("First-party scanners failed: %s", fp_result)
        fp_valid, fp_text, fp_scores, fp_violations, fp_actions, fp_reask, fp_fix = (
            True, text, {}, [], {}, [], False
        )
    else:
        fp_valid, fp_text, fp_scores, fp_violations, fp_actions, fp_reask, fp_fix = fp_result

    # Unpack NeMo result
    nemo_passed, nemo_risk_score = _unpack_nemo_result(gathered, nemo)

    # Merge results
    results_score = dict(fp_scores)
    violation_scanners = list(fp_violations)
    on_fail_actions = dict(fp_actions)
    reask_msgs = list(fp_reask)
    fix_applied = fp_fix
    current_text = fp_text
    overall_valid = fp_valid

    if not nemo_passed:
        results_score["NeMoGuardrails"] = nemo_risk_score
        violation_scanners.append("NeMoGuardrails")
        on_fail_actions["NeMoGuardrails"] = "blocked"
        overall_valid = False

    # Short-circuit: if already blocked, skip Tier 2
    if not overall_valid:
        reask_context = reask_msgs if reask_msgs else None
        result = (False, current_text, results_score, violation_scanners,
                  on_fail_actions, reask_context, fix_applied)
        _result_cache_put(cache_key, result)
        return result

    # ── Tier 2: LLM-as-a-Judge ──────────────────────────────────────────────
    judge_blocked = await _run_judge_tier(
        text, "input", nemo_risk_score, results_score, violation_scanners, on_fail_actions,
    )
    if judge_blocked:
        overall_valid = False

    reask_context = reask_msgs if reask_msgs else None
    result = (overall_valid, current_text, results_score, violation_scanners,
              on_fail_actions, reask_context, fix_applied)
    _result_cache_put(cache_key, result)
    return result


async def run_output_scan(
    prompt: str,
    output: str,
) -> tuple[bool, str, dict, list, dict, list[str] | None, bool]:
    """
    Run the two-tier scanning pipeline on LLM output.

    Returns:
        (is_valid, sanitized_text, scanner_results, violation_scanners,
         on_fail_actions, reask_context, fix_applied)
    """
    cache_key = _result_cache_key("output", f"{prompt}\x00{output}")
    cached = _result_cache_get(cache_key)
    if cached is not None:
        return cached

    canonical_output = canonicalize(output)

    # ── Concurrent: first-party scanners + NeMo Tier 1 ──────────────────────
    nemo = _get_nemo_tier()
    tasks = [_run_first_party_scanners(output, canonical_output, "output", prompt=prompt)]
    if nemo is not None:
        tasks.append(nemo.evaluate_output(prompt, output))

    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    fp_result = gathered[0]
    if isinstance(fp_result, Exception):
        logger.error("First-party output scanners failed: %s", fp_result)
        fp_valid, fp_text, fp_scores, fp_violations, fp_actions, fp_reask, fp_fix = (
            True, output, {}, [], {}, [], False
        )
    else:
        fp_valid, fp_text, fp_scores, fp_violations, fp_actions, fp_reask, fp_fix = fp_result

    nemo_passed, nemo_risk_score = _unpack_nemo_result(gathered, nemo)

    results_score = dict(fp_scores)
    violation_scanners = list(fp_violations)
    on_fail_actions = dict(fp_actions)
    reask_msgs = list(fp_reask)
    fix_applied = fp_fix
    current_text = fp_text
    overall_valid = fp_valid

    if not nemo_passed:
        results_score["NeMoGuardrails"] = nemo_risk_score
        violation_scanners.append("NeMoGuardrails")
        on_fail_actions["NeMoGuardrails"] = "blocked"
        overall_valid = False

    if not overall_valid:
        reask_context = reask_msgs if reask_msgs else None
        result = (False, current_text, results_score, violation_scanners,
                  on_fail_actions, reask_context, fix_applied)
        _result_cache_put(cache_key, result)
        return result

    # ── Tier 2: LLM-as-a-Judge ──────────────────────────────────────────────
    judge_blocked = await _run_judge_tier(
        output, "output", nemo_risk_score, results_score, violation_scanners, on_fail_actions,
        prompt_context=prompt,
    )
    if judge_blocked:
        overall_valid = False

    reask_context = reask_msgs if reask_msgs else None
    result = (overall_valid, current_text, results_score, violation_scanners,
              on_fail_actions, reask_context, fix_applied)
    _result_cache_put(cache_key, result)
    return result


async def run_guard_scan(
    messages: list[dict],
) -> tuple[bool, dict[str, float], list[str]]:
    """Run guard scan on a conversation (input + output + indirect injection)."""
    user_text = "\n".join(m["content"] for m in messages if m["role"] == "user")
    assistant_text = "\n".join(m["content"] for m in messages if m["role"] == "assistant")

    coros = []
    if user_text.strip():
        coros.append(("input", run_input_scan(user_text)))
    if assistant_text.strip():
        coros.append(("output", run_output_scan(user_text or "", assistant_text)))

    gathered = await asyncio.gather(*(c for _, c in coros))
    merged_results, merged_violations = _merge_guard_results(gathered, coros)

    return len(merged_violations) > 0, merged_results, merged_violations


def reload_scanners() -> None:
    """Reload scanners and tiers (call after config reload)."""
    invalidate_cache()
    logger.info("Scanner cache invalidated — tiers and scanners will be reloaded on next scan")


async def warmup() -> None:
    """Pre-load all tier components by running dummy scans."""
    # Warm up first-party scanners
    dummy = "warmup check"
    try:
        entries = _load_first_party_scanners("input")
        if entries:
            logger.info("First-party input scanners loaded: %d",  len(entries))
        entries = _load_first_party_scanners("output")
        if entries:
            logger.info("First-party output scanners loaded: %d", len(entries))
    except Exception as e:
        logger.warning("First-party scanner warm-up failed: %s", e)

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
