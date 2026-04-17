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


class TwitterFormatter(BaseFormatter):
    """Convert a Report into a tweet thread."""

    def __init__(self, max_items: int = 5, max_tweets: int = _MAX_TWEETS) -> None:
        self._max_items = max_items
        self._max_tweets = max_tweets

    def format(self, report: Report) -> list[str]:
        """Convert a Report into a list of tweets.

        Structure:
          [0] Headline + trend summary (1/N)
          [1..N-1] Per-item tweets
          [-1] Closing tweet with source guidance
        """
        tweets: list[str] = []

        # Determine how many item slots are available after headline and closing tweets.
        item_slots = min(self._max_tweets - 2, self._max_items, len(report.items))
        items = report.items[:item_slots]
        total = item_slots + 2  # headline + items + closing

        # 1. Headline tweet.
        trend_snippet = _fit_text(
            report.trend_analysis,
            _MAX_TWEET_LEN - len(report.headline) - len(f"\n\n (1/{total})") - 2,
        )
        headline_tweet = f"{report.headline}\n\n{trend_snippet}\n\n(1/{total})"
        tweets.append(_fit_text(headline_tweet, _MAX_TWEET_LEN))

        # 2. Per-item tweets.
        for i, item in enumerate(items, start=2):
            tweet = _format_item_tweet(item, i, total)
            tweets.append(tweet)

        # 3. Closing tweet.
        closing = (
            f"({total}/{total}) 더 깊은 분석은 Substack에서 →\n\n"
            "#AI #MachineLearning #LLM"
        )
        tweets.append(_fit_text(closing, _MAX_TWEET_LEN))

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
