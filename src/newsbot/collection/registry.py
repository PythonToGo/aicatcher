"""CollectorRegistry — runs registered collectors in parallel via asyncio.gather."""

import asyncio
import logging

from newsbot.collection.base import BaseCollector
from newsbot.models import RawItem

logger = logging.getLogger(__name__)


class CollectorRegistry:
    """Manages a list of collectors and runs them in parallel."""

    def __init__(self) -> None:
        self._collectors: list[BaseCollector] = []

    def register(self, collector: BaseCollector) -> None:
        self._collectors.append(collector)
        logger.debug("registered collector: %s", collector.source_name)

    async def collect_all(self) -> list[RawItem]:
        """Run all registered collectors in parallel and merge results.

        Individual collector failures are logged as warnings and skipped.
        """
        if not self._collectors:
            logger.warning("no collectors registered")
            return []

        results = await asyncio.gather(
            *[c.collect() for c in self._collectors],
            return_exceptions=True,
        )

        items: list[RawItem] = []
        for collector, result in zip(self._collectors, results):
            if isinstance(result, BaseException):
                logger.warning(
                    "[%s] collector raised exception: %s",
                    collector.source_name,
                    result,
                )
                continue
            items.extend(result)

        logger.info("collect_all: total %d items from %d collectors", len(items), len(self._collectors))
        return items


def build_registry(pipeline_mode: str = "news", **kwargs: object) -> CollectorRegistry:
    """Return a CollectorRegistry configured for the given pipeline_mode.

    Args:
        pipeline_mode: "news" | "new_paper" | "classic_paper"
        **kwargs: forwarded to individual collector constructors where applicable
            - api_key: Semantic Scholar API key (classic_paper mode)
    """
    registry = CollectorRegistry()

    if pipeline_mode == "news":
        from newsbot.collection.hackernews import HackerNewsCollector
        registry.register(HackerNewsCollector())
        # Reddit / RSS collectors registered here in future phases

    elif pipeline_mode == "new_paper":
        from newsbot.collection.arxiv import ArxivCollector
        registry.register(ArxivCollector(max_results=50, hours_back=168))  # past 7 days
        # HuggingFace Papers collector registered here in future phases

    elif pipeline_mode == "classic_paper":
        from newsbot.collection.semantic_scholar import SemanticScholarCollector
        registry.register(
            SemanticScholarCollector(
                limit=10,
                api_key=str(kwargs.get("api_key", "")),
            )
        )

    else:
        logger.warning(
            "unknown pipeline_mode '%s', falling back to news collectors", pipeline_mode
        )
        from newsbot.collection.hackernews import HackerNewsCollector
        registry.register(HackerNewsCollector())

    return registry


def build_default_registry() -> CollectorRegistry:
    """Backward-compatible alias — returns the news registry."""
    return build_registry("news")
