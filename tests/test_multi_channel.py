"""tests/test_multi_channel.py — Phase F: multi-channel pipeline coverage.

Tests Phases A–E additions:
  - RawItem.content_type validation
  - AnalyzedItem.extra field
  - Report.pipeline_mode field
  - Settings: pipeline_mode validator + effective_items_per_report routing
  - Scorer: mode-aware _load_prompt, _build_content cache_control
  - Analyzer: mode-aware limits, extra keys populated
  - Synthesizer: mode-aware prompt, Report.pipeline_mode set
  - SemanticScholarCollector: seed loading, rotation, content_type, API fallback
  - build_registry(mode): correct collector per mode + backward-compat alias
  - TwitterFormatter: classic_paper→3 tweets, new_paper→📄, news→#AI closing
  - format_classic_paper_md: sections conditional on extra fields
  - format_classic_paper_html: green header, badge text
  - format_email_html: routing per mode
  - build_report_md: routing per mode
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from newsbot.models import AnalyzedItem, RawItem, Report, ScoredItem


# ── Shared helpers ────────────────────────────────────────────────────────────

def _raw(content_type: str = "news", **kwargs) -> RawItem:
    defaults = dict(
        title="Attention Is All You Need",
        url="https://arxiv.org/abs/1706.03762",
        body="Transformer architecture with self-attention.",
        source="arxiv",
        published_at=datetime(2017, 6, 12, tzinfo=timezone.utc),
        raw_score=50000.0,
    )
    defaults.update(kwargs)
    return RawItem(**defaults, content_type=content_type)


def _scored(content_type: str = "news") -> ScoredItem:
    return ScoredItem(raw=_raw(content_type), score=9.0, score_reason="landmark paper")


def _analyzed(pipeline_mode: str = "news", extra: dict | None = None) -> AnalyzedItem:
    ct = pipeline_mode if pipeline_mode != "news" else "news"
    return AnalyzedItem(
        scored=_scored(content_type=ct),
        summary_ko="어텐션 메커니즘만으로 SOTA 달성.",
        context="RNN 없는 순수 어텐션 아키텍처.",
        implications="현대 LLM의 기반 아키텍처.",
        limitations="이차 복잡도 문제.",
        extra=extra or {},
    )


def _report(pipeline_mode: str = "news", extra: dict | None = None) -> Report:
    return Report(
        report_id="20260418-0900",
        items=[_analyzed(pipeline_mode, extra)],
        headline="Transformer 5주년",
        trend_analysis="어텐션 메커니즘이 AI를 바꿨다.",
        pipeline_mode=pipeline_mode,
    )


# ── RawItem.content_type ──────────────────────────────────────────────────────

class TestRawItemContentType:
    def test_default_is_news(self) -> None:
        assert _raw().content_type == "news"

    def test_new_paper_accepted(self) -> None:
        assert _raw(content_type="new_paper").content_type == "new_paper"

    def test_classic_paper_accepted(self) -> None:
        assert _raw(content_type="classic_paper").content_type == "classic_paper"

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="content_type"):
            _raw(content_type="thesis")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="content_type"):
            _raw(content_type="")


# ── AnalyzedItem.extra ────────────────────────────────────────────────────────

class TestAnalyzedItemExtra:
    def test_default_is_empty_dict(self) -> None:
        a, b = _analyzed(), _analyzed()
        a.extra["key"] = "value"
        assert b.extra == {}, "extra default_factory must not be shared"

    def test_set_on_creation(self) -> None:
        item = _analyzed(extra={"historical_context": "Google 2017"})
        assert item.extra["historical_context"] == "Google 2017"

    def test_extra_survives_round_trip(self) -> None:
        keys = {"methodology": "m", "contributions": "c", "benchmark_results": "b"}
        item = _analyzed(extra=keys)
        for k, v in keys.items():
            assert item.extra[k] == v


# ── Report.pipeline_mode ──────────────────────────────────────────────────────

class TestReportPipelineMode:
    def test_default_is_news(self) -> None:
        r = Report(
            report_id="20260418-0900",
            items=[_analyzed()],
            headline="h",
            trend_analysis="t",
        )
        assert r.pipeline_mode == "news"

    def test_classic_paper_stored(self) -> None:
        assert _report("classic_paper").pipeline_mode == "classic_paper"

    def test_new_paper_stored(self) -> None:
        assert _report("new_paper").pipeline_mode == "new_paper"


# ── Settings: pipeline_mode validator + effective_items_per_report ────────────

class TestSettingsPipelineMode:
    @staticmethod
    def _s(**kwargs):
        from newsbot.config import Settings
        return Settings(**kwargs)

    def test_default_pipeline_mode_is_news(self) -> None:
        assert self._s().pipeline_mode == "news"

    def test_all_valid_modes_accepted(self) -> None:
        for mode in ("news", "new_paper", "classic_paper"):
            s = self._s(pipeline_mode=mode)
            assert s.pipeline_mode == mode

    def test_invalid_mode_raises_validation_error(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._s(pipeline_mode="thesis")

    def test_effective_items_news(self) -> None:
        s = self._s(pipeline_mode="news", items_per_report=7)
        assert s.effective_items_per_report == 7

    def test_effective_items_new_paper(self) -> None:
        s = self._s(pipeline_mode="new_paper", items_per_new_paper=5)
        assert s.effective_items_per_report == 5

    def test_effective_items_classic(self) -> None:
        s = self._s(pipeline_mode="classic_paper", items_per_classic=1)
        assert s.effective_items_per_report == 1

    def test_effective_items_classic_ignores_items_per_report(self) -> None:
        s = self._s(pipeline_mode="classic_paper", items_per_report=10, items_per_classic=2)
        assert s.effective_items_per_report == 2


# ── Scorer: mode-aware prompt loading + cache_control ─────────────────────────

class TestScorerModeAware:
    def test_prompt_map_has_all_modes(self) -> None:
        from newsbot.scoring.scorer import _PROMPT_MAP
        for mode in ("news", "new_paper", "classic_paper"):
            assert mode in _PROMPT_MAP

    def test_prompt_map_filenames_differ(self) -> None:
        from newsbot.scoring.scorer import _PROMPT_MAP
        assert len(set(_PROMPT_MAP.values())) == 3, "each mode must use a distinct prompt file"

    def test_load_prompt_returns_two_strings(self) -> None:
        from newsbot.scoring.scorer import _load_prompt
        for mode in ("news", "new_paper", "classic_paper"):
            static, dynamic = _load_prompt(mode)
            assert isinstance(static, str)
            assert isinstance(dynamic, str)
            assert static or dynamic, f"both parts empty for mode={mode}"

    def test_build_content_static_gets_cache_control(self) -> None:
        from newsbot.scoring.scorer import _build_content
        blocks = _build_content("system prompt text", "item: {{title}}", _raw())
        assert len(blocks) == 2
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in blocks[1]

    def test_build_content_no_static_single_block_no_cache(self) -> None:
        from newsbot.scoring.scorer import _build_content
        blocks = _build_content("", "only dynamic {{title}}", _raw())
        assert len(blocks) == 1
        assert "cache_control" not in blocks[0]

    def test_build_content_injects_title_source_body(self) -> None:
        from newsbot.scoring.scorer import _build_content
        item = _raw()
        item.body = "X" * 1000
        blocks = _build_content("static", "{{title}} {{source}} {{body}}", item)
        joined = "".join(b["text"] for b in blocks)
        assert item.title in joined
        assert item.source in joined
        assert "X" * 800 in joined
        assert "X" * 801 not in joined

    def test_scorer_stores_pipeline_mode(self) -> None:
        from newsbot.scoring.scorer import Scorer
        for mode in ("news", "new_paper", "classic_paper"):
            scorer = Scorer(api_key="test-key", pipeline_mode=mode)
            assert scorer._pipeline_mode == mode


# ── Analyzer: mode-aware limits, extra keys, extra populated ──────────────────

class TestAnalyzerModeAware:
    def test_content_limits(self) -> None:
        from newsbot.generation.analyzer import (
            _content_limit,
            _CLASSIC_CONTENT_LIMIT,
            _NEW_PAPER_CONTENT_LIMIT,
            _DETAIL_CONTENT_LIMIT,
            _LIGHT_CONTENT_LIMIT,
        )
        assert _content_limit("classic_paper", "detail") == _CLASSIC_CONTENT_LIMIT
        assert _content_limit("new_paper", "detail") == _NEW_PAPER_CONTENT_LIMIT
        assert _content_limit("news", "detail") == _DETAIL_CONTENT_LIMIT
        assert _content_limit("news", "light") == _LIGHT_CONTENT_LIMIT
        # classic_paper ignores mode arg
        assert _content_limit("classic_paper", "light") == _CLASSIC_CONTENT_LIMIT

    def test_max_tokens(self) -> None:
        from newsbot.generation.analyzer import (
            _max_tokens,
            _CLASSIC_MAX_TOKENS,
            _NEW_PAPER_MAX_TOKENS,
            _DETAIL_MAX_TOKENS,
            _LIGHT_MAX_TOKENS,
        )
        assert _max_tokens("classic_paper", "detail") == _CLASSIC_MAX_TOKENS
        assert _max_tokens("new_paper", "detail") == _NEW_PAPER_MAX_TOKENS
        assert _max_tokens("news", "detail") == _DETAIL_MAX_TOKENS
        assert _max_tokens("news", "light") == _LIGHT_MAX_TOKENS

    def test_extra_keys_classic_paper(self) -> None:
        from newsbot.generation.analyzer import Analyzer
        a = Analyzer(api_key="k", pipeline_mode="classic_paper")
        assert set(a._extra_keys) == {"historical_context", "why_groundbreaking", "learning_points"}

    def test_extra_keys_new_paper(self) -> None:
        from newsbot.generation.analyzer import Analyzer
        a = Analyzer(api_key="k", pipeline_mode="new_paper")
        assert set(a._extra_keys) == {"methodology", "contributions", "benchmark_results"}

    def test_extra_keys_news(self) -> None:
        from newsbot.generation.analyzer import Analyzer
        assert Analyzer(api_key="k", pipeline_mode="news")._extra_keys == []

    @pytest.mark.asyncio
    async def test_analyze_all_populates_classic_extra_fields(self) -> None:
        from newsbot.generation.analyzer import Analyzer
        analyzer = Analyzer(api_key="k", pipeline_mode="classic_paper")
        item = _scored(content_type="classic_paper")

        resp_data = {
            "summary_ko": "요약.",
            "context": "맥락.",
            "implications": "시사점.",
            "limitations": "한계.",
            "related_urls": [],
            "historical_context": "2017년 Google Brain.",
            "why_groundbreaking": "RNN 완전 대체.",
            "learning_points": "어텐션 이해 필수.",
        }
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(resp_data))]

        with patch.object(analyzer._client.messages, "create", new_callable=AsyncMock) as m:
            m.return_value = mock_msg
            results = await analyzer.analyze_all([item])

        assert results[0].extra["historical_context"] == "2017년 Google Brain."
        assert results[0].extra["why_groundbreaking"] == "RNN 완전 대체."
        assert results[0].extra["learning_points"] == "어텐션 이해 필수."

    @pytest.mark.asyncio
    async def test_analyze_all_populates_new_paper_extra_fields(self) -> None:
        from newsbot.generation.analyzer import Analyzer
        analyzer = Analyzer(api_key="k", pipeline_mode="new_paper")
        item = _scored(content_type="new_paper")

        resp_data = {
            "summary_ko": "요약.",
            "context": "맥락.",
            "implications": "시사점.",
            "limitations": "한계.",
            "related_urls": [],
            "methodology": "Transformer encoder-decoder.",
            "contributions": "Scaled dot-product attention.",
            "benchmark_results": "WMT14: 28.4 BLEU.",
        }
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(resp_data))]

        with patch.object(analyzer._client.messages, "create", new_callable=AsyncMock) as m:
            m.return_value = mock_msg
            results = await analyzer.analyze_all([item])

        assert results[0].extra["methodology"] == "Transformer encoder-decoder."
        assert results[0].extra["benchmark_results"] == "WMT14: 28.4 BLEU."

    @pytest.mark.asyncio
    async def test_analyze_all_news_has_empty_extra(self) -> None:
        from newsbot.generation.analyzer import Analyzer
        analyzer = Analyzer(api_key="k", pipeline_mode="news")
        item = _scored()

        resp_data = {
            "summary_ko": "요약.",
            "context": "맥락.",
            "implications": "시사점.",
            "limitations": "한계.",
            "related_urls": [],
        }
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(resp_data))]

        with patch.object(analyzer._client.messages, "create", new_callable=AsyncMock) as m:
            m.return_value = mock_msg
            results = await analyzer.analyze_all([item])

        assert results[0].extra == {}


# ── Synthesizer: pipeline_mode propagated to Report ───────────────────────────

class TestSynthesizerModeAware:
    def test_max_tokens_classic_paper(self) -> None:
        from newsbot.generation.synthesizer import _max_tokens_for, _CLASSIC_MAX_TOKENS
        assert _max_tokens_for("classic_paper", "detail") == _CLASSIC_MAX_TOKENS

    def test_max_tokens_news_light_less_than_detail(self) -> None:
        from newsbot.generation.synthesizer import _max_tokens_for, _LIGHT_MAX_TOKENS, _DETAIL_MAX_TOKENS
        assert _max_tokens_for("news", "light") == _LIGHT_MAX_TOKENS
        assert _max_tokens_for("news", "detail") == _DETAIL_MAX_TOKENS
        assert _LIGHT_MAX_TOKENS < _DETAIL_MAX_TOKENS

    def test_prompt_map_has_all_modes(self) -> None:
        from newsbot.generation.synthesizer import _PROMPT_MAP
        for mode in ("news", "new_paper", "classic_paper"):
            assert mode in _PROMPT_MAP
        assert len(set(_PROMPT_MAP.values())) == 3

    @pytest.mark.asyncio
    async def test_synthesize_sets_pipeline_mode_on_report(self) -> None:
        from newsbot.generation.synthesizer import Synthesizer
        for mode in ("news", "new_paper", "classic_paper"):
            synth = Synthesizer(api_key="k", pipeline_mode=mode)
            items = [_analyzed(mode)]
            resp_data = {"headline": "Test headline", "trend_analysis": "Trend analysis text."}
            mock_msg = MagicMock()
            mock_msg.content = [MagicMock(text=json.dumps(resp_data))]

            with patch.object(synth._client.messages, "create", new_callable=AsyncMock) as m:
                m.return_value = mock_msg
                report = await synth.synthesize(items, report_id="20260418-0900")

            assert report.pipeline_mode == mode, f"expected {mode}, got {report.pipeline_mode}"


# ── SemanticScholarCollector ──────────────────────────────────────────────────

class TestSemanticScholarCollector:
    def test_load_seed_returns_nonempty_list(self) -> None:
        from newsbot.collection.semantic_scholar import _load_seed
        seed = _load_seed()
        assert isinstance(seed, list)
        assert len(seed) > 0

    def test_seed_batch_correct_size(self) -> None:
        from newsbot.collection.semantic_scholar import _seed_batch
        seed = [{"title": f"P{i}", "url": f"https://x.com/{i}"} for i in range(20)]
        assert len(_seed_batch(seed, 10)) == 10

    def test_seed_batch_wraps_around(self) -> None:
        from newsbot.collection.semantic_scholar import _seed_batch
        seed = [{"title": f"P{i}", "url": f"https://x.com/{i}"} for i in range(5)]
        batch = _seed_batch(seed, 8)
        assert len(batch) == 8
        # Check that all entries are from the seed (no None entries)
        assert all(b is not None for b in batch)

    def test_seed_batch_empty_seed_returns_empty(self) -> None:
        from newsbot.collection.semantic_scholar import _seed_batch
        assert _seed_batch([], 10) == []

    def test_seed_batch_deterministic_same_call(self) -> None:
        from newsbot.collection.semantic_scholar import _seed_batch
        seed = [{"title": f"P{i}", "url": f"https://x.com/{i}"} for i in range(20)]
        assert _seed_batch(seed, 5) == _seed_batch(seed, 5)

    def test_seed_to_raw_content_type_is_classic_paper(self) -> None:
        from newsbot.collection.semantic_scholar import _seed_to_raw
        paper = {
            "title": "Attention Is All You Need",
            "url": "https://arxiv.org/abs/1706.03762",
            "abstract": "Transformer architecture.",
            "year": 2017,
            "citation_count": 50000,
            "venue": "NeurIPS",
            "authors": ["Vaswani et al."],
        }
        item = _seed_to_raw(paper)
        assert item is not None
        assert item.content_type == "classic_paper"
        assert item.source == "semantic_scholar"

    def test_seed_to_raw_source_is_semantic_scholar(self) -> None:
        from newsbot.collection.semantic_scholar import _seed_to_raw
        item = _seed_to_raw({
            "title": "BERT",
            "url": "https://arxiv.org/abs/1810.04805",
            "year": 2018,
        })
        assert item is not None
        assert item.source == "semantic_scholar"

    def test_seed_to_raw_missing_title_returns_none(self) -> None:
        from newsbot.collection.semantic_scholar import _seed_to_raw
        assert _seed_to_raw({"url": "https://example.com"}) is None

    def test_seed_to_raw_missing_url_returns_none(self) -> None:
        from newsbot.collection.semantic_scholar import _seed_to_raw
        assert _seed_to_raw({"title": "Some Paper"}) is None

    def test_seed_to_raw_raw_score_from_citations(self) -> None:
        from newsbot.collection.semantic_scholar import _seed_to_raw
        item = _seed_to_raw({
            "title": "ResNet",
            "url": "https://arxiv.org/abs/1512.03385",
            "citation_count": 5000,
        })
        assert item is not None
        assert item.raw_score == pytest.approx(5.0)

    def test_seed_to_raw_raw_score_capped_at_10(self) -> None:
        from newsbot.collection.semantic_scholar import _seed_to_raw
        item = _seed_to_raw({
            "title": "BERT",
            "url": "https://arxiv.org/abs/1810.04805",
            "citation_count": 999999,
        })
        assert item is not None
        assert item.raw_score == pytest.approx(10.0)

    def test_collector_loads_seed_on_init(self) -> None:
        from newsbot.collection.semantic_scholar import SemanticScholarCollector
        c = SemanticScholarCollector()
        assert isinstance(c._seed, list)
        assert len(c._seed) > 0

    @pytest.mark.asyncio
    async def test_collect_returns_classic_paper_items(self) -> None:
        from newsbot.collection.semantic_scholar import SemanticScholarCollector
        c = SemanticScholarCollector(limit=3)
        items = await c.collect()
        assert isinstance(items, list)
        for item in items:
            assert item.content_type == "classic_paper"

    @pytest.mark.asyncio
    async def test_collect_api_fallback_on_insufficient_seed(self) -> None:
        """When seed is empty the collector must try the API."""
        from newsbot.collection.semantic_scholar import SemanticScholarCollector
        c = SemanticScholarCollector(limit=5)
        c._seed = []  # force seed to be empty

        api_paper = {
            "title": "Deep Residual Learning",
            "year": 2016,
            "citationCount": 80000,
            "abstract": "ResNet with skip connections.",
            "externalIds": {"ArXiv": "1512.03385"},
            "venue": "CVPR",
            "authors": [{"name": "He"}],
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": [api_paper]}

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client
            items = await c.collect()

        assert len(items) >= 1
        assert items[0].content_type == "classic_paper"


# ── build_registry mode routing ───────────────────────────────────────────────

class TestBuildRegistry:
    def _names(self, mode: str, **kw) -> list[str]:
        from newsbot.collection.registry import build_registry
        return [c.source_name for c in build_registry(mode, **kw)._collectors]

    def test_news_registers_hackernews(self) -> None:
        assert "hackernews" in self._names("news")

    def test_new_paper_registers_arxiv(self) -> None:
        assert "arxiv" in self._names("new_paper")

    def test_classic_paper_registers_semantic_scholar(self) -> None:
        assert "semantic_scholar" in self._names("classic_paper")

    def test_build_default_registry_is_news(self) -> None:
        from newsbot.collection.registry import build_default_registry
        names = [c.source_name for c in build_default_registry()._collectors]
        assert "hackernews" in names

    def test_classic_paper_passes_api_key(self) -> None:
        from newsbot.collection.registry import build_registry
        reg = build_registry("classic_paper", api_key="my-s2-key")
        assert reg._collectors[0]._api_key == "my-s2-key"

    def test_unknown_mode_falls_back_to_hackernews(self) -> None:
        assert "hackernews" in self._names("unknown_mode")


# ── TwitterFormatter mode dispatch ────────────────────────────────────────────

class TestTwitterFormatterModes:
    def test_classic_paper_returns_exactly_3_tweets(self) -> None:
        from newsbot.formatting.twitter import TwitterFormatter
        report = _report("classic_paper", extra={
            "why_groundbreaking": "RNN 완전 대체.",
            "learning_points": "어텐션 이해 필수.",
        })
        assert len(TwitterFormatter().format(report)) == 3

    def test_classic_paper_first_tweet_has_book_emoji(self) -> None:
        from newsbot.formatting.twitter import TwitterFormatter
        report = _report("classic_paper", extra={
            "why_groundbreaking": "혁신.",
            "learning_points": "배움.",
        })
        assert "📚" in TwitterFormatter().format(report)[0]

    def test_classic_paper_all_tweets_within_280(self) -> None:
        from newsbot.formatting.twitter import TwitterFormatter, _tweet_len
        report = _report("classic_paper", extra={
            "why_groundbreaking": "RNN을 대체한 어텐션 아키텍처로 SOTA 달성." * 4,
            "learning_points": "어텐션 메커니즘을 이해하면 LLM을 이해할 수 있다." * 4,
        })
        for i, t in enumerate(TwitterFormatter().format(report)):
            assert _tweet_len(t) <= 280, f"classic tweet {i} too long"

    def test_classic_paper_last_tweet_has_url(self) -> None:
        from newsbot.formatting.twitter import TwitterFormatter
        report = _report("classic_paper", extra={
            "why_groundbreaking": "혁신.",
            "learning_points": "배움.",
        })
        last = TwitterFormatter().format(report)[-1]
        assert report.items[0].url in last

    def test_new_paper_first_tweet_has_paper_emoji(self) -> None:
        from newsbot.formatting.twitter import TwitterFormatter
        report = _report("new_paper")
        assert "📄" in TwitterFormatter().format(report)[0]

    def test_new_paper_closing_has_ai_research_hashtag(self) -> None:
        from newsbot.formatting.twitter import TwitterFormatter
        report = _report("new_paper")
        assert "#AIResearch" in TwitterFormatter().format(report)[-1]

    def test_news_closing_has_ai_hashtag(self) -> None:
        from newsbot.formatting.twitter import TwitterFormatter
        report = _report("news")
        assert "#AI" in TwitterFormatter().format(report)[-1]

    def test_news_closing_does_not_have_paper_emoji(self) -> None:
        from newsbot.formatting.twitter import TwitterFormatter
        report = _report("news")
        first = TwitterFormatter().format(report)[0]
        assert "📄" not in first

    def test_new_paper_closing_not_classic_format(self) -> None:
        from newsbot.formatting.twitter import TwitterFormatter
        news_tweets = TwitterFormatter().format(_report("news"))
        new_paper_tweets = TwitterFormatter().format(_report("new_paper"))
        # New paper should have paper emoji in first; news should not
        assert "📄" not in news_tweets[0]
        assert "📄" in new_paper_tweets[0]


# ── format_classic_paper_md ───────────────────────────────────────────────────

class TestClassicPaperMd:
    def test_contains_classic_badge(self) -> None:
        from newsbot.formatting.classic_paper import format_classic_paper_md
        assert "클래식 논문 리뷰" in format_classic_paper_md(_report("classic_paper"))

    def test_trend_analysis_section_present(self) -> None:
        from newsbot.formatting.classic_paper import format_classic_paper_md
        assert "지금 이 논문을 읽어야 하는 이유" in format_classic_paper_md(_report("classic_paper"))

    def test_historical_context_section_present_when_set(self) -> None:
        from newsbot.formatting.classic_paper import format_classic_paper_md
        r = _report("classic_paper", extra={"historical_context": "2017년 Google Brain."})
        md = format_classic_paper_md(r)
        assert "역사적 배경" in md
        assert "2017년 Google Brain." in md

    def test_historical_context_section_absent_when_empty(self) -> None:
        from newsbot.formatting.classic_paper import format_classic_paper_md
        assert "역사적 배경" not in format_classic_paper_md(_report("classic_paper", extra={}))

    def test_why_groundbreaking_section_conditional(self) -> None:
        from newsbot.formatting.classic_paper import format_classic_paper_md
        with_why = _report("classic_paper", extra={"why_groundbreaking": "RNN 없는 아키텍처."})
        without_why = _report("classic_paper", extra={})
        assert "왜 혁신적이었는가" in format_classic_paper_md(with_why)
        assert "왜 혁신적이었는가" not in format_classic_paper_md(without_why)

    def test_learning_points_section_conditional(self) -> None:
        from newsbot.formatting.classic_paper import format_classic_paper_md
        with_lp = _report("classic_paper", extra={"learning_points": "어텐션 이해 필수."})
        without_lp = _report("classic_paper", extra={})
        assert "오늘날 배울 수 있는 것" in format_classic_paper_md(with_lp)
        assert "오늘날 배울 수 있는 것" not in format_classic_paper_md(without_lp)

    def test_report_id_in_output(self) -> None:
        from newsbot.formatting.classic_paper import format_classic_paper_md
        assert "20260418-0900" in format_classic_paper_md(_report("classic_paper"))

    def test_item_title_in_output(self) -> None:
        from newsbot.formatting.classic_paper import format_classic_paper_md
        assert "Attention Is All You Need" in format_classic_paper_md(_report("classic_paper"))


# ── format_classic_paper_html ─────────────────────────────────────────────────

class TestClassicPaperHtml:
    def test_is_valid_html_doctype(self) -> None:
        from newsbot.formatting.classic_paper import format_classic_paper_html
        assert format_classic_paper_html(_report("classic_paper")).startswith("<!DOCTYPE html>")

    def test_green_header_color(self) -> None:
        from newsbot.formatting.classic_paper import format_classic_paper_html
        assert "#065f46" in format_classic_paper_html(_report("classic_paper"))

    def test_classic_badge_text(self) -> None:
        from newsbot.formatting.classic_paper import format_classic_paper_html
        assert "클래식 논문 리뷰" in format_classic_paper_html(_report("classic_paper"))

    def test_item_title_linked(self) -> None:
        from newsbot.formatting.classic_paper import format_classic_paper_html
        html = format_classic_paper_html(_report("classic_paper"))
        assert "Attention Is All You Need" in html
        assert "https://arxiv.org/abs/1706.03762" in html

    def test_empty_extra_sections_not_rendered(self) -> None:
        from newsbot.formatting.classic_paper import format_classic_paper_html
        html = format_classic_paper_html(_report("classic_paper", extra={}))
        assert "역사적 배경" not in html


# ── format_email_html routing ─────────────────────────────────────────────────

class TestEmailHtmlRouting:
    def test_classic_paper_green_header(self) -> None:
        from newsbot.formatting.email import format_email_html
        assert "#065f46" in format_email_html(_report("classic_paper"))

    def test_new_paper_blue_header(self) -> None:
        from newsbot.formatting.email import format_email_html
        assert "#1e40af" in format_email_html(_report("new_paper"))

    def test_news_original_blue_header(self) -> None:
        from newsbot.formatting.email import format_email_html
        assert "#1d4ed8" in format_email_html(_report("news"))

    def test_classic_paper_badge_text(self) -> None:
        from newsbot.formatting.email import format_email_html
        assert "클래식 논문 리뷰" in format_email_html(_report("classic_paper"))

    def test_new_paper_badge_text(self) -> None:
        from newsbot.formatting.email import format_email_html
        assert "신논문 리뷰" in format_email_html(_report("new_paper"))

    def test_all_modes_return_html_doctype(self) -> None:
        from newsbot.formatting.email import format_email_html
        for mode in ("news", "new_paper", "classic_paper"):
            assert format_email_html(_report(mode)).startswith("<!DOCTYPE html>")


# ── build_report_md routing ───────────────────────────────────────────────────

class TestBuildReportMdRouting:
    def test_classic_paper_uses_classic_formatter(self) -> None:
        from newsbot.monitoring.summary import build_report_md
        assert "📚 클래식 논문 리뷰" in build_report_md(_report("classic_paper"))

    def test_new_paper_has_paper_emoji_in_headline(self) -> None:
        from newsbot.monitoring.summary import build_report_md
        md = build_report_md(_report("new_paper"))
        assert "📄" in md

    def test_new_paper_includes_trend_section(self) -> None:
        from newsbot.monitoring.summary import build_report_md
        md = build_report_md(_report("new_paper"))
        assert "이번 주 연구 동향" in md

    def test_news_includes_trend_section(self) -> None:
        from newsbot.monitoring.summary import build_report_md
        md = build_report_md(_report("news"))
        assert "트렌드 분석" in md

    def test_news_includes_item_analysis_section(self) -> None:
        from newsbot.monitoring.summary import build_report_md
        md = build_report_md(_report("news"))
        assert "아이템 분석" in md

    def test_new_paper_extra_fields_rendered_when_present(self) -> None:
        from newsbot.monitoring.summary import build_report_md
        r = _report("new_paper", extra={"methodology": "BERT pretraining."})
        md = build_report_md(r)
        assert "방법론" in md
        assert "BERT pretraining." in md

    def test_all_modes_produce_nonempty_string(self) -> None:
        from newsbot.monitoring.summary import build_report_md
        for mode in ("news", "new_paper", "classic_paper"):
            md = build_report_md(_report(mode))
            assert isinstance(md, str)
            assert len(md) > 100
