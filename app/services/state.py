"""
GuardState — typed state that flows through the guard pipeline graph.

Adopted from the CTF LLM-judge architecture pattern: a single TypedDict
carries all scan context through every LangGraph node, making the pipeline
declarative and each node a pure function over state.
"""
from __future__ import annotations

from typing import Literal, TypedDict


class GuardState(TypedDict):
    """Typed state flowing through the guard LangGraph pipeline."""

    # ── Input ─────────────────────────────────────────────────────────────────
    raw_text: str                         # Text being evaluated
    direction: Literal["input", "output"] # Which side of the proxy
    prompt_context: str                   # Original user prompt (output scans only)

    # ── Accumulated scan results ──────────────────────────────────────────────
    scanner_results: dict[str, float]     # scanner_name → risk_score
    violations: list[str]                 # scanner names that triggered a block
    on_fail_actions: dict[str, str]       # scanner_name → "blocked" | "monitored"
    sanitized_text: str                   # May differ from raw_text if a scanner fixed it

    # ── Control flow ──────────────────────────────────────────────────────────
    blocked: bool                         # True if any scanner blocked the request
    block_reason: str | None              # Human-readable reason for the block

    # ── Tier routing ──────────────────────────────────────────────────────────
    nemo_risk_score: float                # NeMo score; drives judge uncertainty routing
