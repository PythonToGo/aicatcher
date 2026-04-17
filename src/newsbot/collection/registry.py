"""CollectorRegistry — runs registered collectors in parallel via asyncio.gather."""

import asyncio
import logging

from newsbot.collection.base import BaseCollector
from newsbot.models import RawItem

logger = logging.getLogger(__name__)


class CollectorRegistry:
    """Manages a list of collectors and runs them in parallel.

    Example:
        registry = CollectorRegistry()
        registry.register(HackerNewsCollector())
        registry.register(ArxivCollector())
        items = await registry.collect_all()
    """

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


def build_default_registry() -> CollectorRegistry:
    """Return the default Phase 1 collector set."""
    from newsbot.collection.arxiv import ArxivCollector
    from newsbot.collection.hackernews import HackerNewsCollector

    registry = CollectorRegistry()
    registry.register(HackerNewsCollector())
    registry.register(ArxivCollector())
    return registry
