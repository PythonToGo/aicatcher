"""GitHubIssuePublisher — Archive a Report as a GitHub Issue.

Authenticate with GITHUB_TOKEN inside the Actions workflow.
When DRY_RUN=true, log output instead of making API calls.
"""

from __future__ import annotations

import logging
import os

import httpx

from newsbot.distribution.base import BasePublisher
from newsbot.models import Report

logger = logging.getLogger(__name__)

_GH_API = "https://api.github.com"


def _format_issue_body(report: Report) -> str:
    """Convert a Report into a GitHub Issue markdown body."""
    lines: list[str] = [
        f"# {report.headline}",
        f"\n> ID: `{report.report_id}` | "
        f"생성: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')} | "
        f"언어: {report.language} | 아이템: {len(report.items)}개",
        f"\n## 트렌드 분석\n\n{report.trend_analysis}",
        "\n## 아이템 목록\n",
    ]

    for i, item in enumerate(report.items, 1):
        lines.append(f"### {i}. [{item.title}]({item.url})")
        lines.append(f"**점수**: {item.score} | **출처**: {item.scored.raw.source}")
        lines.append(f"\n{item.summary_ko}")
        lines.append(f"\n**맥락**: {item.context}")
        lines.append(f"\n**시사점**: {item.implications}")
        lines.append(f"\n**한계**: {item.limitations}\n")

    return "\n".join(lines)


class GitHubIssuePublisher(BasePublisher):
    """Archive a Report as a GitHub Issue."""

    def __init__(
        self,
        repo: str,                    # "owner/repo" format
        token: str | None = None,     # Use the GITHUB_TOKEN environment variable when None
        dry_run: bool = False,
        label: str = "newsletter",
    ) -> None:
        self._repo = repo
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._dry_run = dry_run
        self._label = label

    @property
    def channel_name(self) -> str:
        return "github_issue"

    def publish(self, report: Report) -> None:
        if self._dry_run:
            self._log_dry_run(report)
            logger.info("[DRY_RUN][github] would create issue: %s", report.headline)
            return

        if not self._token:
            logger.warning("[github] GITHUB_TOKEN not set, skipping archive")
            return

        try:
            issue_url = self._create_issue(report)
            logger.info("[github] archived report %s → %s", report.report_id, issue_url)
            self._log_published(report)
        except httpx.HTTPError as exc:
            logger.error("[github] failed to create issue for %s: %s", report.report_id, exc)
            raise

    def _create_issue(self, report: Report) -> str:
        url = f"{_GH_API}/repos/{self._repo}/issues"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        payload = {
            "title": f"[{report.report_id}] {report.headline}",
            "body": _format_issue_body(report),
            "labels": [self._label],
        }

        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return str(resp.json().get("html_url", ""))
