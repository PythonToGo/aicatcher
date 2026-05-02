"""ThreadsPublisher — Post thread sequences to Meta Threads via the Threads API."""

from __future__ import annotations

import logging

import httpx

from newsbot.distribution.base import BasePublisher
from newsbot.formatting.threads import ThreadsFormatter
from newsbot.models import Report

logger = logging.getLogger(__name__)

_THREADS_API_BASE = "https://graph.threads.net/v1.0"


class ThreadsPublisher(BasePublisher):
    """Threads publisher using Meta's Threads API."""

    def __init__(
        self,
        access_token: str,
        user_id: str,
        dry_run: bool = False,
        formatter: ThreadsFormatter | None = None,
    ) -> None:
        self._access_token = access_token
        self._user_id = user_id
        self._dry_run = dry_run
        self._formatter = formatter or ThreadsFormatter()

    @property
    def channel_name(self) -> str:
        return "threads"

    def publish(self, report: Report) -> None:
        posts = self._formatter.format(report)
        if self._dry_run:
            self._log_dry_run(report)
            for i, post in enumerate(posts, 1):
                logger.info("[DRY_RUN][threads] post %d/%d: %s", i, len(posts), post[:80])
            return

        if not self._access_token or not self._user_id:
            logger.warning("[threads] missing access token or user id, skipping publish")
            return

        try:
            post_ids = self._post_thread(posts)
            logger.info(
                "[threads] posted %d-part thread for %s | root_id=%s",
                len(post_ids),
                report.report_id,
                post_ids[0] if post_ids else "?",
            )
            self._log_published(report)
        except httpx.HTTPError as exc:
            logger.error("[threads] failed to post thread for %s: %s", report.report_id, exc)
            raise

    def _post_thread(self, posts: list[str]) -> list[str]:
        post_ids: list[str] = []
        reply_to: str | None = None

        with httpx.Client(timeout=20.0) as client:
            for post_text in posts:
                creation_id = self._create_text_container(client, post_text, reply_to)
                post_id = self._publish_container(client, creation_id)
                post_ids.append(post_id)
                reply_to = post_id

        return post_ids

    def _create_text_container(self, client: httpx.Client, text: str, reply_to: str | None) -> str:
        url = f"{_THREADS_API_BASE}/{self._user_id}/threads"
        payload: dict[str, str] = {
            "media_type": "TEXT",
            "text": text,
            "access_token": self._access_token,
        }
        if reply_to:
            payload["reply_to_id"] = reply_to

        resp = client.post(url, data=payload)
        resp.raise_for_status()
        return str(resp.json()["id"])

    def _publish_container(self, client: httpx.Client, creation_id: str) -> str:
        url = f"{_THREADS_API_BASE}/{self._user_id}/threads_publish"
        payload = {
            "creation_id": creation_id,
            "access_token": self._access_token,
        }
        resp = client.post(url, data=payload)
        resp.raise_for_status()
        return str(resp.json()["id"])
