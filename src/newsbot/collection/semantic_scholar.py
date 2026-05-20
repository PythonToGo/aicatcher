"""SemanticScholarCollector — curated classic AI/ML papers for the classic_paper pipeline.

Strategy (seed-first):
  1. Load the curated seed list from data/classic_papers_seed.json.
  2. Use ISO week number to rotate through the seed in batches, ensuring variety
     across weekly runs without explicit state.
  3. Fall back to the Semantic Scholar Search API when the seed batch is not enough.

The deduplication store in the main pipeline handles "don't republish" logic,
so the collector simply returns a pool of candidates.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

from newsbot.collection.base import BaseCollector
from newsbot.models import RawItem

logger = logging.getLogger(__name__)

_SEED_PATH = Path(__file__).parent.parent.parent.parent / "data" / "classic_papers_seed.json"
_S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_S2_FIELDS = "title,abstract,year,citationCount,url,externalIds,venue,authors"
# Papers older than this year are considered "classic"
_MAX_YEAR = 2021
# Minimum citation threshold for API fallback
_MIN_CITATIONS = 500
# Candidates returned per batch from seed
_SEED_BATCH_SIZE = 10


def _load_seed() -> list[dict]:
    try:
        return json.loads(_SEED_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[semantic_scholar] failed to load seed: %s", exc)
        return []


def _seed_batch(seed: list[dict], batch_size: int) -> list[dict]:
    """Return a batch from the seed based on the current ISO week number.

    Rotates through the seed deterministically so each week presents different papers.
    """
    if not seed:
        return []
    week = datetime.now(timezone.utc).isocalendar()[1]
    start = (week * batch_size) % len(seed)
    # wrap around if batch crosses list boundary
    indices = [(start + i) % len(seed) for i in range(batch_size)]
    return [seed[i] for i in indices]


def _seed_to_raw(paper: dict) -> RawItem | None:
    try:
        title = paper.get("title", "").strip()
        url = paper.get("url", "").strip()
        if not title or not url:
            return None
        abstract = paper.get("abstract", "") or ""
        year = paper.get("year", 0)
        citation_count = paper.get("citation_count", 0)
        venue = paper.get("venue", "")
        authors = paper.get("authors", [])
        published_at = datetime(year or 2000, 1, 1, tzinfo=timezone.utc)
        return RawItem(
            title=title,
            url=url,
            body=abstract[:1500] if abstract else f"Classic paper: {title}",
            source="semantic_scholar",
            published_at=published_at,
            raw_score=float(min(citation_count / 1000.0, 10.0)),
            content_type="classic_paper",
            metadata={
                "year": year,
                "citation_count": citation_count,
                "venue": venue,
                "authors": authors[:3] if isinstance(authors, list) else [],
            },
        )
    except Exception as exc:
        logger.warning("[semantic_scholar] failed to parse seed entry: %s", exc)
        return None


def _api_paper_to_raw(paper: dict) -> RawItem | None:
    try:
        title = (paper.get("title") or "").strip()
        year = paper.get("year") or 0
        citations = paper.get("citationCount") or 0
        abstract = (paper.get("abstract") or "").strip()

        if not title or year > _MAX_YEAR or citations < _MIN_CITATIONS:
            return None

        # Prefer arXiv URL, fall back to Semantic Scholar page
        external_ids = paper.get("externalIds") or {}
        arxiv_id = external_ids.get("ArXiv")
        url = (
            f"https://arxiv.org/abs/{arxiv_id}"
            if arxiv_id
            else f"https://www.semanticscholar.org/paper/{paper.get('paperId', '')}"
        )

        venue = (paper.get("venue") or "").strip()
        authors = [
            (a.get("name") or "").strip()
            for a in (paper.get("authors") or [])
        ][:3]

        published_at = datetime(year or 2000, 1, 1, tzinfo=timezone.utc)

        return RawItem(
            title=title,
            url=url,
            body=abstract[:1500] if abstract else f"Classic paper: {title}",
            source="semantic_scholar",
            published_at=published_at,
            raw_score=float(min(citations / 1000.0, 10.0)),
            content_type="classic_paper",
            metadata={
                "year": year,
                "citation_count": citations,
                "venue": venue,
                "authors": authors,
            },
        )
    except Exception as exc:
        logger.warning("[semantic_scholar] failed to parse API paper: %s", exc)
        return None


class SemanticScholarCollector(BaseCollector):
    """Collect classic AI/ML paper candidates from seed list + Semantic Scholar API."""

    def __init__(
        self,
        limit: int = _SEED_BATCH_SIZE,
        api_key: str = "",
        timeout: float = 15.0,
    ) -> None:
        self._limit = limit
        self._api_key = api_key
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(1)  # 1 req/s — public rate limit
        self._seed = _load_seed()

    @property
    def source_name(self) -> str:
        return "semantic_scholar"

    async def collect(self) -> list[RawItem]:
        batch = _seed_batch(self._seed, self._limit)
        items: list[RawItem] = []
        for paper in batch:
            item = _seed_to_raw(paper)
            if item is not None:
                items.append(item)

        if len(items) < self._limit:
            # Seed batch insufficient → try API
            extra = await self._fetch_from_api(self._limit - len(items))
            items.extend(extra)

        self._log_collected(len(items))
        return items

    async def _fetch_from_api(self, needed: int) -> list[RawItem]:
        headers: dict[str, str] = {}
        if self._api_key:
            headers["x-api-key"] = self._api_key

        queries = [
            "deep learning neural network",
            "transformer attention mechanism",
            "reinforcement learning policy gradient",
        ]
        results: list[RawItem] = []

        async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as client:
            for query in queries:
                if len(results) >= needed:
                    break
                try:
                    async with self._semaphore:
                        resp = await client.get(
                            _S2_SEARCH_URL,
                            params={
                                "query": query,
                                "fields": _S2_FIELDS,
                                "limit": 20,
                                "publicationDateOrYear": f"-{_MAX_YEAR}",
                            },
                        )
                        resp.raise_for_status()
                    data = resp.json()
                    for paper in data.get("data", []):
                        item = _api_paper_to_raw(paper)
                        if item is not None:
                            results.append(item)
                            if len(results) >= needed:
                                break
                except Exception as exc:
                    logger.warning(
                        "[semantic_scholar] API fetch failed for query '%s': %s", query, exc
                    )

        return results
