"""
Tier 2: LLM-as-a-Judge via LangGraph.

A small language model evaluates text against security criteria and returns
a structured verdict. Uses a 2-node StateGraph inspired by the Tutur/LLM
guard pattern:

    START → classify (SLM call via ChatPromptTemplate) → decide (threshold) → END

The judge prompt is loaded from a separate file so security teams can iterate
on evaluation criteria without code changes.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from app.services.prompts import DEFAULT_JUDGE_PROMPT as _DEFAULT_PROMPT
from app.services.prompts import INPUT_JUDGE_PROMPT, OUTPUT_JUDGE_PROMPT  # noqa: F401 (re-exported)

logger = logging.getLogger(__name__)


@dataclass
class JudgeResult:
    passed: bool
    risk_score: float
    reasoning: str
    threats: list[str] = field(default_factory=list)
    latency_ms: float = 0.0


class JudgeState(TypedDict):
    text: str
    direction: str
    prompt_context: str
    risk_threshold: float
    raw_response: str
    verdict: str
    risk_score: float
    reasoning: str
    threats_detected: list[str]
    blocked: bool


class LangGraphJudge:
    """LLM-as-a-Judge using a LangGraph StateGraph with ChatPromptTemplate chains."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 512,
        risk_threshold: float = 0.7,
        prompt_file: str = "app/services/judge_prompt.txt",
    ) -> None:
        self._model_name = model
        self._base_url = base_url
        self._api_key = api_key
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._risk_threshold = risk_threshold
        self._prompt_file = prompt_file
        self._system_prompt: str | None = None

        self._llm = self._build_llm()
        self._graph = self._build_graph()

    def _build_llm(self) -> ChatOpenAI:
        kwargs: dict[str, Any] = {
            "model": self._model_name,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if self._base_url:
            kwargs["base_url"] = self._base_url
        if self._api_key:
            kwargs["api_key"] = self._api_key
        return ChatOpenAI(**kwargs)

    def _load_system_prompt(self) -> str:
        if self._system_prompt is not None:
            return self._system_prompt

        path = Path(self._prompt_file)
        if path.exists():
            self._system_prompt = path.read_text().strip()
        else:
            logger.warning("Judge prompt file not found: %s — using default", path)
            self._system_prompt = _DEFAULT_PROMPT

        return self._system_prompt

    def _build_graph(self) -> Any:
        graph = StateGraph(JudgeState)
        graph.add_node("classify", self._classify_node)
        graph.add_node("decide", self._decide_node)
        graph.add_edge(START, "classify")
        graph.add_edge("classify", "decide")
        graph.add_edge("decide", END)
        return graph.compile()

    async def _classify_node(self, state: JudgeState) -> dict:
        """Call the SLM with the appropriate prompt template."""
        system_prompt = self._load_system_prompt()

        # Select prompt template based on direction
        if state["direction"] == "output" and state.get("prompt_context"):
            chain = OUTPUT_JUDGE_PROMPT | self._llm
            invoke_kwargs = {
                "system_prompt": system_prompt,
                "text": state["text"],
                "prompt_context": state["prompt_context"],
            }
        else:
            chain = INPUT_JUDGE_PROMPT | self._llm
            invoke_kwargs = {
                "system_prompt": system_prompt,
                "text": state["text"],
            }

        try:
            response = await chain.ainvoke(invoke_kwargs)
            raw = response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.error("Judge SLM call failed: %s", e)
            raw = json.dumps({
                "verdict": "block",
                "risk_score": 1.0,
                "reasoning": f"Judge evaluation failed: {e}",
                "threats_detected": ["evaluation_error"],
            })

        return {"raw_response": raw}

    def _decide_node(self, state: JudgeState) -> dict:
        """Parse the SLM response and apply the risk threshold."""
        raw = state.get("raw_response", "")
        threshold = state.get("risk_threshold", self._risk_threshold)

        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                lines = [l for l in lines[1:] if not l.strip().startswith("```")]
                cleaned = "\n".join(lines)

            parsed = json.loads(cleaned)
            risk_score = float(parsed.get("risk_score", 1.0))
            reasoning = parsed.get("reasoning", "No reasoning provided")
            threats = parsed.get("threats_detected", [])
            verdict_hint = parsed.get("verdict", "")
        except (ValueError, TypeError) as e:
            logger.warning("Judge response parse failed: %s — raw: %s", e, raw[:200])
            risk_score = 0.8
            reasoning = f"Failed to parse judge response: {raw[:200]}"
            threats = ["parse_error"]
            verdict_hint = "block"

        # Threshold is authoritative; SLM verdict is advisory
        if risk_score >= threshold or (verdict_hint == "block" and risk_score >= threshold * 0.8):
            verdict = "block"
            blocked = True
        else:
            verdict = "pass"
            blocked = False

        return {
            "verdict": verdict,
            "risk_score": risk_score,
            "reasoning": reasoning,
            "threats_detected": threats,
            "blocked": blocked,
        }

    async def evaluate(self, text: str, direction: str = "input",
                       prompt_context: str | None = None) -> JudgeResult:
        """Run the judge graph and return a structured result."""
        start = time.perf_counter()

        initial_state: JudgeState = {
            "text": text,
            "direction": direction,
            "prompt_context": prompt_context or "",
            "risk_threshold": self._risk_threshold,
            "raw_response": "",
            "verdict": "pass",
            "risk_score": 0.0,
            "reasoning": "",
            "threats_detected": [],
            "blocked": False,
        }

        try:
            result = await self._graph.ainvoke(initial_state)
        except Exception as e:
            logger.error("Judge graph execution failed: %s", e)
            elapsed = (time.perf_counter() - start) * 1000
            return JudgeResult(
                passed=False, risk_score=1.0,
                reasoning=f"Judge execution failed: {e}",
                threats=["execution_error"], latency_ms=elapsed,
            )

        elapsed = (time.perf_counter() - start) * 1000

        return JudgeResult(
            passed=not result.get("blocked", False),
            risk_score=result.get("risk_score", 0.0),
            reasoning=result.get("reasoning", ""),
            threats=result.get("threats_detected", []),
            latency_ms=elapsed,
        )

    def reload(self, model: str | None = None, base_url: str | None = None,
               api_key: str | None = None, temperature: float | None = None,
               max_tokens: int | None = None, risk_threshold: float | None = None,
               prompt_file: str | None = None) -> None:
        """Reload judge configuration."""
        if model is not None:
            self._model_name = model
        if base_url is not None:
            self._base_url = base_url
        if api_key is not None:
            self._api_key = api_key
        if temperature is not None:
            self._temperature = temperature
        if max_tokens is not None:
            self._max_tokens = max_tokens
        if risk_threshold is not None:
            self._risk_threshold = risk_threshold
        if prompt_file is not None:
            self._prompt_file = prompt_file

        self._system_prompt = None
        self._llm = self._build_llm()
        self._graph = self._build_graph()
        logger.info("LangGraph judge reloaded — model=%s", self._model_name)
