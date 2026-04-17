"""DeduplicationStore — SQLite-backed seen_items store with cosine-similarity duplicate detection.

Schema:
    seen_items(id, url, title, embedding BLOB, source, seen_at)

Duplicate detection:
    1. Exact URL match  → immediate duplicate (O(1))
    2. Embedding cosine similarity >= threshold → semantic duplicate
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from newsbot.dedup.embedder import Embedder, cosine_similarity
from newsbot.models import RawItem

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/newsbot.db")
_DEFAULT_THRESHOLD = 0.92

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS seen_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT    NOT NULL UNIQUE,
    title       TEXT    NOT NULL,
    embedding   BLOB    NOT NULL,
    source      TEXT    NOT NULL,
    seen_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_seen_items_url ON seen_items(url);
CREATE INDEX IF NOT EXISTS idx_seen_items_seen_at ON seen_items(seen_at);
"""


def _vec_to_blob(vec: NDArray[np.float32]) -> bytes:
    return vec.astype(np.float32).tobytes()


def _blob_to_vec(blob: bytes) -> NDArray[np.float32]:
    return np.frombuffer(blob, dtype=np.float32)


class DeduplicationStore:
    """Checks RawItem duplicates and manages the seen_items table."""

    def __init__(
        self,
        db_path: Path = _DEFAULT_DB_PATH,
        threshold: float = _DEFAULT_THRESHOLD,
        embedder: Embedder | None = None,
    ) -> None:
        self._db_path = db_path
        self._threshold = threshold
        self._embedder = embedder or Embedder()
        self._conn: sqlite3.Connection | None = None

    # connection management

    def connect(self) -> None:
        """Open the DB connection and initialise the schema."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        logger.debug("connected to DB: %s", self._db_path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> DeduplicationStore:
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    @property
    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("DeduplicationStore is not connected. Call connect() first.")
        return self._conn

    # public API

    def is_duplicate(self, item: RawItem) -> bool:
        """Return True if the item is a duplicate by URL or embedding similarity."""
        # fast path: exact URL match
        if self._url_exists(item.url):
            logger.debug("duplicate by URL: %s", item.url)
            return True

        # slow path: embedding similarity scan
        embedding = self._embedder.embed(item.title)
        if self._similar_exists(embedding):
            logger.debug("duplicate by embedding: %s", item.title)
            return True

        return False

    def filter_new(self, items: list[RawItem]) -> list[RawItem]:
        """Return only items that are not duplicates."""
        new_items = [item for item in items if not self.is_duplicate(item)]
        logger.info("dedup: %d/%d items are new", len(new_items), len(items))
        return new_items

    def mark_seen(self, item: RawItem) -> None:
        """Insert a single item into seen_items."""
        embedding = self._embedder.embed(item.title)
        now = datetime.now(timezone.utc).isoformat()
        try:
            self._db.execute(
                "INSERT OR IGNORE INTO seen_items (url, title, embedding, source, seen_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (item.url, item.title, _vec_to_blob(embedding), item.source, now),
            )
            self._db.commit()
        except sqlite3.Error as exc:
            logger.warning("failed to mark item as seen: %s", exc)

    def mark_seen_batch(self, items: list[RawItem]) -> None:
        """Insert multiple items at once using embed_batch for efficiency."""
        if not items:
            return
        titles = [item.title for item in items]
        embeddings = self._embedder.embed_batch(titles)
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (item.url, item.title, _vec_to_blob(emb), item.source, now)
            for item, emb in zip(items, embeddings)
        ]
        try:
            self._db.executemany(
                "INSERT OR IGNORE INTO seen_items (url, title, embedding, source, seen_at) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            self._db.commit()
        except sqlite3.Error as exc:
            logger.warning("failed to mark batch as seen: %s", exc)

    def count(self) -> int:
        """Return the total number of entries in seen_items."""
        row = self._db.execute("SELECT COUNT(*) FROM seen_items").fetchone()
        return int(row[0])

    # private helpers

    def _url_exists(self, url: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM seen_items WHERE url = ? LIMIT 1", (url,)
        ).fetchone()
        return row is not None

    def _similar_exists(self, embedding: NDArray[np.float32]) -> bool:
        """Return True if any stored embedding exceeds the similarity threshold."""
        rows = self._db.execute("SELECT embedding FROM seen_items").fetchall()
        for row in rows:
            stored = _blob_to_vec(row["embedding"])
            if cosine_similarity(embedding, stored) >= self._threshold:
                return True
        return False
