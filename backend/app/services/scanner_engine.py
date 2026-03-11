"""
Scanner engine — dynamically loads and runs llm-guard scanners based on DB config.

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
"""
import asyncio
import concurrent.futures
import hashlib
import importlib
import logging
from collections import OrderedDict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select as _sa_select

from app.models.guardrail import GuardrailConfig
from app.services.guardrail_service import list_guardrails

logger = logging.getLogger(__name__)

# Shared thread-pool for blocking scanner inference.
# max_workers=None → Python default (min(32, cpu_count+4)).
_executor = concurrent.futures.ThreadPoolExecutor()

# Keys consumed by the engine, never forwarded to llm-guard scanner constructors.
_META_PARAMS = {"custom_blocked_phrases", "_description"}

# Cache: direction -> list of (scanner_instance, scanner_name, custom_phrases, guardrail_id, scanner_params)
_cache: dict[str, list[tuple[Any, str, list[str], int, dict]]] = {}
_cache_valid: set[str] = set()  # directions whose cache is valid

# ---------------------------------------------------------------------------
# LRU result cache — avoids re-running ML inference on identical inputs.
# Only used for global-mode scans (no per-connection overrides), keyed on
# (direction, sorted scanner IDs, text).  Max 1 000 entries.
# ---------------------------------------------------------------------------
_RESULT_CACHE_SIZE = 1000
_result_cache: OrderedDict = OrderedDict()  # key -> (is_valid, text, results, violations)


def _result_cache_key(direction: str, entries: list, text: str) -> str:
    ids = ",".join(str(e[3]) for e in entries)
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
    _cache_valid = set()
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


async def _load_scanners(
    session: AsyncSession, direction: str
) -> list[tuple[Any, str, list[str], int, dict]]:
    """Return list of (scanner_instance, scanner_name, custom_blocked_phrases, guardrail_id, scanner_params)."""
    global _cache_valid

    if direction in _cache_valid and direction in _cache:
        return _cache[direction]

    configs: list[GuardrailConfig] = await list_guardrails(session)
    active = sorted(
        [c for c in configs if c.direction == direction and c.is_active],
        key=lambda c: c.order,
    )

    entries: list[tuple[Any, str, list[str], int, dict]] = []
    for config in active:
        raw_params = dict(config.params or {})

        # Extract meta-params before passing to llm-guard
        custom_phrases: list[str] = [
            str(p).strip()
            for p in raw_params.pop("custom_blocked_phrases", [])
            if str(p).strip()
        ]
        scanner_params = {k: v for k, v in raw_params.items() if k not in _META_PARAMS}

        try:
            if config.scanner_type == "CustomRule":
                scanner = _import_custom_scanner(direction, scanner_params)
            else:
                scanner = _import_scanner(config.scanner_type, direction, scanner_params)
            entries.append((scanner, config.scanner_type, custom_phrases, config.id, scanner_params))
            logger.info(f"Loaded scanner: {config.scanner_type} (id={config.id})")
        except Exception as e:
            logger.warning(f"Skipping scanner {config.scanner_type}: {e}")

    _cache[direction] = entries
    _cache_valid.add(direction)

    return entries


async def _load_scanners_by_ids(
    session: AsyncSession, direction: str, ids: set[int]
) -> list[tuple[Any, str, list[str], int, dict]]:
    """
    Load specific scanners by guardrail ID, regardless of their global is_active status.
    Used for per-connection custom guardrails so users can override the global active set.
    Results are NOT cached — per-connection selections are too varied to cache globally.
    """
    rows = (
        await session.execute(
            _sa_select(GuardrailConfig).where(
                GuardrailConfig.id.in_(ids),
                GuardrailConfig.direction == direction,
            )
        )
    ).scalars().all()
    configs = sorted(rows, key=lambda c: c.order)

    entries: list[tuple[Any, str, list[str], int, dict]] = []
    for config in configs:
        raw_params = dict(config.params or {})
        custom_phrases: list[str] = [
            str(p).strip()
            for p in raw_params.pop("custom_blocked_phrases", [])
            if str(p).strip()
        ]
        scanner_params = {k: v for k, v in raw_params.items() if k not in _META_PARAMS}
        try:
            if config.scanner_type == "CustomRule":
                scanner = _import_custom_scanner(direction, scanner_params)
            else:
                scanner = _import_scanner(config.scanner_type, direction, scanner_params)
            entries.append((scanner, config.scanner_type, custom_phrases, config.id, scanner_params))
            logger.info(f"Loaded per-connection scanner: {config.scanner_type} (id={config.id}, active={config.is_active})")
        except Exception as e:
            logger.warning(f"Skipping per-connection scanner {config.scanner_type}: {e}")
    return entries


