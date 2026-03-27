"""
NeMo Guardrails node — Tier 1 of the guard pipeline.

Wraps NemoTier as a pure async node function over GuardState.
Returns partial state updates that LangGraph merges into the running state.
"""
from __future__ import annotations

import logging

from app.services.state import GuardState

logger = logging.getLogger(__name__)


async def nemo_node(state: GuardState) -> dict:
    """Tier 1: semantic allow-list check via NeMo Guardrails.

    Blocks immediately if no Colang flow matches the input.
    Sets ``nemo_risk_score`` so the graph can route to the judge tier.
    """
    # Lazy import to avoid circular dependency with scanner_engine
    from app.services.scanner_engine import _get_nemo_tier

    nemo = _get_nemo_tier()
    if nemo is None:
        return {"nemo_risk_score": 0.0}

    try:
        if state["direction"] == "output":
            result = await nemo.evaluate_output(state["prompt_context"], state["raw_text"])
        else:
            result = await nemo.evaluate(state["raw_text"])
    except Exception as exc:
        logger.error("NeMo node failed: %s", exc)
        return {
            "blocked": True,
            "block_reason": f"NeMo evaluation failed: {exc}",
            "scanner_results": {**state["scanner_results"], "NeMoGuardrails": 1.0},
            "violations": [*state["violations"], "NeMoGuardrails"],
            "on_fail_actions": {**state["on_fail_actions"], "NeMoGuardrails": "blocked"},
            "nemo_risk_score": 1.0,
        }

    updated_scores = {**state["scanner_results"], "NeMoGuardrails": result.risk_score}

    if not result.passed:
        logger.warning(
            "NeMo blocked %s: %s", state["direction"], result.detail
        )
        return {
            "blocked": True,
            "block_reason": result.detail,
            "scanner_results": updated_scores,
            "violations": [*state["violations"], "NeMoGuardrails"],
            "on_fail_actions": {**state["on_fail_actions"], "NeMoGuardrails": "blocked"},
            "nemo_risk_score": result.risk_score,
        }

    return {
        "scanner_results": updated_scores,
        "nemo_risk_score": result.risk_score,
    }
