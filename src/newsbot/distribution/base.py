"""BasePublisher — Channel-specific publisher ABC."""

import logging
from abc import ABC, abstractmethod

from newsbot.models import Report

logger = logging.getLogger(__name__)


class BasePublisher(ABC):
    """Abstract base class for publishers.

    Implementation rules:
    - Add a DRY_RUN branch at the top of publish().
    - Wrap all real API calls in try/except blocks.
    """

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Channel identifier used for logging."""
        ...

    @abstractmethod
    def publish(self, report: Report) -> bool:
        """Publish the report to the target channel. Returns True on success."""
        ...

    def _log_dry_run(self, report: Report) -> None:
        logger.info("[DRY_RUN][%s] would publish report %s", self.channel_name, report.report_id)

    def _log_published(self, report: Report) -> None:
        logger.info("[%s] published report %s", self.channel_name, report.report_id)
