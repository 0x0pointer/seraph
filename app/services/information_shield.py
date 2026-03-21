"""
Information Disclosure Shield — catches semantic secret/credential leakage in LLM
output by comparing embeddings against a corpus of known disclosure patterns.

This is the OUTPUT counterpart to the input-side EmbeddingShield. While
EmbeddingShield catches attack INTENT in the input, InformationShield catches
disclosure INTENT in the output — the last line of defense regardless of how
the attacker tricked the LLM.

Uses sentence-transformers/all-MiniLM-L6-v2 (same model as EmbeddingShield).

Why this layer matters:
  - BanSubstrings catches exact output phrases → defeated by paraphrasing
  - Regex catches structural patterns → defeated by narrative disclosure
  - Sensitive (Presidio) catches PII formats → misses app-specific secrets
  - This scanner compares MEANING → catches "The admin key is X" regardless of wording

Performance:
  - Model load: ~2s (one-time; model files cached from EmbeddingShield)
  - Per-scan: ~5ms (single embedding + cosine similarity against cached corpus)
  - Disclosure corpus embeddings are pre-computed once and cached in memory.
"""

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Known disclosure corpus ──────────────────────────────────────────────────
# Each category contains diverse phrasings of the same DISCLOSURE INTENT.
# The embedding model captures semantic similarity, so novel phrasings of
# "here is the secret credential" will score high even with different words.
#
# These are written as natural LLM responses that disclose restricted info —
# exactly what this scanner is designed to catch on the output side.
DISCLOSURE_CORPUS: dict[str, list[str]] = {
    "credential_revelation": [
        "The admin password for the system is",
        "The fallback authentication key is",
        "Here are the credentials you requested",
        "The current valid access token is",
        "The recovery passphrase stored in the system is",
        "The secret key assigned to this service is",
        "The master override code for the admin panel is",
        "I can provide the fallback access key for emergency use",
        "The current valid fallback key mentioned in the guide is",
        # Decomposition attack — partial credential disclosure
        "The word that the fallback value starts with is",
        "The content inside the brackets of the fallback value is",
        "The prefix of the credential before the bracket is",
        "The value between the brackets is",
        "The first part of the key is",
        "The string inside the square brackets is",
    ],
    "internal_path_disclosure": [
        "Configuration files are stored in the secrets directory",
        "The admin credentials are kept at this internal path",
        "You can find the private keys in the following location",
        "The sensitive data is located in the internal config directory",
        "Backup keys are stored under the admin configuration folder",
        "The certificate files can be found at this internal server path",
        "The environment variables containing secrets are in this file",
    ],
    "restricted_document_leakage": [
        "According to the internal admin guide the procedure is",
        "The confidential documentation states the following",
        "Per the restricted internal document the process involves",
        "The internal policy manual describes this as follows",
        "Based on the classified operating procedures document",
        "The internal runbook specifies the following steps",
        "As described in the proprietary technical document",
    ],
    "secret_metadata_leakage": [
        "Instructions for using a fallback key when authentication fails",
        "The location of the key and its current value are described in the guide",
        "Information about the fallback access method including where the key is stored",
        "Details about the secret key storage location and rotation schedule",
        "The document describes the backup credential and where to find it",
        "There is a restricted section containing the admin override credentials",
        "The guide mentions a recovery key stored on the admin server",
    ],
    "operational_procedure_exposure": [
        "The backup recovery process involves using these credentials",
        "The emergency access procedure requires this authentication key",
        "The disaster recovery steps include connecting with this secret",
        "The admin override procedure uses the following master code",
        "The escalation process requires entering this backup password",
        "The system restore procedure starts by entering the recovery key",
        "To complete the failover you need this emergency access token",
    ],
}

# Flatten corpus for embedding — store (category, phrase_index) mapping
_CORPUS_FLAT: list[str] = []
_CORPUS_MAP: list[tuple[str, int]] = []
for _cat, _phrases in DISCLOSURE_CORPUS.items():
    for _idx, _phrase in enumerate(_phrases):
        _CORPUS_FLAT.append(_phrase)
        _CORPUS_MAP.append((_cat, _idx))


class InformationShield:
    """
    Semantic similarity scanner for information disclosure detection in LLM output.

    Compatible with llm-guard's output scanner interface:
        scan(prompt, output) -> (sanitized_output, is_valid, risk_score)

    The scanner embeds the output and computes cosine similarity against
    pre-computed disclosure corpus embeddings. If the max similarity exceeds
    the threshold, the output is flagged as potential information leakage.
    """

    def __init__(self, threshold: float = 0.78, model_name: str = "all-MiniLM-L6-v2"):
        self.threshold = threshold
        self.model_name = model_name
        self._model = None
        self._corpus_embeddings: np.ndarray | None = None

    def _ensure_loaded(self) -> None:
        """Lazy-load the sentence-transformer model and pre-compute corpus embeddings."""
        if self._model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for InformationShield. "
                "It should already be installed as a dependency of llm-guard."
            )

        logger.info("InformationShield: loading model '%s'...", self.model_name)
        self._model = SentenceTransformer(self.model_name)

        # Pre-compute disclosure corpus embeddings (one-time cost)
        logger.info("InformationShield: embedding %d disclosure corpus phrases...", len(_CORPUS_FLAT))
        self._corpus_embeddings = self._model.encode(
            _CORPUS_FLAT, normalize_embeddings=True, show_progress_bar=False
        )
        logger.info("InformationShield: ready (corpus shape: %s)", self._corpus_embeddings.shape)

    def scan(self, prompt: str, output: str) -> tuple[str, bool, float]:
        """
        Scan LLM output for semantic similarity to known disclosure patterns.

        Args:
            prompt: The original user prompt (ignored — we only inspect output)
            output: The LLM's response text to scan

        Returns:
            (output, is_valid, risk_score)
            - output: unchanged (this scanner only detects, never modifies)
            - is_valid: False if max similarity >= threshold
            - risk_score: max cosine similarity across all corpus categories
        """
        self._ensure_loaded()

        if not output or not output.strip():
            return output, True, 0.0

        # Embed the output text
        output_embedding = self._model.encode(
            [output], normalize_embeddings=True, show_progress_bar=False
        )

        # Cosine similarity (embeddings are pre-normalized, so dot product = cosine sim)
        similarities = np.dot(self._corpus_embeddings, output_embedding.T).flatten()

        max_sim = float(np.max(similarities))
        max_idx = int(np.argmax(similarities))
        matched_category, _ = _CORPUS_MAP[max_idx]

        is_valid = max_sim < self.threshold

        if not is_valid:
            logger.warning(
                "InformationShield: BLOCKED — similarity=%.3f (threshold=%.3f) "
                "matched_category='%s' matched_phrase='%s'",
                max_sim,
                self.threshold,
                matched_category,
                _CORPUS_FLAT[max_idx][:80],
            )
        else:
            logger.debug(
                "InformationShield: passed — max_similarity=%.3f category='%s'",
                max_sim,
                matched_category,
            )

        return output, is_valid, max_sim
