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

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select as _sa_select

from app.models.guardrail import GuardrailConfig
from app.services.guardrail_service import list_guardrails
from app.services.text_canonicalizer import canonicalize

logger = logging.getLogger(__name__)

# Scanner types that benefit from text canonicalization.
# These are pure detection scanners (no sanitized output) that match on
# exact substrings or regex patterns — evasion via homoglyphs/leetspeak
# is neutralized by feeding them the canonical text form.
_CANONICAL_SCANNERS = {"BanSubstrings", "Regex"}

# Shared thread-pool for blocking scanner inference.
# max_workers=None → Python default (min(32, cpu_count+4)).
_executor = concurrent.futures.ThreadPoolExecutor()

# Keys consumed by the engine, never forwarded to llm-guard scanner constructors.
_META_PARAMS = {"custom_blocked_phrases", "_description"}

# Cache: direction -> list of (scanner_instance, scanner_name, custom_phrases, guardrail_id, scanner_params, on_fail_action)
_cache: dict[str, list[tuple[Any, str, list[str], int, dict, str]]] = {}
_cache_valid: set[str] = set()  # directions whose cache is valid

# ---------------------------------------------------------------------------
# LRU result cache — avoids re-running ML inference on identical inputs.
# Only used for global-mode scans (no per-connection overrides), keyed on
# (direction, sorted scanner IDs, text).  Max 1 000 entries.
# ---------------------------------------------------------------------------
_RESULT_CACHE_SIZE = 1000
_result_cache: OrderedDict = OrderedDict()  # key -> (is_valid, text, results, violations)


def _result_cache_key(direction: str, entries: list, text: str) -> str:
    # Include on_fail_action in cache key so action changes invalidate the cache
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


def _import_embedding_shield(params: dict) -> Any:
    """Instantiate the first-party EmbeddingShield scanner."""
    from app.services.embedding_shield import EmbeddingShield
    return EmbeddingShield(**params)


