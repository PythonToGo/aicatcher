"""Unit tests for the dedup layer.

Embedder model loading is expensive, so all tests use mocks.
Real model behavior should be covered only in embedder integration tests.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from newsbot.dedup.embedder import Embedder, cosine_similarity
from newsbot.dedup.store import DeduplicationStore, _blob_to_vec, _vec_to_blob
from newsbot.models import RawItem


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_raw(
    title: str = "New GPT model released",
    url: str = "https://example.com/gpt",
    source: str = "hackernews",
) -> RawItem:
    return RawItem(
        title=title,
        url=url,
        body="body text",
        source=source,
        published_at=datetime.now(timezone.utc),
        raw_score=200.0,
    )


def _unit_vec(dim: int = 384, seed: int = 0) -> np.ndarray:
    """Return a reproducible unit vector."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _mock_embedder(vec: np.ndarray | None = None) -> Embedder:
    """Mock Embedder that returns a fixed vector."""
    embedder = MagicMock(spec=Embedder)
    fixed = vec if vec is not None else _unit_vec(seed=42)
    embedder.embed.return_value = fixed
    embedder.embed_batch.return_value = np.stack([fixed])
    return embedder


def _tmp_store(threshold: float = 0.92, embedder: Embedder | None = None) -> DeduplicationStore:
    """Store backed by a temporary file DB for test isolation."""
    tmp = tempfile.mktemp(suffix=".db")
    store = DeduplicationStore(
        db_path=Path(tmp),
        threshold=threshold,
        embedder=embedder or _mock_embedder(),
    )
    return store


# ── Vector serialization ─────────────────────────────────────────────────────

class TestVectorSerialization:
    def test_roundtrip(self) -> None:
        vec = _unit_vec()
        assert np.allclose(vec, _blob_to_vec(_vec_to_blob(vec)))

    def test_dtype_preserved(self) -> None:
        vec = _unit_vec()
        restored = _blob_to_vec(_vec_to_blob(vec))
        assert restored.dtype == np.float32


# ── cosine_similarity ─────────────────────────────────────────────────────────

class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = _unit_vec()
        assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors(self) -> None:
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-6)

    def test_opposite_vectors(self) -> None:
        v = _unit_vec()
        assert cosine_similarity(v, -v) == pytest.approx(-1.0, abs=1e-6)

    def test_returns_float(self) -> None:
        v = _unit_vec()
        result = cosine_similarity(v, v)
        assert isinstance(result, float)


# ── DeduplicationStore ────────────────────────────────────────────────────────

