"""ThreadsFormatter — Convert a Report into a Threads post sequence.

- Up to 6 posts per thread
- Each post must be <= 500 chars
- Structure: English headline post + item posts + closing post
"""

from __future__ import annotations

import re

from newsbot.formatting.base import BaseFormatter
from newsbot.models import AnalyzedItem, Report

_MAX_THREADS_POST_LEN = 500
_MAX_POSTS = 6


def _fit_text(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _english_snippet(item: AnalyzedItem, max_len: int) -> str:
    source_text = item.scored.full_article or item.scored.raw.body or item.title
    source_text = _normalize_whitespace(source_text)
    if not source_text:
        source_text = item.title
    return _fit_text(source_text, max_len)


def _headline_from_items(items: list[AnalyzedItem]) -> str:
    if not items:
        return "AI/ML Briefing"
    if len(items) == 1:
        return items[0].title
    lead = items[0].title
    return _fit_text(f"{lead} and {len(items) - 1} more AI updates", 120)


def _format_item_post(item: AnalyzedItem, index: int, total: int) -> str:
    prefix = f"({index}/{total}) "
    suffix = f"\n\n{item.url}"
    available = _MAX_THREADS_POST_LEN - len(prefix) - len(suffix)
    title = _fit_text(item.title, min(available, 180))
    remaining = max(0, available - len(title) - 4)
    snippet = _english_snippet(item, remaining)
    body = title if not snippet else f"{title}\n\n{snippet}"
    return f"{prefix}{body}{suffix}"


class ThreadsFormatter(BaseFormatter):
    """Convert a Report into an English Threads thread without extra LLM calls."""

    def __init__(self, max_items: int = 4, max_posts: int = _MAX_POSTS) -> None:
        self._max_items = max_items
        self._max_posts = max_posts

    def format(self, report: Report) -> list[str]:
        posts: list[str] = []

        item_slots = min(self._max_posts - 2, self._max_items, len(report.items))
        items = report.items[:item_slots]
        total = item_slots + 2

        headline = _headline_from_items(items or report.items)
        intro = "Top AI stories worth tracking right now."
        posts.append(_fit_text(f"{headline}\n\n{intro}\n\n(1/{total})", _MAX_THREADS_POST_LEN))

        for i, item in enumerate(items, start=2):
            posts.append(_format_item_post(item, i, total))

        closing = (
            f"({total}/{total}) Full archive is available on GitHub.\n\n"
            "#AI #LLM #MachineLearning"
        )
        posts.append(_fit_text(closing, _MAX_THREADS_POST_LEN))

        return posts
