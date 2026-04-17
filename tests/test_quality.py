"""Unit tests for the quality gate."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from newsbot.models import AnalyzedItem, RawItem, ScoredItem
from newsbot.quality.checker import (
    QualityChecker,
    QualityResult,
    _korean_char_ratio,
    _repetition_ratio,
    _rule_check,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_raw(title: str = "GPT-5 released") -> RawItem:
    return RawItem(
        title=title, url="https://example.com", body="Body.",
        source="hackernews", published_at=datetime.now(timezone.utc), raw_score=200.0,
    )


def _make_analyzed(
    summary_ko: str = "GPT-5가 출시되어 AI 업계에 큰 반향을 일으키고 있습니다.",
    context: str = "OpenAI가 기존 GPT-4 대비 대폭 향상된 성능을 발표했습니다.",
    implications: str = "API를 통해 즉시 활용 가능하며 다양한 산업에 적용될 수 있습니다.",
    limitations: str = "높은 가격과 context window 한계가 존재합니다.",
    title: str = "GPT-5 released",
) -> AnalyzedItem:
    scored = ScoredItem(raw=_make_raw(title), score=8.0, score_reason="High impact.")
    return AnalyzedItem(
        scored=scored,
        summary_ko=summary_ko,
        context=context,
        implications=implications,
        limitations=limitations,
    )


def _valid_quality_json(passed: bool = True, overall: float = 0.9) -> str:
    return json.dumps({
        "korean_ratio": 0.95,
        "length_adequacy": 0.9,
        "no_repetition": 0.95,
        "section_completeness": 0.9,
        "factual_coherence": 0.9,
        "overall": overall,
        "passed": passed,
        "feedback": "All checks passed" if passed else "Content is too short.",
    })


def _make_checker() -> QualityChecker:
    return QualityChecker(api_key="test-key", min_score=0.8)


# ── _korean_char_ratio ────────────────────────────────────────────────────────

class TestKoreanCharRatio:
    def test_all_korean(self) -> None:
        assert _korean_char_ratio("안녕하세요") == pytest.approx(1.0)

    def test_no_korean(self) -> None:
        assert _korean_char_ratio("hello world") == pytest.approx(0.0)

    def test_mixed(self) -> None:
        # Three Hangul chars plus three Latin chars -> ratio = 3 / 6 = 0.5
        ratio = _korean_char_ratio("가나다abc")
        assert ratio == pytest.approx(0.5)

    def test_empty_string(self) -> None:
        assert _korean_char_ratio("") == pytest.approx(0.0)


# ── _repetition_ratio ─────────────────────────────────────────────────────────

class TestRepetitionRatio:
    def test_no_repetition(self) -> None:
        text = "첫 번째 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다."
        assert _repetition_ratio(text) == pytest.approx(0.0)

    def test_full_repetition(self) -> None:
        sentence = "완전히 동일한 문장입니다"
        text = f"{sentence}. {sentence}. {sentence}."
        # Out of 3 sentences, unique=1 -> ratio = 1 - 1/3 = 0.667
        assert _repetition_ratio(text) > 0.5

    def test_single_sentence(self) -> None:
        assert _repetition_ratio("단일 문장만 있습니다") == pytest.approx(0.0)

    def test_empty_string(self) -> None:
        assert _repetition_ratio("") == pytest.approx(0.0)


# ── _rule_check ───────────────────────────────────────────────────────────────

class TestRuleCheck:
    def test_passes_good_item(self) -> None:
        item = _make_analyzed()
        assert _rule_check(item) is None

    def test_fails_short_summary(self) -> None:
        item = _make_analyzed(summary_ko="짧음")
        result = _rule_check(item)
        assert result is not None
        assert result.passed is False
        assert "summary_ko" in result.feedback

    def test_fails_short_context(self) -> None:
        item = _make_analyzed(context="짧음")
        result = _rule_check(item)
        assert result is not None
        assert "context" in result.feedback

    def test_fails_low_korean_ratio(self) -> None:
        # English-only text without Korean characters.
        item = _make_analyzed(
            summary_ko="This summary is entirely in English without any Korean.",
            context="This context is also entirely in English.",
            implications="These implications are in English too.",
            limitations="These limitations have no Korean characters.",
        )
        result = _rule_check(item)
        assert result is not None
        assert "Korean ratio" in result.feedback

    def test_fails_high_repetition(self) -> None:
        repeated = "완전히 동일한 문장입니다"
        long_repeated = (repeated + ". ") * 10
        item = _make_analyzed(
            summary_ko=long_repeated,
            context=long_repeated,
            implications=long_repeated,
            limitations=long_repeated,
        )
        result = _rule_check(item)
        assert result is not None
        assert "repetition" in result.feedback


# ── QualityResult ─────────────────────────────────────────────────────────────

class TestQualityResult:
    def test_rule_fail(self) -> None:
        result = QualityResult.rule_fail("test reason")
        assert result.passed is False
        assert result.overall == 0.0
        assert result.feedback == "test reason"

    def test_skip(self) -> None:
        result = QualityResult.skip()
        assert result.passed is True
        assert result.overall == 1.0


# ── QualityChecker ────────────────────────────────────────────────────────────

class TestQualityChecker:
    @pytest.mark.asyncio
    async def test_check_passes_good_item(self) -> None:
        checker = _make_checker()
        item = _make_analyzed()

        msg = MagicMock()
        msg.content = [MagicMock(text=_valid_quality_json(passed=True))]

        with patch.object(checker._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.return_value = msg
            result = await checker.check(item)

        assert result.passed is True
        assert result.overall == pytest.approx(0.9)
        assert "korean_ratio" in result.scores

    @pytest.mark.asyncio
    async def test_check_fails_bad_item(self) -> None:
        checker = _make_checker()
        item = _make_analyzed()

        msg = MagicMock()
        msg.content = [MagicMock(text=_valid_quality_json(passed=False, overall=0.5))]

        with patch.object(checker._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.return_value = msg
            result = await checker.check(item)

        assert result.passed is False
        assert result.feedback == "Content is too short."

    @pytest.mark.asyncio
    async def test_check_skips_api_on_rule_failure(self) -> None:
        """Should not call the Claude API when rule checks already fail."""
        checker = _make_checker()
        item = _make_analyzed(summary_ko="짧음")

        with patch.object(checker._client.messages, "create", new_callable=AsyncMock) as mock_c:
            result = await checker.check(item)
            mock_c.assert_not_called()

        assert result.passed is False

    @pytest.mark.asyncio
    async def test_check_passes_on_api_error(self) -> None:
        """Treat API failures as pass/skip so the pipeline can continue."""
        import anthropic as anthropic_lib
        checker = _make_checker()
        item = _make_analyzed()

        with patch.object(checker._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.side_effect = anthropic_lib.APIConnectionError(request=MagicMock())
            result = await checker.check(item)

        assert result.passed is True
        assert result.feedback == "rule check skipped"

    @pytest.mark.asyncio
    async def test_filter_passing_keeps_good_items(self) -> None:
        checker = _make_checker()
        items = [_make_analyzed(title="Good A"), _make_analyzed(title="Good B")]

        msg = MagicMock()
        msg.content = [MagicMock(text=_valid_quality_json(passed=True))]

        with patch.object(checker._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.return_value = msg
            result = await checker.filter_passing(items)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_filter_passing_drops_bad_without_analyzer(self) -> None:
        checker = _make_checker()
        good = _make_analyzed(title="Good")
        bad = _make_analyzed(title="Bad")

        good_msg = MagicMock()
        good_msg.content = [MagicMock(text=_valid_quality_json(passed=True))]
        bad_msg = MagicMock()
        bad_msg.content = [MagicMock(text=_valid_quality_json(passed=False, overall=0.4))]

        with patch.object(checker._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.side_effect = [good_msg, bad_msg]
            result = await checker.filter_passing([good, bad], analyzer=None)

        assert len(result) == 1
        assert result[0].title == "Good"

    @pytest.mark.asyncio
    async def test_filter_passing_retries_with_analyzer(self) -> None:
        checker = _make_checker()
        item = _make_analyzed(title="Retryable")

        # First check fails, then the retry check succeeds.
        fail_msg = MagicMock()
        fail_msg.content = [MagicMock(text=_valid_quality_json(passed=False, overall=0.5))]
        pass_msg = MagicMock()
        pass_msg.content = [MagicMock(text=_valid_quality_json(passed=True))]

        mock_analyzer = MagicMock()
        retried_item = _make_analyzed(title="Retried")
        mock_analyzer.analyze_one = AsyncMock(return_value=retried_item)

        with patch.object(checker._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.side_effect = [fail_msg, pass_msg]
            result = await checker.filter_passing([item], analyzer=mock_analyzer)

        assert len(result) == 1
        mock_analyzer.analyze_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_filter_passing_exhausts_retries(self) -> None:
        """Skip the item when retries exceed MAX_RETRIES."""
        checker = _make_checker()
        item = _make_analyzed(title="Always bad")

        fail_msg = MagicMock()
        fail_msg.content = [MagicMock(text=_valid_quality_json(passed=False, overall=0.3))]

        mock_analyzer = MagicMock()
        mock_analyzer.analyze_one = AsyncMock(return_value=_make_analyzed("Still bad"))

        # 1 initial + 2 retries = 3 checks, all fail
        with patch.object(checker._client.messages, "create", new_callable=AsyncMock) as mock_c:
            mock_c.return_value = fail_msg
            result = await checker.filter_passing([item], analyzer=mock_analyzer)

        assert result == []
        assert mock_analyzer.analyze_one.call_count == 2  # MAX_RETRIES

    @pytest.mark.asyncio
    async def test_filter_passing_empty_list(self) -> None:
        checker = _make_checker()
        result = await checker.filter_passing([])
        assert result == []
