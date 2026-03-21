"""
Scanner engine — dynamically loads and runs llm-guard scanners from YAML config.

llm-guard API:
  scan_prompt(scanners, prompt) -> (sanitized_prompt, results_valid, results_score)
  scan_output(scanners, prompt, output) -> (sanitized_output, results_valid, results_score)

  results_valid: dict[str, bool]  — True = valid, False = violation
  results_score: dict[str, float] — 0.0 = no risk, 1.0 = high risk

Custom meta-params (stripped before passing to llm-guard):
  custom_blocked_phrases: list[str] — exact substrings that always trigger a block,
                                       checked case-insensitively after the main scan.

Parallel execution:
  Each scanner is run in its own thread via run_in_executor so ML models execute
  concurrently instead of sequentially.  This cuts wall-clock time from the sum of
  all model latencies to roughly the latency of the slowest single model.

Text canonicalization (v17):
  Before scanning, the engine produces a canonical form of the input text
  (homoglyphs resolved, leetspeak reversed, spaced-out letters collapsed, etc.).
  Rule-based scanners (BanSubstrings, Regex) run on the CANONICAL text so that
  evasion techniques like Cyrillic substitution or leetspeak are neutralized.
  ML-based scanners run on the ORIGINAL text for best classification accuracy.
"""
import asyncio
import concurrent.futures
import hashlib
import importlib
import logging
import re
from collections import OrderedDict
from typing import Any

from app.core.config import get_config, ScannerConfig
from app.services.text_canonicalizer import canonicalize

logger = logging.getLogger(__name__)

# Scanner types that benefit from text canonicalization.
_CANONICAL_SCANNERS = {"BanSubstrings", "Regex"}

# Shared thread-pool for blocking scanner inference.
_executor: concurrent.futures.ThreadPoolExecutor | None = None


def _get_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Lazily create the thread pool so it's not spawned on import."""
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor()
    return _executor

# Keys consumed by the engine, never forwarded to llm-guard scanner constructors.
_META_PARAMS = {"custom_blocked_phrases", "_description"}

# Cache: direction -> list of (scanner_instance, scanner_name, custom_phrases, index, scanner_params, on_fail_action)
_cache: dict[str, list[tuple[Any, str, list[str], int, dict, str]]] = {}
_cache_valid: set[str] = set()

# LRU result cache — avoids re-running ML inference on identical inputs.
_RESULT_CACHE_SIZE = 1000
_result_cache: OrderedDict = OrderedDict()


def _result_cache_key(direction: str, entries: list, text: str) -> str:
    ids = ",".join(f"{e[3]}:{e[5]}" for e in entries)
    raw = f"{direction}:{ids}:{text}"
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
    global _cache_valid
    _cache_valid.clear()
    _cache.clear()
    _result_cache.clear()


def _import_scanner(scanner_type: str, direction: str, params: dict) -> Any:
    """Dynamically import and instantiate a scanner from llm-guard."""
    module_name = f"llm_guard.{'input' if direction == 'input' else 'output'}_scanners"
    try:
        module = importlib.import_module(module_name)
        scanner_class = getattr(module, scanner_type)
        return scanner_class(**params)
    except (ImportError, AttributeError, TypeError) as e:
        logger.error(f"Failed to load scanner {scanner_type} from {module_name}: {e}")
        raise


def _import_custom_scanner(direction: str, params: dict) -> Any:
    """Instantiate the first-party CustomRuleScanner."""
    from app.services.custom_scanner import CustomRuleScanner
    return CustomRuleScanner(direction=direction, **params)


def _import_embedding_shield(params: dict) -> Any:
    """Instantiate the first-party EmbeddingShield scanner."""
    from app.services.embedding_shield import EmbeddingShield
    return EmbeddingShield(**params)


def _import_information_shield(params: dict) -> Any:
    """Instantiate the first-party InformationShield output scanner."""
    from app.services.information_shield import InformationShield
    return InformationShield(**params)


def _import_allowed_topics_shield(params: dict) -> Any:
    """Instantiate the first-party AllowedTopicsShield input scanner."""
    from app.services.allowed_topics_shield import AllowedTopicsShield
    return AllowedTopicsShield(**params)


# Exact language names accepted by the llm-guard Code scanner.
_LANG_MATHEMATICA = "Mathematica/Wolfram Language"
_LANG_VB_NET = "Visual Basic .NET"

