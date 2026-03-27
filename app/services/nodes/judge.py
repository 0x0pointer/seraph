"""
LLM-as-a-Judge node — Tier 2 of the guard pipeline.

Wraps LangGraphJudge as a pure async node function over GuardState.
Only runs when the judge is enabled and the NeMo risk score falls in the
configured uncertainty band (or run_on_every_request is True).
"""
from __future__ import annotations

import logging

from app.services.state import GuardState

logger = logging.getLogger(__name__)


async def judge_node(state: GuardState) -> dict:
    """Tier 2: deep LLM evaluation via LangGraph judge.

    Skips entirely when the judge is disabled or the NeMo score is outside
    the uncertainty band.  Blocks on high risk score or detected threats.
    """
    # Lazy imports to avoid circular dependency with scanner_engine
    from app.services.scanner_engine import _get_judge, _should_run_judge

    if not _should_run_judge(state["nemo_risk_score"]):
        return {}

    judge = _get_judge()
    if judge is None:
        return {}

    try:
        result = await judge.evaluate(
            state["raw_text"],
            direction=state["direction"],
            prompt_context=state["prompt_context"] or None,
        )
    except Exception as exc:
        logger.error("Judge node (%s) failed: %s", state["direction"], exc)
        return {
            "blocked": True,
            "block_reason": f"Judge evaluation failed: {exc}",
            "scanner_results": {**state["scanner_results"], "LLMJudge": 1.0},
            "violations": [*state["violations"], "LLMJudge"],
            "on_fail_actions": {**state["on_fail_actions"], "LLMJudge": "blocked"},
        }

    updated_scores = {**state["scanner_results"], "LLMJudge": result.risk_score}

    if not result.passed:
        logger.warning(
            "LLM Judge blocked %s: score=%.3f, threats=%s",
            state["direction"], result.risk_score, result.threats,
        )
        return {
            "blocked": True,
            "block_reason": f"Judge detected threats: {', '.join(result.threats)}",
            "scanner_results": updated_scores,
            "violations": [*state["violations"], "LLMJudge"],
            "on_fail_actions": {**state["on_fail_actions"], "LLMJudge": "blocked"},
        }

    logger.debug(
        "LLM Judge passed %s: score=%.3f, reasoning=%s",
        state["direction"], result.risk_score, result.reasoning,
    )
    return {"scanner_results": updated_scores}
