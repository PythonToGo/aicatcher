"""HackerNews collector — uses the Firebase REST API.

- Filters Top 500 stories by score > 100 and AI/ML keyword match
- Parallel item fetch via asyncio.gather
- Individual item failures are skipped
"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from newsbot.collection.base import BaseCollector
from newsbot.models import RawItem

logger = logging.getLogger(__name__)

_HN_BASE = "https://hacker-news.firebaseio.com/v0"
_TOP_STORIES_URL = f"{_HN_BASE}/topstories.json"
_ITEM_URL = f"{_HN_BASE}/item/{{item_id}}.json"

# stories below this score are excluded
_MIN_SCORE = 100

# any of these keywords in the title (case-insensitive) qualifies as AI/ML
_AI_KEYWORDS = {
    "ai", "ml", "llm", "gpt", "claude", "gemini", "openai", "anthropic",
    "machine learning", "deep learning", "neural", "transformer", "diffusion",
    "reinforcement learning", "rl", "nlp", "computer vision", "embedding",
    "fine-tun", "inference", "model", "dataset", "benchmark", "agent",
    "multimodal", "rag", "retrieval", "foundation model", "language model",
    "mistral", "llama", "stable diffusion", "hugging face", "huggingface",
}


def _is_ai_related(title: str) -> bool:
    lower = title.lower()
    return any(kw in lower for kw in _AI_KEYWORDS)


class HackerNewsCollector(BaseCollector):
    """Collects AI/ML-related items from HN Top Stories."""

    def __init__(
        self,
        min_score: int = _MIN_SCORE,
        max_items: int = 30,
        timeout: float = 10.0,
    ) -> None:
        self._min_score = min_score
        self._max_items = max_items
        self._timeout = timeout

    @property
    def source_name(self) -> str:
        return "hackernews"

    async def collect(self) -> list[RawItem]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                story_ids = await self._fetch_top_ids(client)
                items = await self._fetch_items(client, story_ids)
        except Exception as exc:
            self._log_error("failed to fetch top stories", exc)
            return []

        self._log_collected(len(items))
        return items

    async def _fetch_top_ids(self, client: httpx.AsyncClient) -> list[int]:
        try:
            resp = await client.get(_TOP_STORIES_URL)
            resp.raise_for_status()
            ids: list[int] = resp.json()
            # only consider the top 500 (older ones are less relevant)
            return ids[:500]
        except Exception as exc:
            self._log_error("failed to fetch top story IDs", exc)
            raise

    async def _fetch_items(
        self, client: httpx.AsyncClient, story_ids: list[int]
    ) -> list[RawItem]:
        tasks = [self._fetch_single(client, sid) for sid in story_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        items: list[RawItem] = []
        for result in results:
            if isinstance(result, Exception):
                logger.debug("[hackernews] item fetch failed: %s", result)
                continue
            if result is not None:
                items.append(result)
            if len(items) >= self._max_items:
                break
        return items

    async def _fetch_single(
        self, client: httpx.AsyncClient, item_id: int
    ) -> RawItem | None:
        try:
            resp = await client.get(_ITEM_URL.format(item_id=item_id))
            resp.raise_for_status()
            data: dict = resp.json()
        except Exception as exc:
            self._log_error(f"item {item_id} fetch error", exc)
            raise

        return self._parse(data)

    def _parse(self, data: dict) -> RawItem | None:
        """Convert a HN item dict to RawItem. Returns None when criteria are not met."""
        # only collect story type (skip job, ask, comment)
        if data.get("type") != "story":
            return None

        title: str = data.get("title", "").strip()
        url: str = data.get("url", "").strip()
        score: int = data.get("score", 0)

        if not title or not url:
            return None
        if score < self._min_score:
            return None
        if not _is_ai_related(title):
            return None

        published_at = datetime.fromtimestamp(
            data.get("time", 0), tz=timezone.utc
        )
        text: str = data.get("text", "") or ""  # Ask HN posts may have body text

        return RawItem(
            title=title,
            url=url,
            body=text or f"HackerNews discussion with {score} points.",
            source=self.source_name,
            published_at=published_at,
            raw_score=float(score),
            metadata={
                "hn_id": data.get("id"),
                "comments": data.get("descendants", 0),
                "author": data.get("by", ""),
            },
        )
