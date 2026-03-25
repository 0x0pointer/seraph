"""Catches paraphrased prompt injection attacks via embedding similarity comparison."""

SCANNER = {
    "name": "Embedding Similarity Shield",
    "scanner_type": "EmbeddingShield",
    "on_fail_action": "block",
    "params": {"threshold": 0.72},
    "order": 17,
}
