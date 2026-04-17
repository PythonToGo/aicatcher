"""Embedder — sentence-transformers all-MiniLM-L6-v2 (local, free).

Model size: ~80 MB. Downloaded automatically from HuggingFace Hub on first run.
GitHub Actions caches the model directory to avoid re-downloading.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_MODEL_NAME = "all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Singleton model instance. Loaded on first call (~1–2 seconds)."""
    logger.info("loading sentence-transformer model: %s", _MODEL_NAME)
    return SentenceTransformer(_MODEL_NAME)


class Embedder:
    """Converts text to embedding vectors."""

    def embed(self, text: str) -> NDArray[np.float32]:
        """Encode a single text into a 384-dim float32 vector."""
        model = _get_model()
        result = model.encode(
            text,
            normalize_embeddings=True,  # cosine similarity == dot product for normalized vectors
            show_progress_bar=False,
        )
        return np.asarray(result, dtype=np.float32)

    def embed_batch(self, texts: list[str]) -> NDArray[np.float32]:
        """Encode multiple texts at once. Faster than repeated single calls."""
        if not texts:
            return np.empty((0, 384), dtype=np.float32)
        model = _get_model()
        result = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=64,
        )
        return np.asarray(result, dtype=np.float32)


def cosine_similarity(a: NDArray[np.float32], b: NDArray[np.float32]) -> float:
    """Cosine similarity between two normalized vectors (== dot product). Range: [-1, 1]."""
    return float(np.dot(a, b))
