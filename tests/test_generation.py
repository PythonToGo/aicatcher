"""Unit tests for the generation layer.

All Claude API calls and HTTP requests are mocked.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from newsbot.generation.analyzer import (
    Analyzer,
    _build_content as _analyzer_build_content,
    _content_limit,
    _load_prompt as _analyzer_load_prompt,
)
from newsbot.generation.fetcher import Fetcher, _extract_text, _should_skip
from newsbot.generation.synthesizer import (
    Synthesizer,
    _build_content as _synth_build_content,
    _items_to_json,
    _load_prompt as _synth_load_prompt,
)


# ── Compatibility shims for renamed functions ─────────────────────────────────

def _build_analyzer_prompt(item) -> str:
    """Wrap new _build_content API to return joined text (for legacy tests)."""
    static, dynamic = _analyzer_load_prompt("news")
    limit = _content_limit("news", "detail")
    blocks = _analyzer_build_content(static, dynamic, item, limit)
    return "".join(b["text"] for b in blocks)


def _build_synth_prompt(items, hours_back: int = 24) -> str:
    """Wrap new _build_content API to return joined text (for legacy tests)."""
    static, tpl = _synth_load_prompt("news")
    blocks = _synth_build_content(static, tpl, items, len(items), hours_back, "news", "detail")
    return "".join(b["text"] for b in blocks)
from newsbot.models import AnalyzedItem, RawItem, Report, ScoredItem


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_raw(title: str = "GPT-5 released", url: str = "https://example.com") -> RawItem:
    return RawItem(
        title=title, url=url, body="Body text here.",
        source="hackernews", published_at=datetime.now(timezone.utc), raw_score=200.0,
    )


def _make_scored(title: str = "GPT-5 released", url: str = "https://example.com") -> ScoredItem:
    return ScoredItem(raw=_make_raw(title, url), score=8.0, score_reason="High impact.")


def _make_analyzed(title: str = "GPT-5 released") -> AnalyzedItem:
    return AnalyzedItem(
        scored=_make_scored(title),
        summary_ko="GPT-5가 출시되었습니다.",
        context="OpenAI의 최신 모델입니다.",
        implications="즉시 API를 테스트해보세요.",
        limitations="비용이 높을 수 있습니다.",
    )


def _make_api_message(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def _valid_analysis_json(**overrides) -> str:
    data = {
        "summary_ko": "GPT-5가 출시되어 업계에 큰 반향을 일으키고 있습니다.",
        "context": "OpenAI가 기존 GPT-4 대비 대폭 향상된 성능을 발표했습니다.",
        "implications": "API를 통해 즉시 활용 가능하며 fine-tuning도 지원합니다.",
        "limitations": "가격이 높고 context window 한계가 존재합니다.",
        "related_urls": ["https://openai.com/gpt-5"],
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _valid_synthesis_json(**overrides) -> str:
    data = {
        "headline": "추론 비용 전쟁이 시작됐다",
        "trend_analysis": "이번 주 AI 업계는 모델 효율화에 집중했습니다. " * 5,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


# ── Fetcher ───────────────────────────────────────────────────────────────────

class TestShouldSkip:
    def test_skips_twitter(self) -> None:
        assert _should_skip("https://twitter.com/user/status/123") is True

    def test_skips_x_com(self) -> None:
        assert _should_skip("https://x.com/user/status/123") is True

    def test_skips_github(self) -> None:
        assert _should_skip("https://github.com/openai/gpt") is True

    def test_does_not_skip_regular_url(self) -> None:
        assert _should_skip("https://techcrunch.com/article") is False

    def test_handles_malformed_url(self) -> None:
        assert _should_skip("not-a-url") is False


class TestExtractText:
    def test_extracts_article_tag(self) -> None:
        html = b"<html><body><article>Main content here</article><nav>Nav</nav></body></html>"
        result = _extract_text(html)
        assert "Main content here" in result
        assert "Nav" not in result

    def test_strips_script_tags(self) -> None:
        html = b"<html><body><article>Good text</article><script>bad()</script></body></html>"
        result = _extract_text(html)
        assert "bad()" not in result
        assert "Good text" in result

    def test_truncates_to_max_length(self) -> None:
        long_text = "word " * 2000
        html = f"<html><body><article>{long_text}</article></body></html>".encode()
        result = _extract_text(html)
        assert len(result) <= 4000

    def test_falls_back_to_body(self) -> None:
        html = b"<html><body><p>Only body content</p></body></html>"
        result = _extract_text(html)
        assert "Only body content" in result


class TestFetcher:
    @pytest.mark.asyncio
    async def test_fetch_all_populates_full_article(self) -> None:
        item = _make_scored(url="https://techcrunch.com/article")
        fetcher = Fetcher()

        html_content = b"<html><body><article>Full article content here for testing purposes.</article></body></html>"

        async def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.headers = {"content-type": "text/html"}
            resp.content = html_content
            return resp

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            results = await fetcher.fetch_all([item])

        assert results[0].full_article != ""
        assert "Full article content" in results[0].full_article

    @pytest.mark.asyncio
    async def test_fetch_all_fallback_on_http_error(self) -> None:
        import httpx
        item = _make_scored(url="https://techcrunch.com/article")
        item.raw.body = "Original body fallback"
        fetcher = Fetcher()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await fetcher.fetch_all([item])

        assert item.full_article == "Original body fallback"

    @pytest.mark.asyncio
    async def test_fetch_all_skips_excluded_domain(self) -> None:
        item = _make_scored(url="https://github.com/openai/gpt")
        item.raw.body = "GitHub body text"
        fetcher = Fetcher()

        # No real HTTP request should happen even without patching the request call itself.
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.side_effect = AssertionError("should not be called")
            await fetcher.fetch_all([item])

        assert item.full_article == "GitHub body text"

    @pytest.mark.asyncio
    async def test_fetch_all_skips_non_html(self) -> None:
        item = _make_scored(url="https://example.com/paper.pdf")
        item.raw.body = "PDF fallback"
        fetcher = Fetcher()

        async def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.headers = {"content-type": "application/pdf"}
            resp.content = b"%PDF..."
            return resp

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await fetcher.fetch_all([item])

        assert item.full_article == "PDF fallback"


# ── Analyzer ──────────────────────────────────────────────────────────────────

class TestBuildAnalyzerPrompt:
    def test_contains_title(self) -> None:
        item = _make_scored(title="Unique Analyzer Title")
        assert "Unique Analyzer Title" in _build_analyzer_prompt(item)

    def test_content_truncated(self) -> None:
        item = _make_scored()
        item.full_article = "x" * 5000
        prompt = _build_analyzer_prompt(item)
        assert "x" * 3000 in prompt
        assert "x" * 3001 not in prompt

    def test_uses_full_article_over_body(self) -> None:
        item = _make_scored()
        item.full_article = "Full article content"
        item.raw.body = "Raw body content"
        prompt = _build_analyzer_prompt(item)
        assert "Full article content" in prompt
        assert "Raw body content" not in prompt

    def test_falls_back_to_body_when_no_full_article(self) -> None:
        item = _make_scored()
        item.full_article = ""
        item.raw.body = "Only body"
        prompt = _build_analyzer_prompt(item)
        assert "Only body" in prompt


class TestAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_all_returns_analyzed_items(self) -> None:
        analyzer = Analyzer(api_key="test-key")
        items = [_make_scored("Item A"), _make_scored("Item B")]

        with patch.object(analyzer._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.return_value = _make_api_message(_valid_analysis_json())
            results = await analyzer.analyze_all(items)

        assert len(results) == 2
        assert all(isinstance(r, AnalyzedItem) for r in results)
        assert results[0].summary_ko != ""
        assert results[0].related_urls == ["https://openai.com/gpt-5"]

    @pytest.mark.asyncio
    async def test_analyze_all_fallback_on_api_error(self) -> None:
        import anthropic as anthropic_lib
        analyzer = Analyzer(api_key="test-key")
        item = _make_scored()

        with patch.object(analyzer._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.side_effect = anthropic_lib.APIConnectionError(request=MagicMock())
            results = await analyzer.analyze_all([item])

        assert len(results) == 1
        assert "오류" in results[0].context

    @pytest.mark.asyncio
    async def test_analyze_all_fallback_on_invalid_json(self) -> None:
        analyzer = Analyzer(api_key="test-key")
        item = _make_scored()

        with patch.object(analyzer._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.return_value = _make_api_message("not json at all")
            results = await analyzer.analyze_all([item])

        assert results[0].limitations == "자동 분석 실패 — 내용이 불완전할 수 있습니다."

    @pytest.mark.asyncio
    async def test_analyze_retries_after_invalid_json(self) -> None:
        analyzer = Analyzer(api_key="test-key")
        item = _make_scored()

        with patch.object(analyzer._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.side_effect = [
                _make_api_message("bad response"),
                _make_api_message(_valid_analysis_json()),
            ]
            results = await analyzer.analyze_all([item])

        assert results[0].summary_ko != ""
        assert mock_c.await_count == 2

    @pytest.mark.asyncio
    async def test_analyze_all_empty(self) -> None:
        analyzer = Analyzer(api_key="test-key")
        results = await analyzer.analyze_all([])
        assert results == []

    def test_fallback_uses_body_as_summary(self) -> None:
        item = _make_scored()
        item.raw.body = "Short body text."
        result = Analyzer._fallback(item)
        assert result.summary_ko == "Short body text."


# ── Synthesizer ───────────────────────────────────────────────────────────────

class TestItemsToJson:
    def test_serializes_all_fields(self) -> None:
        item = _make_analyzed("Test Title")
        output = json.loads(_items_to_json([item], "news", "detail"))
        assert output[0]["title"] == "Test Title"
        assert output[0]["summary_ko"] == "GPT-5가 출시되었습니다."
        assert output[0]["score"] == 8.0

    def test_empty_list(self) -> None:
        assert _items_to_json([], "news", "detail") == "[]"


class TestBuildSynthPrompt:
    def test_contains_item_count(self) -> None:
        items = [_make_analyzed() for _ in range(3)]
        prompt = _build_synth_prompt(items, hours_back=24)
        assert "3" in prompt

    def test_contains_hours_back(self) -> None:
        items = [_make_analyzed()]
        prompt = _build_synth_prompt(items, hours_back=48)
        assert "48" in prompt


class TestSynthesizer:
    @pytest.mark.asyncio
    async def test_synthesize_returns_report(self) -> None:
        synth = Synthesizer(api_key="test-key")
        items = [_make_analyzed("Item A"), _make_analyzed("Item B")]

        with patch.object(synth._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.return_value = _make_api_message(_valid_synthesis_json())
            report = await synth.synthesize(items, report_id="20260417-0800")

        assert isinstance(report, Report)
        assert report.report_id == "20260417-0800"
        assert report.headline == "추론 비용 전쟁이 시작됐다"
        assert len(report.items) == 2

    @pytest.mark.asyncio
    async def test_synthesize_generates_report_id_if_not_given(self) -> None:
        synth = Synthesizer(api_key="test-key")
        items = [_make_analyzed()]

        with patch.object(synth._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.return_value = _make_api_message(_valid_synthesis_json())
            report = await synth.synthesize(items)

        assert report.report_id != ""
        assert len(report.report_id) == 13  # YYYYMMDD-HHMM

    @pytest.mark.asyncio
    async def test_synthesize_raises_on_empty_items(self) -> None:
        synth = Synthesizer(api_key="test-key")
        with pytest.raises(ValueError, match="empty"):
            await synth.synthesize([])

    @pytest.mark.asyncio
    async def test_synthesize_raises_on_api_error(self) -> None:
        import anthropic as anthropic_lib
        synth = Synthesizer(api_key="test-key")

        with patch.object(synth._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.side_effect = anthropic_lib.APIConnectionError(request=MagicMock())
            with pytest.raises(anthropic_lib.APIConnectionError):
                await synth.synthesize([_make_analyzed()])

    @pytest.mark.asyncio
    async def test_synthesize_raises_on_invalid_json(self) -> None:
        synth = Synthesizer(api_key="test-key")

        with patch.object(synth._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.return_value = _make_api_message("bad response")
            with pytest.raises(ValueError, match="invalid synthesizer response"):
                await synth.synthesize([_make_analyzed()])

    @pytest.mark.asyncio
    async def test_synthesize_retries_after_invalid_json(self) -> None:
        synth = Synthesizer(api_key="test-key")

        with patch.object(synth._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.side_effect = [
                _make_api_message("bad response"),
                _make_api_message(_valid_synthesis_json()),
            ]
            report = await synth.synthesize([_make_analyzed()])

        assert report.headline == "추론 비용 전쟁이 시작됐다"
        assert mock_c.await_count == 2

    @pytest.mark.asyncio
    async def test_synthesize_language_passed_to_report(self) -> None:
        synth = Synthesizer(api_key="test-key")

        with patch.object(synth._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.return_value = _make_api_message(_valid_synthesis_json())
            report = await synth.synthesize([_make_analyzed()], language="en")

        assert report.language == "en"
