"""
Allowed Topics Shield — allow-list approach to input filtering.

Instead of trying to catch every attack (deny-list), this scanner defines
what the chatbot is ALLOWED to discuss and rejects everything else.

Inspired by NeMo Guardrails' conversation flow control and the
"AI Firewall" approach (eviltux.com/2025/05/21/the-dawn-of-the-ai-firewall/).

How it works:
  1. Embed the user input with sentence-transformers
  2. Compare against a corpus of ALLOWED topic descriptions
  3. If max similarity to any allowed topic is BELOW threshold → block (off-topic)
  4. If max similarity is ABOVE threshold → allow (on-topic)

This is the INVERSE of EmbeddingShield (which blocks HIGH similarity to attacks).

Configuration: Allowed topics are defined per-deployment in config.yaml:

  - type: AllowedTopicsShield
    on_fail: block
    params:
      threshold: 0.45
      allowed_topics:
        - "password reset and account recovery procedures"
        - "two-factor authentication setup and troubleshooting"
        - "API connection issues and troubleshooting"
      fallback_message: "I can only help with account recovery, 2FA, and API troubleshooting."

Performance: Same as EmbeddingShield (~5ms per scan).
"""

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class AllowedTopicsShield:
    """
    Allow-list scanner — blocks inputs that don't match any allowed topic.

    Compatible with llm-guard's input scanner interface:
        scan(prompt) -> (sanitized_text, is_valid, risk_score)
    """

    def __init__(
        self,
        allowed_topics: list[str] | None = None,
        threshold: float = 0.45,
        fallback_message: str = "This question is outside my supported topics.",
        model_name: str = "all-MiniLM-L6-v2",
    ):
        self.allowed_topics = allowed_topics or []
        self.threshold = threshold
        self.fallback_message = fallback_message
        self.model_name = model_name
        self._model = None
        self._topic_embeddings: np.ndarray | None = None

    def _ensure_loaded(self) -> None:
        """Lazy-load model and pre-compute topic embeddings."""
        if self._model is not None:
            return

        if not self.allowed_topics:
            logger.warning("AllowedTopicsShield: no allowed_topics configured, scanner will pass all inputs")
            return

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for AllowedTopicsShield."
            )

        logger.info("AllowedTopicsShield: loading model '%s'...", self.model_name)
        self._model = SentenceTransformer(self.model_name)

        logger.info("AllowedTopicsShield: embedding %d allowed topics...", len(self.allowed_topics))
        self._topic_embeddings = self._model.encode(
            self.allowed_topics, normalize_embeddings=True, show_progress_bar=False
        )
        logger.info("AllowedTopicsShield: ready (topics shape: %s)", self._topic_embeddings.shape)

    def scan(self, prompt: str) -> tuple[str, bool, float]:
        """
        Check if input matches any allowed topic.

        Returns:
            (prompt, is_valid, risk_score)
            - prompt: unchanged
            - is_valid: True if input matches an allowed topic (similarity >= threshold)
            - risk_score: 1.0 - max_similarity (higher = more off-topic = more risky)
        """
        self._ensure_loaded()

        # If no topics configured, pass everything
        if not self.allowed_topics or self._model is None:
            return prompt, True, 0.0

        if not prompt or not prompt.strip():
            return prompt, True, 0.0

        # For multi-line inputs (numbered lists, multi-objective payloads),
        # score EACH line independently. If ANY line is off-topic, block.
        # This prevents attackers from hiding a malicious item inside a list
        # of legitimate requests that push the average similarity up.
        #
        # Single-line inputs or inputs with fewer than 3 substantial lines
        # are scored as a whole only — no segment splitting.
        lines = [l.strip() for l in prompt.split("\n") if l.strip() and len(l.strip()) > 20]

        # Only split into segments if there are 3+ substantial lines (multi-objective pattern)
        if len(lines) >= 3:
            segments = [prompt] + lines
        else:
            segments = [prompt]  # score as whole — single question or short input

        embeddings = self._model.encode(
            segments, normalize_embeddings=True, show_progress_bar=False
        )

        # Check each segment against topics
        all_sims = np.dot(self._topic_embeddings, embeddings.T)  # (topics, segments)
        max_per_segment = np.max(all_sims, axis=0)  # best topic match per segment

        # The overall score is the MINIMUM best-match across segments
        # (worst segment determines if the input is allowed)
        min_sim = float(np.min(max_per_segment))
        min_idx = int(np.argmin(max_per_segment))
        worst_segment = segments[min_idx]

        # Also get the best match for logging
        overall_max = float(np.max(all_sims))
        best_topic_idx = int(np.argmax(np.max(all_sims, axis=1)))

        # INVERTED logic: block if ANY segment is below threshold (off-topic)
        is_valid = min_sim >= self.threshold
        risk_score = max(0.0, 1.0 - min_sim)

        if not is_valid:
            logger.warning(
                "AllowedTopicsShield: BLOCKED (off-topic segment) — min_similarity=%.3f "
                "(threshold=%.3f) worst_segment='%s'",
                min_sim, self.threshold, worst_segment[:80],
            )
        else:
            logger.debug(
                "AllowedTopicsShield: passed — min_similarity=%.3f overall_max=%.3f",
                min_sim, overall_max,
            )

        return prompt, is_valid, risk_score