class TestDeduplicationStore:
    def test_context_manager(self) -> None:
        with _tmp_store() as store:
            assert store.count() == 0

    def test_not_connected_raises(self) -> None:
        store = _tmp_store()
        with pytest.raises(RuntimeError, match="not connected"):
            store.count()

    def test_count_starts_at_zero(self) -> None:
        with _tmp_store() as store:
            assert store.count() == 0

    def test_mark_seen_increments_count(self) -> None:
        item = _make_raw()
        with _tmp_store() as store:
            store.mark_seen(item)
            assert store.count() == 1

    def test_mark_seen_duplicate_url_ignored(self) -> None:
        item = _make_raw()
        with _tmp_store() as store:
            store.mark_seen(item)
            store.mark_seen(item)  # Same URL twice
            assert store.count() == 1

    # ── URL duplicates ───────────────────────────────────────

    def test_is_duplicate_by_url(self) -> None:
        item = _make_raw(url="https://example.com/exact")
        with _tmp_store() as store:
            store.mark_seen(item)
            # Duplicate if the URL matches even when the title differs.
            duplicate = _make_raw(title="Different Title", url="https://example.com/exact")
            assert store.is_duplicate(duplicate) is True

    def test_is_not_duplicate_new_url(self) -> None:
        item = _make_raw(url="https://example.com/a")
        embedder = MagicMock(spec=Embedder)
        # Return different vectors.
        embedder.embed.side_effect = [_unit_vec(seed=1), _unit_vec(seed=99)]
        with _tmp_store(embedder=embedder) as store:
            store.mark_seen(item)
            new_item = _make_raw(title="Totally different", url="https://example.com/b")
            assert store.is_duplicate(new_item) is False

    # ── Embedding duplicates ─────────────────────────────────

    def test_is_duplicate_by_embedding(self) -> None:
        same_vec = _unit_vec(seed=7)
        embedder = MagicMock(spec=Embedder)
        embedder.embed.return_value = same_vec
        embedder.embed_batch.return_value = np.stack([same_vec])

        item = _make_raw(title="GPT-5 announced by OpenAI")
        duplicate = _make_raw(
            title="OpenAI announces GPT-5",  # Different title, different URL, same vector
            url="https://example.com/other",
        )
        with _tmp_store(threshold=0.92, embedder=embedder) as store:
            store.mark_seen(item)
            assert store.is_duplicate(duplicate) is True

    def test_is_not_duplicate_different_embedding(self) -> None:
        vec_a = _unit_vec(seed=1)
        vec_b = _unit_vec(seed=99)  # Nearly orthogonal

        embedder = MagicMock(spec=Embedder)
        embedder.embed.side_effect = [vec_a, vec_b, vec_b]
        embedder.embed_batch.return_value = np.stack([vec_a])

        item = _make_raw(title="Paper about reinforcement learning")
        new_item = _make_raw(title="Postgres 17 released", url="https://example.com/pg")

        with _tmp_store(threshold=0.92, embedder=embedder) as store:
            store.mark_seen(item)
            assert store.is_duplicate(new_item) is False

    # ── filter_new ────────────────────────────────────────────

    def test_filter_new_removes_duplicates(self) -> None:
        seen = _make_raw(title="GPT-5", url="https://example.com/gpt5")
        fresh = _make_raw(title="New ArXiv paper", url="https://arxiv.org/abs/2401.00001")

        seen_vec = _unit_vec(seed=1)
        fresh_vec = _unit_vec(seed=99)

        embedder = MagicMock(spec=Embedder)
        # mark_seen(seen) -> seen_vec
        # is_duplicate(seen) -> URL hit, no embedding call
        # is_duplicate(fresh) -> URL miss -> embed -> fresh_vec
        embedder.embed.side_effect = [seen_vec, fresh_vec]
        embedder.embed_batch.return_value = np.stack([seen_vec])

        with _tmp_store(embedder=embedder) as store:
            store.mark_seen(seen)
            result = store.filter_new([seen, fresh])

        assert len(result) == 1
        assert result[0].url == "https://arxiv.org/abs/2401.00001"

    def test_filter_new_empty_input(self) -> None:
        with _tmp_store() as store:
            assert store.filter_new([]) == []

    # ── mark_seen_batch ───────────────────────────────────────

    def test_mark_seen_batch(self) -> None:
        items = [
            _make_raw("Item A", "https://example.com/a"),
            _make_raw("Item B", "https://example.com/b"),
            _make_raw("Item C", "https://example.com/c"),
        ]
        vec = _unit_vec()
        embedder = MagicMock(spec=Embedder)
        embedder.embed_batch.return_value = np.stack([vec, vec, vec])

        with _tmp_store(embedder=embedder) as store:
            store.mark_seen_batch(items)
            assert store.count() == 3

    def test_mark_seen_batch_empty(self) -> None:
        with _tmp_store() as store:
            store.mark_seen_batch([])
            assert store.count() == 0

    # ── Threshold boundary ────────────────────────────────────

    def test_threshold_boundary_just_below(self) -> None:
        """Should not be duplicate when similarity is just below the threshold."""
        base_vec = _unit_vec(seed=0)
        # threshold=0.92, create a vector with similarity 0.91
        noise = np.zeros(384, dtype=np.float32)
        noise[0] = 1.0
        noise = noise / np.linalg.norm(noise)
        slightly_different = base_vec * 0.91 + noise * np.sqrt(1 - 0.91**2)
        slightly_different = slightly_different / np.linalg.norm(slightly_different)

        embedder = MagicMock(spec=Embedder)
        embedder.embed.side_effect = [base_vec, slightly_different]
        embedder.embed_batch.return_value = np.stack([base_vec])

        item = _make_raw("Original title")
        candidate = _make_raw("Slightly different title", url="https://example.com/diff")

        with _tmp_store(threshold=0.92, embedder=embedder) as store:
            store.mark_seen(item)
            assert store.is_duplicate(candidate) is False
