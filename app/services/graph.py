"""
Guard pipeline — LangGraph StateGraph.

Replaces the imperative if/else orchestration in scanner_engine with a
declarative graph adopted from the CTF LLM-judge architecture pattern:

    START → nemo_check → [blocked?] → END
                       ↘ judge_check → END

Each node is a pure async function over GuardState.  Conditional edges
implement the same routing the old _run_two_tier_scan did imperatively,
but the flow is now explicit, inspectable, and trivially extensible.
"""
from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app.services.nodes.judge import judge_node
from app.services.nodes.nemo import nemo_node
from app.services.state import GuardState

logger = logging.getLogger(__name__)


def _route_after_nemo(state: GuardState) -> str:
    """After NeMo check: skip judge if already blocked, else continue."""
    return "end" if state.get("blocked") else "judge_check"


def build_guard_graph():
    """Compile the guard StateGraph.

    Graph topology (mirrors CTF dual-guard pattern):
        START → nemo_check → conditional → judge_check → END
                                         ↘ END  (if NeMo blocked)
    """
    graph = StateGraph(GuardState)

    graph.add_node("nemo_check", nemo_node)
    graph.add_node("judge_check", judge_node)

    graph.add_edge(START, "nemo_check")
    graph.add_conditional_edges(
        "nemo_check",
        _route_after_nemo,
        {"end": END, "judge_check": "judge_check"},
    )
    graph.add_edge("judge_check", END)

    compiled = graph.compile()
    logger.debug("Guard graph compiled")
    return compiled


# ── Module-level compiled graph (lazy, invalidated on config reload) ──────────

_guard_graph = None


def get_guard_graph():
    """Return the compiled guard graph, building it on first call."""
    global _guard_graph
    if _guard_graph is None:
        _guard_graph = build_guard_graph()
    return _guard_graph


def invalidate_guard_graph() -> None:
    """Discard the compiled graph so it is rebuilt on the next scan."""
    global _guard_graph
    _guard_graph = None
    logger.debug("Guard graph invalidated")