_CODE_SCANNER_LANGUAGES = [
    "ARM Assembly", "AppleScript", "C", "C#", "C++", "COBOL", "Erlang", "Fortran",
    "Go", "Java", "JavaScript", "Kotlin", "Lua", _LANG_MATHEMATICA,
    "PHP", "Pascal", "Perl", "PowerShell", "Python", "R", "Ruby", "Rust", "Scala",
    "Swift", _LANG_VB_NET, "jq",
]
_LANG_NORMALIZE: dict[str, str] = {l.lower(): l for l in _CODE_SCANNER_LANGUAGES}
_LANG_NORMALIZE.update({
    "js": "JavaScript",
    "ts": "JavaScript",
    "typescript": "JavaScript",
    "bash": "PowerShell",
    "shell": "PowerShell",
    "sh": "PowerShell",
    "csharp": "C#",
    "cpp": "C++",
    "vb.net": _LANG_VB_NET,
    "vb": _LANG_VB_NET,
    "wolfram": _LANG_MATHEMATICA,
    "mathematica": _LANG_MATHEMATICA,
})


def _normalize_languages(languages: list) -> list[str]:
    """Normalize user-entered language names to exact llm-guard names."""
    result = []
    for lang in languages:
        if not lang:
            continue
        normalized = _LANG_NORMALIZE.get(lang.strip().lower(), lang.strip())
        if normalized not in result:
            result.append(normalized)
    return result


_MARKDOWN_CODE_FENCE_RE = re.compile(r"```[\w]*\n.+?```", re.DOTALL)


