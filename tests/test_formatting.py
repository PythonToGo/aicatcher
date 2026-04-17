"""Unit tests for the formatting and distribution layers."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from newsbot.distribution.github_issue import GitHubIssuePublisher, _format_issue_body
from newsbot.distribution.twitter_pub import TwitterPublisher
from newsbot.formatting.twitter import (
    TwitterFormatter,
    _fit_text,
    _tweet_len,
    split_into_tweets,
)
from newsbot.models import AnalyzedItem, RawItem, Report, ScoredItem


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_raw(title: str = "GPT-5 released", url: str = "https://example.com/gpt5") -> RawItem:
    return RawItem(
        title=title, url=url, body="body",
        source="hackernews", published_at=datetime.now(timezone.utc), raw_score=200.0,
    )


def _make_analyzed(title: str = "GPT-5 released", score: float = 8.0) -> AnalyzedItem:
    scored = ScoredItem(raw=_make_raw(title), score=score, score_reason="High impact.")
    return AnalyzedItem(
        scored=scored,
        summary_ko="GPT-5가 출시되어 AI 업계에 큰 반향을 일으키고 있습니다.",
        context="OpenAI 최신 모델.",
        implications="즉시 활용 가능.",
        limitations="가격이 높음.",
    )


def _make_report(n_items: int = 3) -> Report:
    items = [_make_analyzed(f"Item {i}", score=max(1.0, float(10 - i))) for i in range(1, n_items + 1)]
    return Report(
        report_id="20260417-0800",
        items=items,
        headline="AI 추론 비용 전쟁이 시작됐다",
        trend_analysis="이번 주 AI 업계는 추론 비용 절감에 집중했습니다. " * 3,
    )


# ── _tweet_len ────────────────────────────────────────────────────────────────

class TestTweetLen:
    def test_plain_text(self) -> None:
        assert _tweet_len("hello world") == 11

    def test_url_counts_as_23(self) -> None:
        url = "https://example.com/very/long/url/path"
        text = f"Check this out: {url}"
        expected = len("Check this out: ") + 23
        assert _tweet_len(text) == expected

    def test_multiple_urls(self) -> None:
        text = "https://a.com https://b.com"
        assert _tweet_len(text) == 23 + 1 + 23  # space between

    def test_korean_text(self) -> None:
        assert _tweet_len("안녕하세요") == 5


# ── _fit_text ─────────────────────────────────────────────────────────────────

class TestFitText:
    def test_short_text_unchanged(self) -> None:
        assert _fit_text("hello", 280) == "hello"

    def test_long_text_truncated(self) -> None:
        long = "a" * 300
        result = _fit_text(long, 280)
        assert _tweet_len(result) <= 280
        assert result.endswith("…")

    def test_exactly_at_limit(self) -> None:
        text = "a" * 280
        result = _fit_text(text, 280)
        assert result == text


# ── split_into_tweets ─────────────────────────────────────────────────────────

class TestSplitIntoTweets:
    def test_short_text_single_tweet(self) -> None:
        result = split_into_tweets("Short text.", 280)
        assert len(result) == 1
        assert result[0] == "Short text."

    def test_splits_on_paragraph_boundary(self) -> None:
        para1 = "A" * 200
        para2 = "B" * 200
        text = f"{para1}\n\n{para2}"
        result = split_into_tweets(text, 280)
        assert len(result) == 2
        assert result[0] == para1
        assert result[1] == para2

    def test_splits_on_word_boundary(self) -> None:
        words = ("word " * 100).strip()
        result = split_into_tweets(words, 100)
        for tweet in result:
            assert _tweet_len(tweet) <= 100


# ── TwitterFormatter ──────────────────────────────────────────────────────────

class TestTwitterFormatter:
    def test_format_returns_list(self) -> None:
        formatter = TwitterFormatter()
        report = _make_report()
        tweets = formatter.format(report)
        assert isinstance(tweets, list)
        assert len(tweets) >= 2  # At minimum: headline + closing

    def test_all_tweets_within_limit(self) -> None:
        formatter = TwitterFormatter()
        report = _make_report(n_items=5)
        tweets = formatter.format(report)
        for i, tweet in enumerate(tweets):
            assert _tweet_len(tweet) <= 280, f"tweet {i} exceeds 280: {_tweet_len(tweet)}"

    def test_max_tweets_respected(self) -> None:
        formatter = TwitterFormatter(max_tweets=4)
        report = _make_report(n_items=10)
        tweets = formatter.format(report)
        assert len(tweets) <= 4

    def test_headline_in_first_tweet(self) -> None:
        formatter = TwitterFormatter()
        report = _make_report()
        tweets = formatter.format(report)
        assert report.headline in tweets[0]

    def test_last_tweet_has_hashtags(self) -> None:
        formatter = TwitterFormatter()
        report = _make_report()
        tweets = formatter.format(report)
        assert "#AI" in tweets[-1]

    def test_item_urls_in_tweets(self) -> None:
        formatter = TwitterFormatter(max_items=2)
        report = _make_report(n_items=2)
        all_text = "\n".join(formatter.format(report))
        for item in report.items[:2]:
            assert item.url in all_text

    def test_empty_items_graceful(self) -> None:
        """Handle the case gracefully without crashing."""
        formatter = TwitterFormatter(max_items=0)
        report = Report(
            report_id="20260417-0800",
            items=[_make_analyzed()],
            headline="테스트",
            trend_analysis="트렌드 분석입니다.",
        )
        tweets = formatter.format(report)
        assert len(tweets) >= 1


# ── GitHubIssuePublisher ──────────────────────────────────────────────────────

class TestFormatIssueBody:
    def test_contains_headline(self) -> None:
        report = _make_report()
        body = _format_issue_body(report)
        assert report.headline in body

    def test_contains_all_item_titles(self) -> None:
        report = _make_report(n_items=3)
        body = _format_issue_body(report)
        for item in report.items:
            assert item.title in body

    def test_contains_report_id(self) -> None:
        report = _make_report()
        body = _format_issue_body(report)
        assert report.report_id in body


class TestGitHubIssuePublisher:
    def test_dry_run_does_not_call_api(self) -> None:
        report = _make_report()
        publisher = GitHubIssuePublisher(repo="owner/repo", token="tok", dry_run=True)

        with patch("httpx.Client") as mock_cls:
            publisher.publish(report)
            mock_cls.assert_not_called()

    def test_skips_when_no_token(self) -> None:
        report = _make_report()
        publisher = GitHubIssuePublisher(repo="owner/repo", token="", dry_run=False)

        with patch("httpx.Client") as mock_cls:
            publisher.publish(report)
            mock_cls.assert_not_called()

    def test_calls_api_with_correct_endpoint(self) -> None:
        report = _make_report()
        publisher = GitHubIssuePublisher(repo="owner/repo", token="mytoken", dry_run=False)

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"html_url": "https://github.com/owner/repo/issues/1"}

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client

            publisher.publish(report)

            call_args = mock_client.post.call_args
            assert "owner/repo/issues" in call_args[0][0]
            payload = call_args[1]["json"]
            assert report.headline in payload["title"]


# ── TwitterPublisher ──────────────────────────────────────────────────────────

class TestTwitterPublisher:
    def _make_publisher(self, dry_run: bool = True) -> TwitterPublisher:
        return TwitterPublisher(
            bearer_token="bt", api_key="ak", api_secret="as",
            access_token="at", access_secret="as2",
            dry_run=dry_run,
        )

    def test_dry_run_does_not_call_tweepy(self) -> None:
        publisher = self._make_publisher(dry_run=True)
        report = _make_report()

        with patch.object(publisher._client, "create_tweet") as mock_tweet:
            publisher.publish(report)
            mock_tweet.assert_not_called()

    def test_publish_calls_create_tweet(self) -> None:
        publisher = self._make_publisher(dry_run=False)
        report = _make_report()

        mock_resp = MagicMock()
        mock_resp.data = {"id": "123456"}

        with patch.object(publisher._client, "create_tweet", return_value=mock_resp) as mock_tweet:
            publisher.publish(report)
            assert mock_tweet.call_count >= 2  # At minimum: headline + closing

    def test_publish_builds_thread(self) -> None:
        """Set in_reply_to_tweet_id starting from the second tweet."""
        publisher = self._make_publisher(dry_run=False)
        report = _make_report(n_items=1)

        call_num = 0
        responses = [MagicMock(data={"id": str(i)}) for i in range(10)]

        def fake_create_tweet(**kwargs):
            nonlocal call_num
            resp = responses[call_num]
            call_num += 1
            return resp

        with patch.object(publisher._client, "create_tweet", side_effect=fake_create_tweet):
            publisher.publish(report)

        # Verify that at least two tweets were posted: headline + closing.
        assert call_num >= 2

    def test_channel_name(self) -> None:
        assert self._make_publisher().channel_name == "twitter"