# Exact language names accepted by the llm-guard Code scanner.
_CODE_SCANNER_LANGUAGES = [
    "ARM Assembly", "AppleScript", "C", "C#", "C++", "COBOL", "Erlang", "Fortran",
    "Go", "Java", "JavaScript", "Kotlin", "Lua", "Mathematica/Wolfram Language",
    "PHP", "Pascal", "Perl", "PowerShell", "Python", "R", "Ruby", "Rust", "Scala",
    "Swift", "Visual Basic .NET", "jq",
]
# Lowercase lookup so user-entered values like "javascript" → "JavaScript"
_LANG_NORMALIZE: dict[str, str] = {l.lower(): l for l in _CODE_SCANNER_LANGUAGES}
# Extra aliases for common shorthand
_LANG_NORMALIZE.update({
    "js": "JavaScript",
    "ts": "JavaScript",      # TypeScript maps to JS detection
    "typescript": "JavaScript",
    "bash": "PowerShell",    # closest shell equivalent
    "shell": "PowerShell",
    "sh": "PowerShell",
    "csharp": "C#",
    "cpp": "C++",
    "vb.net": "Visual Basic .NET",
    "vb": "Visual Basic .NET",
    "wolfram": "Mathematica/Wolfram Language",
    "mathematica": "Mathematica/Wolfram Language",
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


# Matches triple-backtick fenced code blocks (``` or ```lang\n...\n```)
_MARKDOWN_CODE_FENCE_RE = re.compile(r"```[\w]*\n[\s\S]*?```", re.DOTALL)


class BanCode:
    """
    Wraps llm_guard's BanCode output scanner to correctly detect markdown-fenced code.

    llm_guard's BanCode calls remove_markdown() before ML inference, which strips the
    content inside ``` fences so the model never sees the code — producing false-negatives
    for every LLM that wraps its code in ```python ... ```.

    This wrapper short-circuits to a guaranteed block when a fenced code block is present,
    then falls through to the normal BanCode ML scan for raw (un-fenced) code.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def scan(self, prompt: str, output: str) -> tuple[str, bool, float]:
        if _MARKDOWN_CODE_FENCE_RE.search(output):
            logger.warning("BanCode: markdown code fence detected in output — blocked")
            return output, False, 1.0
        return self._inner.scan(prompt, output)


_BanCodeOutputWrapper = BanCode  # alias kept for backwards-compat with cached entries


def _build_scanner(scanner_type: str, direction: str, params: dict) -> Any:
    """
    Instantiate a scanner, with smart routing for BanCode:
    - BanCode + languages list → route to Code scanner (supports per-language blocking)
    - BanCode with no languages → use BanCode as-is (blocks all code)
    - All other scanners → instantiate directly
    """
    if scanner_type == "CustomRule":
        return _import_custom_scanner(direction, params)

    if scanner_type == "EmbeddingShield":
        return _import_embedding_shield(params)

    if scanner_type == "BanCode":
        languages = params.get("languages")
        if languages:
            normalized = _normalize_languages(languages)
            if not normalized:
                # All entries were invalid — fall back to BanCode (block all)
                clean = {k: v for k, v in params.items() if k not in ("languages", "is_blocked")}
                return _import_scanner("BanCode", direction, clean)
            code_params = {
                "languages": normalized,
                "is_blocked": True,
                "threshold": params.get("threshold", 0.4),
            }
            logger.info(f"BanCode with languages={normalized} → routing to Code scanner")
            return _import_scanner("Code", direction, code_params)
        # No languages — BanCode detects all code; strip any invalid keys
        clean = {k: v for k, v in params.items() if k not in ("languages", "is_blocked")}
        scanner = _import_scanner("BanCode", direction, clean)
        # Wrap output scanner to catch markdown-fenced code (llm_guard strips fences before ML)
        if direction == "output":
            return BanCode(scanner)
        return scanner

    return _import_scanner(scanner_type, direction, params)


async def _load_scanners(
    session: AsyncSession, direction: str
) -> list[tuple[Any, str, list[str], int, dict, str]]:
    """Return list of (scanner_instance, scanner_name, custom_blocked_phrases, guardrail_id, scanner_params, on_fail_action)."""
    global _cache_valid

    if direction in _cache_valid and direction in _cache:
        return _cache[direction]

    configs: list[GuardrailConfig] = await list_guardrails(session)
    active = sorted(
        [c for c in configs if c.direction == direction and c.is_active],
        key=lambda c: c.order,
    )

    entries: list[tuple[Any, str, list[str], int, dict, str]] = []
    for config in active:
        raw_params = dict(config.params or {})

        # Extract meta-params before passing to llm-guard
        custom_phrases: list[str] = [
            str(p).strip()
            for p in raw_params.pop("custom_blocked_phrases", [])
            if str(p).strip()
        ]
        scanner_params = {k: v for k, v in raw_params.items() if k not in _META_PARAMS}
        on_fail_action = getattr(config, "on_fail_action", None) or "block"

        try:
            scanner = _build_scanner(config.scanner_type, direction, scanner_params)
            entries.append((scanner, config.scanner_type, custom_phrases, config.id, scanner_params, on_fail_action))
            logger.info(f"Loaded scanner: {config.scanner_type} (id={config.id}, on_fail={on_fail_action})")
        except Exception as e:
            logger.warning(f"Skipping scanner {config.scanner_type}: {e}")

    _cache[direction] = entries
    _cache_valid.add(direction)

    return entries


async def _load_scanners_by_ids(
    session: AsyncSession, direction: str, ids: set[int]
) -> list[tuple[Any, str, list[str], int, dict, str]]:
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

    entries: list[tuple[Any, str, list[str], int, dict, str]] = []
    for config in configs:
        raw_params = dict(config.params or {})
        custom_phrases: list[str] = [
            str(p).strip()
            for p in raw_params.pop("custom_blocked_phrases", [])
            if str(p).strip()
        ]
        scanner_params = {k: v for k, v in raw_params.items() if k not in _META_PARAMS}
        on_fail_action = getattr(config, "on_fail_action", None) or "block"
        try:
            scanner = _build_scanner(config.scanner_type, direction, scanner_params)
            entries.append((scanner, config.scanner_type, custom_phrases, config.id, scanner_params, on_fail_action))
            logger.info(f"Loaded per-connection scanner: {config.scanner_type} (id={config.id}, active={config.is_active}, on_fail={on_fail_action})")
        except Exception as e:
            logger.warning(f"Skipping per-connection scanner {config.scanner_type}: {e}")
    return entries


def _apply_custom_phrases(
    text: str,
    entries: list[tuple[Any, str, list[str], int, dict, str]],
    results_score: dict,
    violation_scanners: list,
) -> bool:
    """
    Check custom_blocked_phrases for every scanner entry.
    Custom phrases always use the 'block' action (they are explicit hard-blocks).
    Returns True if any phrase matched (i.e. overall_valid should become False).
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
    """Run a single input scanner synchronously (called in thread pool).
    Returns (sanitized_text, valid_dict, score_dict).
    sanitized_text may differ from text for sanitizing scanners (Anonymize, Secrets, etc.).
    """
    from llm_guard.evaluate import scan_prompt
    sanitized, valid_dict, score_dict = scan_prompt([scanner], text)
    return sanitized, valid_dict, score_dict


def _scan_one_output(scanner: Any, prompt: str, output: str) -> tuple[str, dict, dict]:
    """Run a single output scanner synchronously (called in thread pool).
    Returns (sanitized_text, valid_dict, score_dict).
    """
    from llm_guard.evaluate import scan_output
    sanitized, valid_dict, score_dict = scan_output([scanner], prompt, output)
    return sanitized, valid_dict, score_dict


def _apply_threshold_overrides(
    entries: list[tuple[Any, str, list[str], int, dict, str]],
    threshold_overrides: dict[int, float],
    direction: str,
) -> list[tuple[Any, str, list[str], int, dict, str]]:
    """Re-instantiate scanners whose guardrail_id has a threshold override."""
    result = []
    for e in entries:
        scanner, scanner_type, phrases, guardrail_id, params, on_fail_action = e
        if guardrail_id in threshold_overrides:
            override_params = {**params, "threshold": threshold_overrides[guardrail_id]}
            try:
                new_scanner = _import_scanner(scanner_type, direction, override_params)
                result.append((new_scanner, scanner_type, phrases, guardrail_id, params, on_fail_action))
                logger.info(f"Applied threshold override {threshold_overrides[guardrail_id]} to {scanner_type} (id={guardrail_id})")
            except Exception as ex:
                logger.warning(f"Threshold override failed for {scanner_type}: {ex}")
                result.append(e)
        else:
            result.append(e)
    return result


def _build_reask_message(scanner_name: str, score: float) -> str:
    """Build a human-readable correction instruction for a failed scanner."""
    return (
        f"Your response was flagged by the '{scanner_name}' guardrail "
        f"(confidence: {score:.0%}). Please revise your message to comply with the policy."
    )


async def run_input_scan(
    session: AsyncSession,
    text: str,
    allowed_types: set[str] | None = None,
    allowed_guardrail_ids: set[int] | None = None,
    threshold_overrides: dict[int, float] | None = None,
) -> tuple[bool, str, dict, list, dict, list[str] | None, bool]:
    """
    Run all active input scanners in parallel threads.

    Returns:
        (is_valid, sanitized_text, scanner_results, violation_scanners,
         on_fail_actions, reask_context, fix_applied)

    on_fail_action semantics (inspired by Guardrails AI):
      block   — violation causes is_valid=False (default)
      fix     — scanner's sanitized output is used; is_valid remains True
      monitor — violation is logged but is_valid remains True
      reask   — violation causes is_valid=False + reask_context populated
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
        return True, text, {}, [], {}, None, False

    # ── Text canonicalization (v17) ─────────────────────────────────────────
    # Produce a canonical form for rule-based scanners (BanSubstrings, Regex).
    # ML scanners still see the original text for best classification accuracy.
    canonical_text = canonicalize(text)
    _has_canonical = canonical_text != text
    if _has_canonical:
        logger.debug("Text canonicalized: original=%d chars, canonical=%d chars", len(text), len(canonical_text))

    # Check LRU cache (global mode only, no per-connection overrides)
    # Include canonical text in cache key so evasion variants cache separately
    _cache_input = f"{text}\x01{canonical_text}" if _has_canonical else text
    cache_key = _result_cache_key("input", entries, _cache_input) if use_cache else None
    if cache_key:
        cached = _result_cache_get(cache_key)
        if cached is not None:
            return cached

    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(
            _executor, _scan_one_input, e[0],
            # Rule-based scanners see canonical text; ML scanners see original
            canonical_text if _has_canonical and e[1] in _CANONICAL_SCANNERS else text,
        )
        for e in entries
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    results_valid: dict[str, bool] = {}
    results_score: dict[str, float] = {}
    # Map scanner_name → (sanitized_text, on_fail_action) for failed scanners
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
        # Track sanitized text for violated scanners with fix action
        if not all(valid_dict.values()):
            scanner_sanitized[scanner_name] = (sanitized, on_fail_action)

    # ── Apply on_fail_action per violated scanner ───────────────────────────
    overall_valid = True
    violation_scanners: list[str] = []
    on_fail_actions: dict[str, str] = {}
    reask_msgs: list[str] = []
    fix_applied = False
    current_text = text

    for scanner_name, is_valid_flag in results_valid.items():
        if is_valid_flag:
            continue
        # Determine the on_fail_action for this scanner
        action = "block"
        for e in entries:
            if e[1] == scanner_name:
                action = e[5]
                break

        score = results_score.get(scanner_name, 1.0)

        if action == "monitor":
            # Log only — let the request through
            on_fail_actions[scanner_name] = "monitored"
            logger.info("Scanner %s: violation monitored (score=%.3f, action=monitor)", scanner_name, score)

        elif action == "fix":
            # Use sanitized output instead of blocking
            san_info = scanner_sanitized.get(scanner_name)
            if san_info and san_info[0] != text:
                current_text = san_info[0]
                fix_applied = True
                on_fail_actions[scanner_name] = "fixed"
                logger.info("Scanner %s: violation fixed via sanitization (score=%.3f)", scanner_name, score)
            else:
                # Scanner doesn't produce a different sanitized text — fall back to block
                overall_valid = False
                violation_scanners.append(scanner_name)
                on_fail_actions[scanner_name] = "blocked"
                logger.warning("Scanner %s: fix action but no sanitized text — blocked (score=%.3f)", scanner_name, score)

        elif action == "reask":
            # Reject but provide correction context
            overall_valid = False
            violation_scanners.append(scanner_name)
            on_fail_actions[scanner_name] = "reask"
            reask_msgs.append(_build_reask_message(scanner_name, score))

        else:
            # Default: block
            overall_valid = False
            violation_scanners.append(scanner_name)
            on_fail_actions[scanner_name] = "blocked"

    phrase_hit = _apply_custom_phrases(text, entries, results_score, violation_scanners)
    # v17: Also check custom phrases against canonical text (catches homoglyph/leetspeak evasion)
    if _has_canonical and not phrase_hit:
        phrase_hit = _apply_custom_phrases(canonical_text, entries, results_score, violation_scanners)
    if phrase_hit:
        overall_valid = False

    reask_context = reask_msgs if reask_msgs else None
    result = (overall_valid, current_text, results_score, violation_scanners, on_fail_actions, reask_context, fix_applied)
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
) -> tuple[bool, str, dict, list, dict, list[str] | None, bool]:
    """
    Run all active output scanners in parallel threads.

    Returns:
        (is_valid, sanitized_text, scanner_results, violation_scanners,
         on_fail_actions, reask_context, fix_applied)
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
        return True, output, {}, [], {}, None, False

    # ── Text canonicalization (v17) — also applies to output scanning ────
    canonical_output = canonicalize(output)
    _has_canonical_out = canonical_output != output
    if _has_canonical_out:
        logger.debug("Output canonicalized: original=%d chars, canonical=%d chars", len(output), len(canonical_output))

    # Check LRU cache — key includes prompt so context is preserved
    _cache_out = f"{prompt}\x00{output}\x01{canonical_output}" if _has_canonical_out else f"{prompt}\x00{output}"
    cache_key = _result_cache_key("output", entries, _cache_out) if use_cache else None
    if cache_key:
        cached = _result_cache_get(cache_key)
        if cached is not None:
            return cached

    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(
            _executor, _scan_one_output, e[0], prompt,
            canonical_output if _has_canonical_out and e[1] in _CANONICAL_SCANNERS else output,
        )
        for e in entries
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

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

    # ── Apply on_fail_action per violated scanner ───────────────────────────
    overall_valid = True
    violation_scanners: list[str] = []
    on_fail_actions: dict[str, str] = {}
    reask_msgs: list[str] = []
    fix_applied = False
    current_text = output

    for scanner_name, is_valid_flag in results_valid.items():
        if is_valid_flag:
            continue
        action = "block"
        for e in entries:
            if e[1] == scanner_name:
                action = e[5]
                break

        score = results_score.get(scanner_name, 1.0)

        if action == "monitor":
            on_fail_actions[scanner_name] = "monitored"
            logger.info("Scanner %s: violation monitored (score=%.3f, action=monitor)", scanner_name, score)

        elif action == "fix":
            san_info = scanner_sanitized.get(scanner_name)
            if san_info and san_info[0] != output:
                current_text = san_info[0]
                fix_applied = True
                on_fail_actions[scanner_name] = "fixed"
                logger.info("Scanner %s: violation fixed via sanitization (score=%.3f)", scanner_name, score)
            else:
                overall_valid = False
                violation_scanners.append(scanner_name)
                on_fail_actions[scanner_name] = "blocked"
                logger.warning("Scanner %s: fix action but no sanitized text — blocked (score=%.3f)", scanner_name, score)

        elif action == "reask":
            overall_valid = False
            violation_scanners.append(scanner_name)
            on_fail_actions[scanner_name] = "reask"
            reask_msgs.append(_build_reask_message(scanner_name, score))

        else:
            overall_valid = False
            violation_scanners.append(scanner_name)
            on_fail_actions[scanner_name] = "blocked"

    phrase_hit = _apply_custom_phrases(output, entries, results_score, violation_scanners)
    # v17: Also check custom phrases against canonical output
    if _has_canonical_out and not phrase_hit:
        phrase_hit = _apply_custom_phrases(canonical_output, entries, results_score, violation_scanners)
    if phrase_hit:
        overall_valid = False

    reask_context = reask_msgs if reask_msgs else None
    result = (overall_valid, current_text, results_score, violation_scanners, on_fail_actions, reask_context, fix_applied)
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
        _, _, r1, v1, *_ = gathered[idx]; idx += 1
        merged_results.update(r1)
        for v in v1:
            if v not in merged_violations:
                merged_violations.append(v)

    if run_p2:
        _, _, r2, v2, *_ = gathered[idx]
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
        _, _, r3, v3, *_ = await run_input_scan(
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