class BanCode:
    """
    Wraps llm_guard's BanCode output scanner to correctly detect markdown-fenced code.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def scan(self, prompt: str, output: str) -> tuple[str, bool, float]:
        if _MARKDOWN_CODE_FENCE_RE.search(output):
            logger.warning("BanCode: markdown code fence detected in output — blocked")
            return output, False, 1.0
        return self._inner.scan(prompt, output)


def _build_scanner(scanner_type: str, direction: str, params: dict) -> Any:
    """
    Instantiate a scanner, with smart routing for BanCode.
    """
    if scanner_type == "CustomRule":
        return _import_custom_scanner(direction, params)

    if scanner_type == "EmbeddingShield":
        return _import_embedding_shield(params)

    if scanner_type == "InformationShield":
        return _import_information_shield(params)

    if scanner_type == "AllowedTopicsShield":
        return _import_allowed_topics_shield(params)

    if scanner_type == "BanCode":
        languages = params.get("languages")
        if languages:
            normalized = _normalize_languages(languages)
            if not normalized:
                clean = {k: v for k, v in params.items() if k not in ("languages", "is_blocked")}
                return _import_scanner("BanCode", direction, clean)
            code_params = {
                "languages": normalized,
                "is_blocked": True,
                "threshold": params.get("threshold", 0.4),
            }
            logger.info(f"BanCode with languages={normalized} → routing to Code scanner")
            return _import_scanner("Code", direction, code_params)
        clean = {k: v for k, v in params.items() if k not in ("languages", "is_blocked")}
        scanner = _import_scanner("BanCode", direction, clean)
        if direction == "output":
            return BanCode(scanner)
        return scanner

    return _import_scanner(scanner_type, direction, params)


def _scanner_configs_from_catalog(direction: str, include_disabled: bool = False) -> list:
    """Build ScannerConfig list from the guardrail_catalog defaults.

    If include_disabled=True, loads ALL scanners (for adaptive deep scanning).
    """
    from app.core.guardrail_catalog import GUARDRAIL_CATALOG
    return [
        ScannerConfig(
            type=e["scanner_type"],
            threshold=e.get("params", {}).get("threshold"),
            params=e.get("params", {}),
            on_fail=e.get("on_fail_action", "block"),
        )
        for e in GUARDRAIL_CATALOG
        if e["direction"] == direction and (include_disabled or e.get("is_active", False))
    ]


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


def _load_scanners_from_config(
    direction: str,
    include_disabled: bool = False,
) -> list[tuple[Any, str, list[str], int, dict, str]]:
    """
    Load scanners from YAML config (or guardrail_catalog defaults).
    Returns list of (scanner_instance, scanner_name, custom_blocked_phrases, index, scanner_params, on_fail_action).
    """
    global _cache_valid

    cache_key_dir = f"{direction}:{'all' if include_disabled else 'active'}"
    if cache_key_dir in _cache_valid and cache_key_dir in _cache:
        return _cache[cache_key_dir]

    config = get_config()

    if config.scanners is not None:
        scanner_configs: list[ScannerConfig] = (
            config.scanners.input if direction == "input" else config.scanners.output
        )
    else:
        scanner_configs = _scanner_configs_from_catalog(direction, include_disabled=include_disabled)

    # Inject AllowedTopicsShield for input direction if configured
    if direction == "input" and hasattr(config, "allowed_topics_shield"):
        ats = config.allowed_topics_shield
        if ats and ats.enabled and ats.topics:
            scanner_configs.append(ScannerConfig(
                type="AllowedTopicsShield",
                params={
                    "allowed_topics": ats.topics,
                    "threshold": ats.threshold,
                    "fallback_message": ats.fallback_message,
                },
                on_fail="block",
            ))

    # Apply per-scanner on_fail overrides from config.
    # Supports: "Regex" (both), "input.Regex" (input only), "output.Regex" (output only).
    overrides = config.on_fail_overrides

    entries: list[tuple[Any, str, list[str], int, dict, str]] = []
    for idx, sc in enumerate(scanner_configs):
        scanner_params, custom_phrases, on_fail_action = _prepare_scanner_params(sc)
        direction_key = f"{direction}.{sc.type}"
        if direction_key in overrides:
            on_fail_action = overrides[direction_key]
        elif sc.type in overrides:
            on_fail_action = overrides[sc.type]
        try:
            scanner = _build_scanner(sc.type, direction, scanner_params)
            entries.append((scanner, sc.type, custom_phrases, idx, scanner_params, on_fail_action))
            logger.info(f"Loaded scanner: {sc.type} (index={idx}, on_fail={on_fail_action})")
        except Exception as e:
            logger.warning(f"Skipping scanner {sc.type}: {e}")

    _cache[cache_key_dir] = entries
    _cache_valid.add(cache_key_dir)

    return entries


def _apply_custom_phrases(
    text: str,
    entries: list[tuple[Any, str, list[str], int, dict, str]],
    results_score: dict,
    violation_scanners: list,
) -> bool:
    """
    Check custom_blocked_phrases for every scanner entry.
    Returns True if any phrase matched.
    """
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


def _scan_one_input(scanner: Any, text: str) -> tuple[str, dict, dict]:
    """Run a single input scanner synchronously (called in thread pool)."""
    from llm_guard.evaluate import scan_prompt
    sanitized, valid_dict, score_dict = scan_prompt([scanner], text)
    return sanitized, valid_dict, score_dict


def _scan_one_output(scanner: Any, prompt: str, output: str) -> tuple[str, dict, dict]:
    """Run a single output scanner synchronously (called in thread pool)."""
    from llm_guard.evaluate import scan_output
    sanitized, valid_dict, score_dict = scan_output([scanner], prompt, output)
    return sanitized, valid_dict, score_dict


def _build_reask_message(scanner_name: str, score: float) -> str:
    """Build a human-readable correction instruction for a failed scanner."""
    return (
        f"Your response was flagged by the '{scanner_name}' guardrail "
        f"(confidence: {score:.0%}). Please revise your message to comply with the policy."
    )


def _find_action_for_scanner(entries: list, scanner_name: str) -> str:
    """Look up the on_fail_action for a scanner by name."""
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
    Process a single scanner violation based on its on_fail_action.
    Returns (should_block, fixed_text_or_None, action_label, reask_msg_or_None).
    """
    if action == "monitor":
        logger.info("Scanner %s: violation monitored (score=%.3f, action=monitor)", scanner_name, score)
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

    # Default: block
    return True, None, "blocked", None