def _apply_custom_phrases(
    text: str,
    entries: list[tuple[Any, str, list[str]]],
    results_score: dict,
    violation_scanners: list,
) -> bool:
    """
    Check custom_blocked_phrases for every scanner entry.
    Returns True if any phrase matched (i.e. overall_valid should become False).
    """
    text_lower = text.lower()
    matched = False
    for _, scanner_name, custom_phrases, _, _ in entries:
        for phrase in custom_phrases:
            if phrase.lower() in text_lower:
                matched = True
                key = f"{scanner_name} (keyword)"
                results_score[key] = 1.0
                if key not in violation_scanners:
                    violation_scanners.append(key)
                logger.warning(
                    f"Custom blocked phrase matched",
                    scanner=scanner_name,
                    phrase=phrase,
                )
    return matched


def _scan_one_input(scanner: Any, text: str) -> tuple[dict, dict]:
    """Run a single input scanner synchronously (called in thread pool)."""
    from llm_guard.evaluate import scan_prompt
    _, valid_dict, score_dict = scan_prompt([scanner], text)
    return valid_dict, score_dict


def _scan_one_output(scanner: Any, prompt: str, output: str) -> tuple[dict, dict]:
    """Run a single output scanner synchronously (called in thread pool)."""
    from llm_guard.evaluate import scan_output
    _, valid_dict, score_dict = scan_output([scanner], prompt, output)
    return valid_dict, score_dict


def _apply_threshold_overrides(
    entries: list[tuple[Any, str, list[str], int, dict]],
    threshold_overrides: dict[int, float],
    direction: str,
) -> list[tuple[Any, str, list[str], int, dict]]:
    """Re-instantiate scanners whose guardrail_id has a threshold override."""
    result = []
    for e in entries:
        scanner, scanner_type, phrases, guardrail_id, params = e
        if guardrail_id in threshold_overrides:
            override_params = {**params, "threshold": threshold_overrides[guardrail_id]}
            try:
                new_scanner = _import_scanner(scanner_type, direction, override_params)
                result.append((new_scanner, scanner_type, phrases, guardrail_id, params))
                logger.info(f"Applied threshold override {threshold_overrides[guardrail_id]} to {scanner_type} (id={guardrail_id})")
            except Exception as ex:
                logger.warning(f"Threshold override failed for {scanner_type}: {ex}")
                result.append(e)
        else:
            result.append(e)
    return result


async def run_input_scan(
    session: AsyncSession,
    text: str,
    allowed_types: set[str] | None = None,
    allowed_guardrail_ids: set[int] | None = None,
    threshold_overrides: dict[int, float] | None = None,
) -> tuple[bool, str, dict, list]:
    """
    Run all active input scanners in parallel threads.
    If allowed_types is given, only scanners whose scanner_type is in that set are run.
    If allowed_guardrail_ids is given, only scanners whose guardrail_id is in that set are run.
    If threshold_overrides is given, those scanners are re-instantiated with the overridden threshold.
    Returns (is_valid, sanitized_text, scanner_results, violation_scanners)
    """
    use_cache = allowed_guardrail_ids is None and not threshold_overrides

    if allowed_guardrail_ids is not None:
        entries = await _load_scanners_by_ids(session, "input", allowed_guardrail_ids)
        if allowed_types is not None:
            entries = [e for e in entries if e[1] in allowed_types]
    else:
        entries = await _load_scanners(session, "input")
        if allowed_types is not None:
            entries = [e for e in entries if e[1] in allowed_types]
    if threshold_overrides:
        entries = _apply_threshold_overrides(entries, threshold_overrides, "input")
    if not entries:
        return True, text, {}, []

    # Check LRU cache (global mode only, no per-connection overrides)
    cache_key = _result_cache_key("input", entries, text) if use_cache else None
    if cache_key:
        cached = _result_cache_get(cache_key)
        if cached is not None:
            return cached

    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(_executor, _scan_one_input, e[0], text)
        for e in entries
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    results_valid: dict[str, bool] = {}
    results_score: dict[str, float] = {}
    for i, res in enumerate(raw_results):
        if isinstance(res, Exception):
            logger.warning("Scanner %s failed: %s", entries[i][1], res)
            continue
        valid_dict, score_dict = res
        results_valid.update(valid_dict)
        results_score.update(score_dict)

    overall_valid = all(results_valid.values()) if results_valid else True
    violation_scanners = [name for name, valid in results_valid.items() if not valid]

    phrase_hit = _apply_custom_phrases(text, entries, results_score, violation_scanners)
    if phrase_hit:
        overall_valid = False

    result = (overall_valid, text, results_score, violation_scanners)
    if cache_key:
        _result_cache_put(cache_key, result)
    return result


