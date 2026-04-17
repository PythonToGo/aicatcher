"""BaseFormatter — Channel-specific formatter ABC."""

from abc import ABC, abstractmethod

from newsbot.models import Report


class BaseFormatter(ABC):
    """Convert a Report into channel-specific strings."""

    @abstractmethod
    def format(self, report: Report) -> list[str]:
        """Convert a Report into a list of strings for a channel.

        Returns:
            - Twitter: list of tweets (each <= 280 chars)
            - WhatsApp: list of messages
            - Substack: single-item list containing html_body
        """
        ...