def _process_violations(
    results_valid: dict[str, bool],
    results_score: dict[str, float],
    entries: list,
    scanner_sanitized: dict[str, tuple[str, str]],
    original_text: str,
) -> tuple[bool, str, list[str], dict[str, str], list[str], bool]:
    """
    Process all scanner violations and apply on_fail_action logic.
    Returns (overall_valid, current_text, violation_scanners,
             on_fail_actions, reask_msgs, fix_applied).
    """
    overall_valid = True
    violation_scanners: list[str] = []
    on_fail_actions: dict[str, str] = {}
    reask_msgs: list[str] = []
    fix_applied = False
    current_text = original_text

    for scanner_name, is_valid_flag in results_valid.items():
        if is_valid_flag:
            continue
        action = _find_action_for_scanner(entries, scanner_name)
        score = results_score.get(scanner_name, 1.0)

        should_block, fixed_text, label, reask_msg = _handle_violation_action(
            action, scanner_name, score, original_text, scanner_sanitized,
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

    return overall_valid, current_text, violation_scanners, on_fail_actions, reask_msgs, fix_applied


def _load_and_filter_entries(
    entries: list,
    allowed_types: set[str] | None,
) -> list:
    """Filter scanner entries by allowed types."""
    if allowed_types is not None:
        return [e for e in entries if e[1] in allowed_types]
    return entries


def _collect_raw_results(
    raw_results: list,
    entries: list,
) -> tuple[dict[str, bool], dict[str, float], dict[str, tuple[str, str]]]:
    """Collect raw scanner results into aggregated dicts."""
    results_valid: dict[str, bool] = {}
    results_score: dict[str, float] = {}
    scanner_sanitized: dict[str, tuple[str, str]] = {}

    for i, res in enumerate(raw_results):
        if isinstance(res, Exception):
            logger.warning("Scanner %s failed: %s", entries[i][1], res)
            continue
        sanitized, valid_dict, score_dict = res
        scanner_name = entries[i][1]
        on_fail_action = entries[i][5]
        results_valid.update(valid_dict)
        results_score.update(score_dict)
        if not all(valid_dict.values()):
            scanner_sanitized[scanner_name] = (sanitized, on_fail_action)

    return results_valid, results_score, scanner_sanitized


async def run_input_scan(
    text: str,
    allowed_types: set[str] | None = None,
    scan_tier: str = "standard",
) -> tuple[bool, str, dict, list, dict, list[str] | None, bool]:
    """
    Run all active input scanners in parallel threads.

    Returns:
        (is_valid, sanitized_text, scanner_results, violation_scanners,
         on_fail_actions, reask_context, fix_applied)
    """
    # For deep scan tier, load ALL scanners (including disabled ones from catalog)
    if scan_tier == "deep":
        all_entries = _load_scanners_from_config("input", include_disabled=True)
        entries = _load_and_filter_entries(all_entries, allowed_types)
    else:
        entries = _load_and_filter_entries(
            _load_scanners_from_config("input"), allowed_types)
    if not entries:
        return True, text, {}, [], {}, None, False

    canonical_text = canonicalize(text)
    _has_canonical = canonical_text != text
    if _has_canonical:
        logger.debug("Text canonicalized: original=%d chars, canonical=%d chars", len(text), len(canonical_text))

    _cache_input = f"{text}\x01{canonical_text}" if _has_canonical else text
    cache_key = _result_cache_key("input", entries, _cache_input)
    cached = _result_cache_get(cache_key)
    if cached is not None:
        return cached

    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(
            _get_executor(), _scan_one_input, e[0],
            canonical_text if _has_canonical and e[1] in _CANONICAL_SCANNERS else text,
        )
        for e in entries
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    results_valid, results_score, scanner_sanitized = _collect_raw_results(raw_results, entries)

    overall_valid, current_text, violation_scanners, on_fail_actions, reask_msgs, fix_applied = (
        _process_violations(results_valid, results_score, entries, scanner_sanitized, text)
    )

    phrase_hit = _apply_custom_phrases(text, entries, results_score, violation_scanners)
    if _has_canonical and not phrase_hit:
        phrase_hit = _apply_custom_phrases(canonical_text, entries, results_score, violation_scanners)
    if phrase_hit:
        overall_valid = False

    reask_context = reask_msgs if reask_msgs else None
    result = (overall_valid, current_text, results_score, violation_scanners, on_fail_actions, reask_context, fix_applied)
    _result_cache_put(cache_key, result)
    return result


async def run_output_scan(
    prompt: str,
    output: str,
    allowed_types: set[str] | None = None,
    scan_tier: str = "standard",
) -> tuple[bool, str, dict, list, dict, list[str] | None, bool]:
    """
    Run all active output scanners in parallel threads.

    Returns:
        (is_valid, sanitized_text, scanner_results, violation_scanners,
         on_fail_actions, reask_context, fix_applied)
    """
    if scan_tier == "deep":
        all_entries = _load_scanners_from_config("output", include_disabled=True)
        entries = _load_and_filter_entries(all_entries, allowed_types)
    else:
        entries = _load_and_filter_entries(
            _load_scanners_from_config("output"), allowed_types)
    if not entries:
        return True, output, {}, [], {}, None, False

    canonical_output = canonicalize(output)
    _has_canonical_out = canonical_output != output
    if _has_canonical_out:
        logger.debug("Output canonicalized: original=%d chars, canonical=%d chars", len(output), len(canonical_output))

    _cache_out = f"{prompt}\x00{output}\x01{canonical_output}" if _has_canonical_out else f"{prompt}\x00{output}"
    cache_key = _result_cache_key("output", entries, _cache_out)
    cached = _result_cache_get(cache_key)
    if cached is not None:
        return cached

    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(
            _get_executor(), _scan_one_output, e[0], prompt,
            canonical_output if _has_canonical_out and e[1] in _CANONICAL_SCANNERS else output,
        )
        for e in entries
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    results_valid, results_score, scanner_sanitized = _collect_raw_results(raw_results, entries)

    overall_valid, current_text, violation_scanners, on_fail_actions, reask_msgs, fix_applied = (
        _process_violations(results_valid, results_score, entries, scanner_sanitized, output)
    )

    phrase_hit = _apply_custom_phrases(output, entries, results_score, violation_scanners)
    if _has_canonical_out and not phrase_hit:
        phrase_hit = _apply_custom_phrases(canonical_output, entries, results_score, violation_scanners)
    if phrase_hit:
        overall_valid = False

    reask_context = reask_msgs if reask_msgs else None
    result = (overall_valid, current_text, results_score, violation_scanners, on_fail_actions, reask_context, fix_applied)
    _result_cache_put(cache_key, result)
    return result


def _merge_scan_results(
    merged_results: dict[str, float],
    merged_violations: list[str],
    results: dict[str, float],
    violations: list[str],
    suffix: str = "",
) -> None:
    """Merge scan results/violations into the running totals, with optional namespace suffix."""
    for k, v in results.items():
        key = f"{k} ({suffix})" if suffix and k in merged_results else k
        merged_results[key] = v
    for v in violations:
        name = f"{v} ({suffix})" if suffix and v in merged_violations else v
        if name not in merged_violations:
            merged_violations.append(name)


async def run_guard_scan(
    messages: list[dict],
    allowed_input_types: set[str] | None = None,
    allowed_output_types: set[str] | None = None,
) -> tuple[bool, dict[str, float], list[str]]:
    user_text      = "\n".join(m["content"] for m in messages if m["role"] == "user")
    assistant_text = "\n".join(m["content"] for m in messages if m["role"] == "assistant")
    full_convo     = "\n".join(f"[{m['role'].upper()}]: {m['content']}" for m in messages)

    merged_results: dict[str, float] = {}
    merged_violations: list[str] = []

    coros = []
    if user_text.strip():
        coros.append(("input", run_input_scan(user_text, allowed_types=allowed_input_types)))
    if assistant_text.strip():
        coros.append(("output", run_output_scan(user_text or "", assistant_text, allowed_types=allowed_output_types)))

    gathered = await asyncio.gather(*(c for _, c in coros))
    for i, (label, _) in enumerate(coros):
        _, _, results, violations, *_ = gathered[i]
        suffix = "output" if label == "output" else ""
        _merge_scan_results(merged_results, merged_violations, results, violations, suffix)

    # Pass 3 — full conversation through PromptInjection only (indirect injection)
    if full_convo.strip():
        _, _, r3, v3, *_ = await run_input_scan(full_convo, allowed_types={"PromptInjection"})
        _merge_scan_results(merged_results, merged_violations, r3, v3, "indirect")

    return len(merged_violations) > 0, merged_results, merged_violations


def reload_scanners() -> None:
    """Reload scanners (call after config reload)."""
    invalidate_cache()
    logger.info("Scanner cache invalidated — scanners will be reloaded on next scan")


async def warmup() -> None:
    """
    Pre-load all active scanner models by running a short dummy scan.
    """
    dummy = "warmup check"
    try:
        await run_input_scan(dummy)
        logger.info("Scanner warm-up: input scanners ready.")
    except Exception as e:
        logger.warning("Scanner warm-up (input) failed: %s", e)
    try:
        await run_output_scan(dummy, dummy)
        logger.info("Scanner warm-up: output scanners ready.")
    except Exception as e:
        logger.warning("Scanner warm-up (output) failed: %s", e)
