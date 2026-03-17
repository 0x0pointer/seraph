"""
CustomRuleScanner — a first-party scanner that does not require llm-guard.

Supports three rule types that can be freely combined:
  blocked_keywords  : list[str]  — case-insensitive substring match
  blocked_patterns  : list[str]  — Python re patterns (case-insensitive)
  blocked_topics    : list[str]  — zero-shot AI classification via BanTopics model
  topics_threshold  : float      — classification threshold (default 0.5)

Works for both directions:
  input  — scan(prompt)           called by llm_guard.evaluate.scan_prompt
  output — scan(prompt, output)   called by llm_guard.evaluate.scan_output
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


class CustomRuleScanner:
    """
    Unified custom rule scanner satisfying both the llm-guard InputScanner
    and OutputScanner protocols via a flexible scan() signature.
    """

    def __init__(
        self,
        *,
        direction: str = "input",
        blocked_keywords: list[str] | None = None,
        blocked_patterns: list[str] | None = None,
        blocked_topics: list[str] | None = None,
        topics_threshold: float = 0.5,
    ) -> None:
        self._direction = direction
        self._keywords: list[str] = [
            kw.strip() for kw in (blocked_keywords or []) if kw.strip()
        ]
        self._patterns: list[re.Pattern] = []
        self._topics: list[str] = [
            t.strip() for t in (blocked_topics or []) if t.strip()
        ]
        self._topics_threshold = topics_threshold
        self._ban_topics_scanner = None  # lazy — only load model if topics provided

        for raw in (blocked_patterns or []):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                self._patterns.append(re.compile(stripped, re.IGNORECASE))
            except re.error as exc:
                logger.warning(
                    f"CustomRuleScanner: invalid regex pattern {stripped!r} skipped: {exc}"
                )

        if self._topics:
            self._ban_topics_scanner = self._build_ban_topics()

    def _build_ban_topics(self):
        from llm_guard.input_scanners.ban_topics import BanTopics
        return BanTopics(topics=self._topics, threshold=self._topics_threshold)

    def _target_text(self, prompt: str, output: str) -> str:
        return output if (self._direction == "output" and output) else prompt

    def scan(self, prompt: str, output: str = "") -> tuple[str, bool, float]:
        """
        Compatible with both scanner protocols:
          InputScanner.scan(prompt)           → output defaults to ""
          OutputScanner.scan(prompt, output)  → both args provided
        """
        text = self._target_text(prompt, output)

        text_lower = text.lower()
        for kw in self._keywords:
            if kw.lower() in text_lower:
                logger.warning(f"CustomRuleScanner: keyword matched: {kw!r}")
                return text, False, 1.0

        for pattern in self._patterns:
            if pattern.search(text):
                logger.warning(f"CustomRuleScanner: pattern matched: {pattern.pattern!r}")
                return text, False, 1.0

        if self._ban_topics_scanner is not None:
            _, is_valid, risk_score = self._ban_topics_scanner.scan(text)
            if not is_valid:
                logger.warning(f"CustomRuleScanner: topic matched (score={risk_score})")
                return text, False, risk_score

        return text, True, 0.0
