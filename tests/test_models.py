"""Unit tests for models.py: RawItem, ScoredItem, AnalyzedItem, and Report."""

import pytest
from datetime import datetime, timezone

from newsbot.models import AnalyzedItem, RawItem, Report, ScoredItem


def make_raw(
    title: str = "Test Title",
    url: str = "https://example.com",
    source: str = "hackernews",
    raw_score: float = 150.0,
) -> RawItem:
    return RawItem(
        title=title,
        url=url,
        body="Test body text.",
        source=source,
        published_at=datetime.now(timezone.utc),
        raw_score=raw_score,
    )


def make_scored(raw: RawItem | None = None, score: float = 7.5) -> ScoredItem:
    return ScoredItem(raw=raw or make_raw(), score=score, score_reason="High impact research.")


def make_analyzed(scored: ScoredItem | None = None) -> AnalyzedItem:
    return AnalyzedItem(
        scored=scored or make_scored(),
        summary_ko="테스트 요약입니다.",
        context="배경 설명.",
        implications="실무 시사점.",
        limitations="한계점.",
    )


# ── RawItem ───────────────────────────────────────────────────────────────────

class TestRawItem:
    def test_valid_creation(self) -> None:
        item = make_raw()
        assert item.title == "Test Title"
        assert item.source == "hackernews"
        assert item.metadata == {}

    def test_empty_title_raises(self) -> None:
        with pytest.raises(ValueError, match="title"):
            make_raw(title="")

    def test_empty_url_raises(self) -> None:
        with pytest.raises(ValueError, match="url"):
            make_raw(url="")

    def test_empty_source_raises(self) -> None:
        with pytest.raises(ValueError, match="source"):
            make_raw(source="")

    def test_metadata_default_is_empty_dict(self) -> None:
        a = make_raw()
        b = make_raw()
        a.metadata["key"] = "value"
        assert b.metadata == {}, "metadata default_factory must not be shared"


# ── ScoredItem ────────────────────────────────────────────────────────────────

class TestScoredItem:
    def test_valid_score_boundary(self) -> None:
        assert make_scored(score=1.0).score == 1.0
        assert make_scored(score=10.0).score == 10.0

    def test_score_below_range_raises(self) -> None:
        with pytest.raises(ValueError, match="1.0 and 10.0"):
            make_scored(score=0.9)

    def test_score_above_range_raises(self) -> None:
        with pytest.raises(ValueError, match="1.0 and 10.0"):
            make_scored(score=10.1)

    def test_full_article_defaults_empty(self) -> None:
        item = make_scored()
        assert item.full_article == ""


# ── AnalyzedItem ──────────────────────────────────────────────────────────────

class TestAnalyzedItem:
    def test_convenience_properties(self) -> None:
        item = make_analyzed()
        assert item.title == "Test Title"
        assert item.url == "https://example.com"
        assert item.score == 7.5

    def test_related_urls_default_empty(self) -> None:
        a = make_analyzed()
        b = make_analyzed()
        a.related_urls.append("https://example.com")
        assert b.related_urls == [], "related_urls default_factory must not be shared"


# ── Report ────────────────────────────────────────────────────────────────────

class TestReport:
    def make_report(self, items: list[AnalyzedItem] | None = None) -> Report:
        return Report(
            report_id="20260417-0800",
            items=items or [make_analyzed()],
            headline="AI 주간 브리핑",
            trend_analysis="이번 주 핵심 트렌드.",
        )

    def test_valid_creation(self) -> None:
        report = self.make_report()
        assert report.report_id == "20260417-0800"
        assert report.language == "ko"
        assert report.thumbnail_path == ""

    def test_empty_report_id_raises(self) -> None:
        with pytest.raises(ValueError, match="report_id"):
            Report(report_id="", items=[make_analyzed()], headline="h", trend_analysis="t")

    def test_empty_items_raises(self) -> None:
        with pytest.raises(ValueError, match="items"):
            Report(report_id="20260417-0800", items=[], headline="h", trend_analysis="t")

    def test_top_item_returns_highest_score(self) -> None:
        low = make_analyzed(make_scored(score=3.0))
        high = make_analyzed(make_scored(score=9.0))
        mid = make_analyzed(make_scored(score=6.0))
        report = self.make_report(items=[low, high, mid])
        assert report.top_item.score == 9.0

    def test_generated_at_is_timezone_aware(self) -> None:
        report = self.make_report()
        assert report.generated_at.tzinfo is not None
