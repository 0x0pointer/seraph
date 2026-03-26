"""
CustomRuleScanner — a first-party scanner with no external ML dependencies.

Supports two rule types that can be freely combined:
  blocked_keywords  : list[str]  — case-insensitive substring match
  blocked_patterns  : list[str]  — Python re patterns (case-insensitive)

Works for both directions:
  input  — scan(prompt)           called by scanner_engine
  output — scan(prompt, output)   called by scanner_engine
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


class CustomRuleScanner:
    """
    Custom rule scanner using keyword matching and regex patterns.
    No external ML dependencies required.
    """

    def __init__(
        self,
        *,
        direction: str = "input",
        blocked_keywords: list[str] | None = None,
        blocked_patterns: list[str] | None = None,
    ) -> None:
        self._direction = direction
        self._keywords: list[str] = [
            kw.strip() for kw in (blocked_keywords or []) if kw.strip()
        ]
        self._patterns: list[re.Pattern] = []

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

    def _target_text(self, prompt: str, output: str) -> str:
        return output if (self._direction == "output" and output) else prompt

    def scan(self, prompt: str, output: str = "") -> tuple[str, bool, float]:
        """
        Evaluate text against keyword and regex rules.

        Returns:
            (text, is_valid, risk_score)
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

        return text, True, 0.0
