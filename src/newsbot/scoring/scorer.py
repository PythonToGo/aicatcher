"""Scorer — uses the Claude API to score RawItems on 4 axes and produce ScoredItems.

Prompt: src/newsbot/generation/prompts/scorer.md
Response format: JSON (impact, freshness, practical_value, content_potential, score, reason)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

import anthropic

from newsbot.models import RawItem, ScoredItem

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "generation" / "prompts" / "scorer.md"

# Sonnet 4.6 — balanced speed / cost
_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 256
_TEMPERATURE = 0.2  # low temperature for consistent scoring


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _build_prompt(item: RawItem) -> str:
    template = _load_prompt()
    return (
        template
        .replace("{{title}}", item.title)
        .replace("{{source}}", item.source)
        .replace("{{body}}", item.body[:800])  # trim to save tokens
    )


def _parse_response(text: str) -> dict:
    """Extract JSON from Claude's response. Handles markdown fences."""
    # strip ```json ... ``` or ``` ... ```
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    return json.loads(cleaned)


def _validate_scores(data: dict) -> None:
    for key in ("impact", "freshness", "practical_value", "content_potential", "score"):
        val = data.get(key)
        if val is None:
            raise ValueError(f"missing key: {key}")
        if not (1.0 <= float(val) <= 10.0):
            raise ValueError(f"{key}={val} out of range [1.0, 10.0]")
    if not data.get("reason"):
        raise ValueError("missing reason")


class Scorer:
    """Scores a list of RawItems via the Claude API."""

    def __init__(
        self,
        api_key: str,
        model: str = _MODEL,
        concurrency: int = 5,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._semaphore = asyncio.Semaphore(concurrency)

    async def score_all(self, items: list[RawItem]) -> list[ScoredItem]:
        """Score all items in parallel. Failed items fall back to a default score."""
        tasks = [self._score_one(item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scored: list[ScoredItem] = []
        for item, result in zip(items, results):
            if isinstance(result, BaseException):
                logger.warning("[scorer] failed to score '%s': %s", item.title, result)
                scored.append(self._fallback(item))
            else:
                scored.append(result)

        scored.sort(key=lambda s: s.score, reverse=True)
        logger.info("[scorer] scored %d items", len(scored))
        return scored

    async def _score_one(self, item: RawItem) -> ScoredItem:
        async with self._semaphore:
            prompt = _build_prompt(item)
            try:
                message = await self._client.messages.create(
                    model=self._model,
                    max_tokens=_MAX_TOKENS,
                    temperature=_TEMPERATURE,
                    messages=[{"role": "user", "content": prompt}],
                )
            except anthropic.APIError as exc:
                logger.warning("[scorer] API error for '%s': %s", item.title, exc)
                raise

            raw_text = message.content[0].text
            try:
                data = _parse_response(raw_text)
                _validate_scores(data)
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                logger.warning(
                    "[scorer] invalid response for '%s': %s | response: %s",
                    item.title, exc, raw_text[:200],
                )
                raise ValueError(f"invalid scorer response: {exc}") from exc

            return ScoredItem(
                raw=item,
                score=round(float(data["score"]), 1),
                score_reason=str(data["reason"]),
            )

    @staticmethod
    def _fallback(item: RawItem) -> ScoredItem:
        """Estimate a score from raw_score when the API is unavailable."""
        # map raw_score (e.g. HN points) to 1–10: 500 pts → 10
        estimated = min(10.0, max(1.0, item.raw_score / 50.0))
        return ScoredItem(
            raw=item,
            score=round(estimated, 1),
            score_reason="[fallback] scoring API unavailable",
        )
