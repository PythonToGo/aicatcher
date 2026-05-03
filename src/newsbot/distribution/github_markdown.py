"""GitHubMarkdownPublisher — Commit a Report markdown file into a GitHub repo."""

from __future__ import annotations

import base64
import logging
import os
import re
from urllib.parse import quote

import httpx

from newsbot.distribution.base import BasePublisher
from newsbot.models import Report
from newsbot.monitoring.summary import build_report_md

logger = logging.getLogger(__name__)

_GH_API = "https://api.github.com"
_SSH_REPO_RE = re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$")
_HTTPS_REPO_RE = re.compile(r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")


def _parse_repo(repo_url: str) -> tuple[str, str]:
    repo_url = repo_url.strip()
    for pattern in (_SSH_REPO_RE, _HTTPS_REPO_RE):
        match = pattern.match(repo_url)
        if match:
            return match.group("owner"), match.group("repo")
    raise ValueError(f"unsupported GitHub repo URL: {repo_url}")


def _build_archive_path(report: Report) -> str:
    date_part = f"{report.report_id[:4]}/{report.report_id[4:6]}/{report.report_id[6:8]}"
    return f"news/{date_part}/{report.report_id}-{report.language}.md"


class GitHubMarkdownPublisher(BasePublisher):
    """Commit a report markdown file into a target GitHub repository."""

    def __init__(
        self,
        repo_url: str,
        branch: str = "main",
        token: str | None = None,
        dry_run: bool = False,
    ) -> None:
        self._repo_url = repo_url
        self._owner, self._repo = _parse_repo(repo_url)
        self._branch = branch
        # GITHUB_TOKEN is intentionally excluded: it only has access to the
        # current repository and will always fail for cross-repo archives.
        self._token = (
            token
            or os.environ.get("ARCHIVE_GITHUB_TOKEN", "")
            or os.environ.get("GITHUB_ARCHIVE_TOKEN", "")
        )
        self._dry_run = dry_run

    @property
    def channel_name(self) -> str:
        return "github_markdown"

    def publish(self, report: Report) -> bool:
        if self._dry_run:
            self._log_dry_run(report)
            logger.info(
                "[DRY_RUN][github] would commit %s into %s@%s",
                _build_archive_path(report),
                f"{self._owner}/{self._repo}",
                self._branch,
            )
            return True

        if not self._token:
            logger.warning(
                "[github] no archive token set, skipping markdown archive for %s@%s",
                f"{self._owner}/{self._repo}",
                self._branch,
            )
            return False

        try:
            commit_url = self._commit_report(report)
            logger.info("[github] archived report %s → %s", report.report_id, commit_url)
            self._log_published(report)
            return True
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500] if exc.response is not None else ""
            logger.error(
                "[github] failed to commit report %s: status=%s repo=%s branch=%s body=%s",
                report.report_id,
                exc.response.status_code if exc.response is not None else "?",
                f"{self._owner}/{self._repo}",
                self._branch,
                body,
            )
            raise
        except httpx.HTTPError as exc:
            logger.error("[github] failed to commit report %s: %s", report.report_id, exc)
            raise

    def _commit_report(self, report: Report) -> str:
        path = _build_archive_path(report)
        url = f"{_GH_API}/repos/{self._owner}/{self._repo}/contents/{quote(path)}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        content = build_report_md(report).encode("utf-8")
        payload: dict = {
            "message": f"archive: {report.report_id} {report.headline}",
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self._branch,
        }

        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            # If the file already exists (e.g. re-run within the same minute),
            # the GitHub API requires the current file's sha to overwrite it.
            get_resp = client.get(url, headers=headers, params={"ref": self._branch})
            if get_resp.status_code == 200:
                existing_sha = get_resp.json().get("sha", "")
                if existing_sha:
                    payload["sha"] = existing_sha
                    logger.info("[github] file already exists — overwriting with sha %s", existing_sha[:7])

            resp = client.put(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return str(data.get("commit", {}).get("html_url", ""))
