"""TwitterFormatter — Convert a Report into an X(Twitter) thread.

- Up to 8 tweets per thread
- Each tweet must be <= 280 chars, with URLs always counted as 23 chars
- Thread structure: headline tweet + item tweets + closing tweet
"""

from __future__ import annotations

from newsbot.formatting.base import BaseFormatter
from newsbot.models import AnalyzedItem, Report

_MAX_TWEET_LEN = 280
_URL_LEN = 23       # Twitter t.co shortened URL length (always fixed).
_MAX_TWEETS = 8


def _tweet_len(text: str) -> int:
    """Return tweet length using Twitter's URL counting rules."""
    import re
    url_pattern = re.compile(r"https?://\S+")
    urls = url_pattern.findall(text)
    length = len(text)
    for url in urls:
        length = length - len(url) + _URL_LEN
    return length


def _fit_text(text: str, max_len: int) -> str:
    """Trim text to max_len and append '…' if truncation occurs."""
    if _tweet_len(text) <= max_len:
        return text
    # Shrink one character at a time.
    while _tweet_len(text + "…") > max_len and text:
        text = text[:-1]
    return text + "…"


def _format_item_tweet(item: AnalyzedItem, index: int, total: int) -> str:
    """Format a single item as tweet text."""
    num = f"({index}/{total}) "
    available = _MAX_TWEET_LEN - len(num) - _URL_LEN - 2  # \n\n
    summary = _fit_text(item.summary_ko, available)
    return f"{num}{summary}\n\n{item.url}"


def _format_new_paper_tweet(item: AnalyzedItem, index: int, total: int) -> str:
    """Format a research paper tweet: title + methodology snippet + URL."""
    num = f"({index}/{total}) "
    methodology = item.extra.get("methodology", "") or item.summary_ko
    available = _MAX_TWEET_LEN - len(num) - _URL_LEN - 4
    snippet = _fit_text(methodology, available)
    return f"{num}{item.title}\n\n{snippet}\n\n{item.url}"


def _format_classic_tweets(report: Report) -> list[str]:
    """Render a classic paper as a 3-tweet thread."""
    item = report.items[0]
    why = item.extra.get("why_groundbreaking", "") or item.context
    learning = item.extra.get("learning_points", "") or item.implications

    tweets: list[str] = []

    # Tweet 1: headline + summary
    t1_body = f"📚 클래식 논문 리뷰\n\n{report.headline}\n\n{item.summary_ko}\n\n(1/3)"
    tweets.append(_fit_text(t1_body, _MAX_TWEET_LEN))

    # Tweet 2: why groundbreaking
    t2_body = f"(2/3) 왜 혁신적이었나\n\n{why}"
    tweets.append(_fit_text(t2_body, _MAX_TWEET_LEN))

    # Tweet 3: learning points + URL
    first_two_lines = "\n".join(learning.splitlines()[:4]) if learning else ""
    t3_body = f"(3/3) 오늘날 배울 점\n\n{first_two_lines}\n\n{item.url}"
    tweets.append(_fit_text(t3_body, _MAX_TWEET_LEN))

    return tweets


class TwitterFormatter(BaseFormatter):
    """Convert a Report into a tweet thread (mode-aware)."""

    def __init__(self, max_items: int = 5, max_tweets: int = _MAX_TWEETS) -> None:
        self._max_items = max_items
        self._max_tweets = max_tweets

    def format(self, report: Report) -> list[str]:
        """Dispatch to the correct thread format based on report.pipeline_mode."""
        if report.pipeline_mode == "classic_paper":
            return _format_classic_tweets(report)
        if report.pipeline_mode == "new_paper":
            return self._format_new_paper(report)
        return self._format_news(report)

    def _format_news(self, report: Report) -> list[str]:
        """Original news thread format."""
        tweets: list[str] = []
        item_slots = min(self._max_tweets - 2, self._max_items, len(report.items))
        items = report.items[:item_slots]
        total = item_slots + 2

        trend_snippet = _fit_text(
            report.trend_analysis,
            _MAX_TWEET_LEN - len(report.headline) - len(f"\n\n (1/{total})") - 2,
        )
        tweets.append(_fit_text(
            f"{report.headline}\n\n{trend_snippet}\n\n(1/{total})",
            _MAX_TWEET_LEN,
        ))

        for i, item in enumerate(items, start=2):
            tweets.append(_format_item_tweet(item, i, total))

        tweets.append(_fit_text(
            f"({total}/{total}) 더 깊은 분석은 Substack에서 →\n\n#AI #MachineLearning #LLM",
            _MAX_TWEET_LEN,
        ))
        return tweets

    def _format_new_paper(self, report: Report) -> list[str]:
        """Weekly research paper thread."""
        tweets: list[str] = []
        item_slots = min(self._max_tweets - 2, self._max_items, len(report.items))
        items = report.items[:item_slots]
        total = item_slots + 2

        trend_snippet = _fit_text(
            report.trend_analysis,
            _MAX_TWEET_LEN - len(report.headline) - len(f"\n\n (1/{total})") - 10,
        )
        tweets.append(_fit_text(
            f"📄 이번 주 신논문 {len(items)}편\n\n{report.headline}\n\n{trend_snippet}\n\n(1/{total})",
            _MAX_TWEET_LEN,
        ))

        for i, item in enumerate(items, start=2):
            tweets.append(_format_new_paper_tweet(item, i, total))

        tweets.append(_fit_text(
            f"({total}/{total}) 전체 논문 분석은 뉴스레터에서 →\n\n#AIResearch #MachineLearning #Papers",
            _MAX_TWEET_LEN,
        ))
        return tweets


def split_into_tweets(text: str, max_len: int = _MAX_TWEET_LEN) -> list[str]:
    """Split long text into tweet-sized chunks while respecting word boundaries."""
    if _tweet_len(text) <= max_len:
        return [text]

    paragraphs = text.split("\n\n")
    tweets: list[str] = []
    current = ""

    for para in paragraphs:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if _tweet_len(candidate) <= max_len:
            current = candidate
        else:
            if current:
                tweets.append(current)
            # If the paragraph itself is too long, split it by words.
            if _tweet_len(para) > max_len:
                words = para.split()
                chunk = ""
                for word in words:
                    trial = f"{chunk} {word}".strip()
                    if _tweet_len(trial) <= max_len:
                        chunk = trial
                    else:
                        if chunk:
                            tweets.append(chunk)
                        chunk = word
                if chunk:
                    current = chunk
            else:
                current = para

    if current:
        tweets.append(current)

    return tweets