async def run_output_scan(
    session: AsyncSession,
    prompt: str,
    output: str,
    allowed_types: set[str] | None = None,
    allowed_guardrail_ids: set[int] | None = None,
    threshold_overrides: dict[int, float] | None = None,
) -> tuple[bool, str, dict, list]:
    """
    Run all active output scanners in parallel threads.
    If allowed_types is given, only scanners whose scanner_type is in that set are run.
    If allowed_guardrail_ids is given, only scanners whose guardrail_id is in that set are run.
    If threshold_overrides is given, those scanners are re-instantiated with the overridden threshold.
    Returns (is_valid, sanitized_text, scanner_results, violation_scanners)
    """
    use_cache = allowed_guardrail_ids is None and not threshold_overrides

    if allowed_guardrail_ids is not None:
        entries = await _load_scanners_by_ids(session, "output", allowed_guardrail_ids)
        if allowed_types is not None:
            entries = [e for e in entries if e[1] in allowed_types]
    else:
        entries = await _load_scanners(session, "output")
        if allowed_types is not None:
            entries = [e for e in entries if e[1] in allowed_types]
    if threshold_overrides:
        entries = _apply_threshold_overrides(entries, threshold_overrides, "output")
    if not entries:
        return True, output, {}, []

    # Check LRU cache — key includes prompt so context is preserved
    cache_key = _result_cache_key("output", entries, f"{prompt}\x00{output}") if use_cache else None
    if cache_key:
        cached = _result_cache_get(cache_key)
        if cached is not None:
            return cached

    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(_executor, _scan_one_output, e[0], prompt, output)
        for e in entries
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    results_valid: dict[str, bool] = {}
    results_score: dict[str, float] = {}
    for i, res in enumerate(raw_results):
        if isinstance(res, Exception):
            logger.warning("Scanner %s failed: %s", entries[i][1], res)
            continue
        valid_dict, score_dict = res
        results_valid.update(valid_dict)
        results_score.update(score_dict)

    overall_valid = all(results_valid.values()) if results_valid else True
    violation_scanners = [name for name, valid in results_valid.items() if not valid]

    phrase_hit = _apply_custom_phrases(output, entries, results_score, violation_scanners)
    if phrase_hit:
        overall_valid = False

    result = (overall_valid, output, results_score, violation_scanners)
    if cache_key:
        _result_cache_put(cache_key, result)
    return result


async def run_guard_scan(
    session: AsyncSession,
    messages: list[dict],   # [{"role": str, "content": str}]
    allowed_input_types: set[str] | None = None,
    allowed_output_types: set[str] | None = None,
    allowed_guardrail_ids: set[int] | None = None,
    threshold_overrides: dict[int, float] | None = None,
) -> tuple[bool, dict[str, float], list[str]]:
    user_text      = "\n".join(m["content"] for m in messages if m["role"] == "user")
    assistant_text = "\n".join(m["content"] for m in messages if m["role"] == "assistant")
    full_convo     = "\n".join(f"[{m['role'].upper()}]: {m['content']}" for m in messages)

    merged_results: dict[str, float] = {}
    merged_violations: list[str] = []

    # Passes 1 & 2 run concurrently — they are independent of each other
    run_p1 = bool(user_text.strip())
    run_p2 = bool(assistant_text.strip())

    coros = []
    if run_p1:
        coros.append(run_input_scan(
            session, user_text,
            allowed_types=allowed_input_types,
            allowed_guardrail_ids=allowed_guardrail_ids,
            threshold_overrides=threshold_overrides,
        ))
    if run_p2:
        coros.append(run_output_scan(
            session, user_text or "", assistant_text,
            allowed_types=allowed_output_types,
            allowed_guardrail_ids=allowed_guardrail_ids,
            threshold_overrides=threshold_overrides,
        ))

    gathered = await asyncio.gather(*coros)
    idx = 0

    if run_p1:
        _, _, r1, v1 = gathered[idx]; idx += 1
        merged_results.update(r1)
        for v in v1:
            if v not in merged_violations:
                merged_violations.append(v)

    if run_p2:
        _, _, r2, v2 = gathered[idx]
        for k, v in r2.items():
            key = f"{k} (output)" if k in merged_results else k
            merged_results[key] = v
        for v in v2:
            namespaced = f"{v} (output)" if v in merged_violations else v
            if namespaced not in merged_violations:
                merged_violations.append(namespaced)

    # Pass 3 — full conversation through PromptInjection only (indirect injection)
    # Runs after passes 1/2 complete so indirect score can be compared against direct score
    if full_convo.strip():
        _, _, r3, v3 = await run_input_scan(
            session, full_convo,
            allowed_types={"PromptInjection"},
            allowed_guardrail_ids=allowed_guardrail_ids,
            threshold_overrides=threshold_overrides,
        )
        for k, score in r3.items():
            key = f"{k} (indirect)"
            if key not in merged_results or score > merged_results[key]:
                merged_results[key] = score
        for v in v3:
            key = f"{v} (indirect)"
            if key not in merged_violations:
                merged_violations.append(key)

    return len(merged_violations) > 0, merged_results, merged_violations


async def warmup(session: AsyncSession) -> None:
    """
    Pre-load all active scanner models by running a short dummy scan through each direction.
    Call this at server startup so the first real request does not pay the cold-start penalty.
    """
    dummy = "warmup check"
    try:
        await run_input_scan(session, dummy)
        logger.info("Scanner warm-up: input scanners ready.")
    except Exception as e:
        logger.warning("Scanner warm-up (input) failed: %s", e)
    try:
        await run_output_scan(session, dummy, dummy)
        logger.info("Scanner warm-up: output scanners ready.")
    except Exception as e:
        logger.warning("Scanner warm-up (output) failed: %s", e)
