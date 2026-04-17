"""Unit tests for the scoring layer.

All Claude API calls are replaced with AsyncMock.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from newsbot.models import RawItem, ScoredItem
from newsbot.scoring.feedback import FeedbackWeighter
from newsbot.scoring.scorer import Scorer, _build_prompt, _parse_response, _validate_scores


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_raw(
    title: str = "GPT-5 released by OpenAI",
    source: str = "hackernews",
    raw_score: float = 300.0,
) -> RawItem:
    return RawItem(
        title=title,
        url="https://example.com/gpt5",
        body="OpenAI released GPT-5 with major improvements.",
        source=source,
        published_at=datetime.now(timezone.utc),
        raw_score=raw_score,
    )


def _valid_response_json(**overrides) -> str:
    data = {
        "impact": 9.0,
        "freshness": 8.5,
        "practical_value": 7.0,
        "content_potential": 8.0,
        "score": 8.2,
        "reason": "Major model release with broad industry impact.",
    }
    data.update(overrides)
    return json.dumps(data)


def _make_message(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def _make_scorer() -> Scorer:
    return Scorer(api_key="test-key", concurrency=2)


# ── _build_prompt ─────────────────────────────────────────────────────────────

class TestBuildPrompt:
    def test_contains_title(self) -> None:
        item = _make_raw(title="Unique Title XYZ")
        prompt = _build_prompt(item)
        assert "Unique Title XYZ" in prompt

    def test_contains_source(self) -> None:
        item = _make_raw(source="arxiv")
        prompt = _build_prompt(item)
        assert "arxiv" in prompt

    def test_body_truncated_to_800(self) -> None:
        item = _make_raw()
        item.body = "x" * 1000
        prompt = _build_prompt(item)
        assert "x" * 800 in prompt
        assert "x" * 801 not in prompt


# ── _parse_response ───────────────────────────────────────────────────────────

class TestParseResponse:
    def test_plain_json(self) -> None:
        data = _parse_response(_valid_response_json())
        assert data["score"] == 8.2

    def test_json_with_markdown_fence(self) -> None:
        text = f"```json\n{_valid_response_json()}\n```"
        data = _parse_response(text)
        assert data["impact"] == 9.0

    def test_json_with_plain_fence(self) -> None:
        text = f"```\n{_valid_response_json()}\n```"
        data = _parse_response(text)
        assert data["reason"] == "Major model release with broad industry impact."

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _parse_response("not valid json")


# ── _validate_scores ──────────────────────────────────────────────────────────

class TestValidateScores:
    def _valid(self) -> dict:
        return json.loads(_valid_response_json())

    def test_valid_passes(self) -> None:
        _validate_scores(self._valid())  # should not raise

    def test_missing_key_raises(self) -> None:
        data = self._valid()
        del data["score"]
        with pytest.raises(ValueError, match="missing key"):
            _validate_scores(data)

    def test_out_of_range_raises(self) -> None:
        data = self._valid()
        data["impact"] = 11.0
        with pytest.raises(ValueError, match="out of range"):
            _validate_scores(data)

    def test_below_range_raises(self) -> None:
        data = self._valid()
        data["freshness"] = 0.5
        with pytest.raises(ValueError, match="out of range"):
            _validate_scores(data)

    def test_empty_reason_raises(self) -> None:
        data = self._valid()
        data["reason"] = ""
        with pytest.raises(ValueError, match="missing reason"):
            _validate_scores(data)


# ── Scorer ────────────────────────────────────────────────────────────────────

class TestScorer:
    @pytest.mark.asyncio
    async def test_score_all_returns_scored_items(self) -> None:
        scorer = _make_scorer()
        items = [_make_raw("Item A"), _make_raw("Item B")]

        with patch.object(scorer._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _make_message(_valid_response_json())
            results = await scorer.score_all(items)

        assert len(results) == 2
        assert all(isinstance(r, ScoredItem) for r in results)
        assert all(1.0 <= r.score <= 10.0 for r in results)

    @pytest.mark.asyncio
    async def test_score_all_sorted_descending(self) -> None:
        scorer = _make_scorer()
        items = [_make_raw("Low"), _make_raw("High")]
        responses = [
            _valid_response_json(score=3.0),
            _valid_response_json(score=9.0),
        ]

        with patch.object(scorer._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = [_make_message(r) for r in responses]
            results = await scorer.score_all(items)

        assert results[0].score >= results[1].score

    @pytest.mark.asyncio
    async def test_score_all_fallback_on_api_error(self) -> None:
        import anthropic as anthropic_lib
        scorer = _make_scorer()
        item = _make_raw(raw_score=250.0)

        with patch.object(scorer._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = anthropic_lib.APIConnectionError(request=MagicMock())
            results = await scorer.score_all([item])

        assert len(results) == 1
        assert results[0].score_reason == "[fallback] scoring API unavailable"
        # raw_score 250 / 50 = 5.0
        assert results[0].score == pytest.approx(5.0)

    @pytest.mark.asyncio
    async def test_score_all_fallback_on_invalid_json(self) -> None:
        scorer = _make_scorer()
        item = _make_raw()

        with patch.object(scorer._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _make_message("this is not json")
            results = await scorer.score_all([item])

        assert results[0].score_reason == "[fallback] scoring API unavailable"

    @pytest.mark.asyncio
    async def test_score_all_empty_input(self) -> None:
        scorer = _make_scorer()
        results = await scorer.score_all([])
        assert results == []

    @pytest.mark.asyncio
    async def test_concurrency_respected(self) -> None:
        """Ensure no more than _semaphore.concurrency(2) run at once."""
        scorer = Scorer(api_key="test-key", concurrency=2)
        items = [_make_raw(f"Item {i}") for i in range(6)]
        active = 0
        max_active = 0

        async def slow_create(*args, **kwargs):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            import asyncio
            await asyncio.sleep(0.01)
            active -= 1
            return _make_message(_valid_response_json())

        with patch.object(scorer._client.messages, "create", new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = slow_create
            await scorer.score_all(items)

        assert max_active <= 2

    def test_fallback_score_clamps_to_10(self) -> None:
        item = _make_raw(raw_score=9999.0)
        result = Scorer._fallback(item)
        assert result.score == 10.0

    def test_fallback_score_clamps_to_1(self) -> None:
        item = _make_raw(raw_score=0.0)
        result = Scorer._fallback(item)
        assert result.score == 1.0


# ── FeedbackWeighter (Phase 1 stub) ───────────────────────────────────────────

class TestFeedbackWeighter:
    def _make_scored(self) -> ScoredItem:
        return ScoredItem(raw=_make_raw(), score=7.0, score_reason="good")

    def test_apply_returns_same_items(self) -> None:
        weighter = FeedbackWeighter()
        items = [self._make_scored(), self._make_scored()]
        result = weighter.apply(items)
        assert result is items

    def test_get_weight_returns_one(self) -> None:
        weighter = FeedbackWeighter()
        assert weighter.get_weight(self._make_scored()) == 1.0

    def test_apply_does_not_change_scores(self) -> None:
        weighter = FeedbackWeighter()
        item = self._make_scored()
        original_score = item.score
        weighter.apply([item])
        assert item.score == original_score
