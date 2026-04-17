"""BaseCollector — abstract base class that every collector must implement."""

import logging
from abc import ABC, abstractmethod

from newsbot.models import RawItem

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Abstract base class for all collectors.

    Rules:
    - collect() must be async.
    - Individual item parse failures are logged and skipped (pipeline must not abort).
    - All external API calls must be wrapped in try/except.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Collector identifier stored in RawItem.source."""
        ...

    @abstractmethod
    async def collect(self) -> list[RawItem]:
        """Collect and return items. Return an empty list on failure."""
        ...

    def _log_collected(self, count: int) -> None:
        logger.info("[%s] collected %d items", self.source_name, count)

    def _log_error(self, msg: str, exc: Exception) -> None:
        logger.warning("[%s] %s: %s", self.source_name, msg, exc)
