"""Fetcher — fetches the full article text from a URL.

- httpx AsyncClient + BeautifulSoup4
- Falls back silently to ScoredItem.raw.body on failure (pipeline never aborts)
- Maximum content length is configurable to control token cost
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from newsbot.models import ScoredItem

logger = logging.getLogger(__name__)

_FETCH_TIMEOUT = 15.0
_FETCH_CONCURRENCY = 5

# skip fetching these domains (PDFs, large files, etc.)
_SKIP_DOMAINS = {
    "arxiv.org",   # abs pages are fine but PDFs are skipped
    "twitter.com",
    "x.com",
    "github.com",  # use body description instead of README
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; newsbot/1.0; +https://github.com/ai-catcher)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
}


def _should_skip(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
        return any(host.endswith(d) for d in _SKIP_DOMAINS)
    except Exception:
        return False


class Fetcher:
    """Fetches full article text for a list of ScoredItems in parallel."""

    def __init__(
        self,
        timeout: float = _FETCH_TIMEOUT,
        concurrency: int = _FETCH_CONCURRENCY,
        max_content_length: int = 4000,
    ) -> None:
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(concurrency)
        self._max_content_length = max_content_length

    async def fetch_all(self, items: list[ScoredItem]) -> list[ScoredItem]:
        """Fetch all items in parallel. Falls back to raw.body on failure."""
        tasks = [self._fetch_one(item) for item in items]
        await asyncio.gather(*tasks, return_exceptions=True)
        return items

    def _extract_text(self, html: bytes) -> str:
        """Extract body text from HTML."""
        soup = BeautifulSoup(html, "lxml")

        # remove noise elements
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()

        # prefer <article> / <main> over <body>
        for selector in ("article", "main", "[role=main]", "body"):
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator=" ", strip=True)
                if len(text) > 200:
                    return text[: self._max_content_length]

        return soup.get_text(separator=" ", strip=True)[: self._max_content_length]

    async def _fetch_one(self, item: ScoredItem) -> None:
        """Write item.full_article on success; keep raw.body on failure."""
        url = item.raw.url
        if _should_skip(url):
            logger.debug("[fetcher] skipping domain: %s", url)
            item.full_article = item.raw.body
            return

        async with self._semaphore:
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout,
                    follow_redirects=True,
                    headers=_HEADERS,
                ) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    content_type = resp.headers.get("content-type", "")
                    if "text/html" not in content_type:
                        logger.debug("[fetcher] non-HTML content-type: %s", content_type)
                        item.full_article = item.raw.body
                        return
                    text = self._extract_text(resp.content)
                    item.full_article = text or item.raw.body
                    logger.debug("[fetcher] fetched %d chars from %s", len(text), url)
            except Exception as exc:
                logger.warning("[fetcher] failed to fetch %s: %s", url, exc)
                item.full_article = item.raw.body  # fallback
