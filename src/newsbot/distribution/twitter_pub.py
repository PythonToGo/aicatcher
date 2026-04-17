"""TwitterPublisher — Post threads to X(Twitter) with the tweepy v2 client.

When DRY_RUN=true, log output instead of making API calls.
"""

from __future__ import annotations

import logging
import time

import tweepy

from newsbot.distribution.base import BasePublisher
from newsbot.formatting.twitter import TwitterFormatter
from newsbot.models import Report

logger = logging.getLogger(__name__)

_TWEET_DELAY_SEC = 1.0  # Delay between tweets to reduce rate-limit risk.


class TwitterPublisher(BasePublisher):
    """X(Twitter) thread publisher."""

    def __init__(
        self,
        bearer_token: str,
        api_key: str,
        api_secret: str,
        access_token: str,
        access_secret: str,
        dry_run: bool = False,
        formatter: TwitterFormatter | None = None,
    ) -> None:
        self._dry_run = dry_run
        self._formatter = formatter or TwitterFormatter()
        self._client = tweepy.Client(
            bearer_token=bearer_token,
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret,
            wait_on_rate_limit=True,
        )

    @property
    def channel_name(self) -> str:
        return "twitter"

    def publish(self, report: Report) -> None:
        if self._dry_run:
            self._log_dry_run(report)
            tweets = self._formatter.format(report)
            for i, tweet in enumerate(tweets, 1):
                logger.info("[DRY_RUN][twitter] tweet %d/%d: %s", i, len(tweets), tweet[:80])
            return

        tweets = self._formatter.format(report)
        if not tweets:
            logger.warning("[twitter] formatter returned empty tweet list for %s", report.report_id)
            return

        try:
            thread_ids = self._post_thread(tweets)
            logger.info(
                "[twitter] posted %d-tweet thread for %s | root_id=%s",
                len(thread_ids), report.report_id, thread_ids[0] if thread_ids else "?",
            )
            self._log_published(report)
        except tweepy.TweepyException as exc:
            logger.error("[twitter] failed to post thread for %s: %s", report.report_id, exc)
            raise

    def _post_thread(self, tweets: list[str]) -> list[str]:
        """Post a list of tweets as a thread and return the tweet IDs."""
        thread_ids: list[str] = []
        reply_to: str | None = None

        for tweet_text in tweets:
            try:
                kwargs: dict = {"text": tweet_text}
                if reply_to:
                    kwargs["in_reply_to_tweet_id"] = reply_to

                response = self._client.create_tweet(**kwargs)
                tweet_id = str(response.data["id"])
                thread_ids.append(tweet_id)
                reply_to = tweet_id

                if len(tweets) > 1:
                    time.sleep(_TWEET_DELAY_SEC)

            except tweepy.TweepyException as exc:
                logger.error("[twitter] tweet %d failed: %s | text: %s", len(thread_ids) + 1, exc, tweet_text[:80])
                raise

        return thread_ids
