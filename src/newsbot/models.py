"""Data contracts for the full pipeline — RawItem → ScoredItem → AnalyzedItem → Report."""

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RawItem:
    title: str
    url: str
    body: str           # article summary or lead paragraph
    source: str         # "hackernews" | "arxiv" | "reddit" | "rss" | "github" | "huggingface"
    published_at: datetime
    raw_score: float    # source-native score (HN points, arXiv citations, upvotes, etc.)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.title:
            raise ValueError("RawItem.title must not be empty")
        if not self.url:
            raise ValueError("RawItem.url must not be empty")
        if not self.source:
            raise ValueError("RawItem.source must not be empty")


@dataclass
class ScoredItem:
    raw: RawItem
    score: float        # 1.0 – 10.0 (Claude 4-axis scoring)
    score_reason: str
    full_article: str = ""  # filled by Fetcher; falls back to raw.body on failure

    def __post_init__(self) -> None:
        if not (1.0 <= self.score <= 10.0):
            raise ValueError(f"ScoredItem.score must be between 1.0 and 10.0, got {self.score}")


@dataclass
class AnalyzedItem:
    scored: ScoredItem
    summary_ko: str
    context: str        # background context — why this news matters now
    implications: str   # practical implications for practitioners
    limitations: str    # limitations and open questions
    related_urls: list[str] = field(default_factory=list)

    # convenience properties
    @property
    def title(self) -> str:
        return self.scored.raw.title

    @property
    def url(self) -> str:
        return self.scored.raw.url

    @property
    def score(self) -> float:
        return self.scored.score


@dataclass
class Report:
    report_id: str              # YYYYMMDD-HHMM
    items: list[AnalyzedItem]
    headline: str
    trend_analysis: str
    thumbnail_path: str = ""
    language: str = "ko"        # "ko" | "en" (Phase 2)
    generated_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.report_id:
            raise ValueError("Report.report_id must not be empty")
        if not self.items:
            raise ValueError("Report.items must not be empty")

    @property
    def top_item(self) -> AnalyzedItem:
        return max(self.items, key=lambda i: i.score)
