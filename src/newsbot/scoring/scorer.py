"""Scorer — uses the Claude API to score RawItems and produce ScoredItems.

Prompts: src/newsbot/generation/prompts/scorer_{news,new_paper,classic_paper}.md
Response format: JSON with mode-specific axes + score + reason

Token optimisation:
  - Each prompt file is split on ---ITEM--- into a static (cached) block and a
    dynamic (item-specific) block.  The static block is sent with
    cache_control=ephemeral so repeated calls within the same run share the
    cache, cutting input tokens for the static part by ~90%.
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

_PROMPT_DIR = Path(__file__).parent.parent / "generation" / "prompts"

_PROMPT_MAP: dict[str, str] = {
    "news": "scorer_news.md",
    "new_paper": "scorer_new_paper.md",
    "classic_paper": "scorer_classic_paper.md",
}

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 256
_TEMPERATURE = 0.2


def _load_prompt(pipeline_mode: str) -> tuple[str, str]:
    """Return (static_part, dynamic_template) split on the ---ITEM--- marker."""
    filename = _PROMPT_MAP.get(pipeline_mode, _PROMPT_MAP["news"])
    text = (_PROMPT_DIR / filename).read_text(encoding="utf-8")
    if "---ITEM---" not in text:
        return text, ""
    static, dynamic = text.split("---ITEM---", 1)
    return static.strip(), dynamic.strip()


def _build_content(
    static: str, dynamic_template: str, item: RawItem
) -> list[dict]:
    """Build the message content array with the static block cached."""
    dynamic = (
        dynamic_template
        .replace("{{title}}", item.title)
        .replace("{{source}}", item.source)
        .replace("{{body}}", item.body[:800])
    )
    if not static:
        return [{"type": "text", "text": dynamic}]
    return [
        {
            "type": "text",
            "text": static,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": dynamic},
    ]


def _parse_response(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    return json.loads(cleaned)


def _validate_scores(data: dict) -> None:
    for key in ("score", "reason"):
        if data.get(key) is None:
            raise ValueError(f"missing key: {key}")
    score = float(data["score"])
    if not (1.0 <= score <= 10.0):
        raise ValueError(f"score={score} out of range [1.0, 10.0]")
    if not data.get("reason"):
        raise ValueError("missing reason")


class Scorer:
    """Scores a list of RawItems via the Claude API."""

    def __init__(
        self,
        api_key: str,
        model: str = _MODEL,
        concurrency: int = 5,
        pipeline_mode: str = "news",
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._semaphore = asyncio.Semaphore(concurrency)
        self._pipeline_mode = pipeline_mode
        self._static, self._dynamic_tpl = _load_prompt(pipeline_mode)

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
        logger.info("[scorer] scored %d items (mode=%s)", len(scored), self._pipeline_mode)
        return scored

    async def _score_one(self, item: RawItem) -> ScoredItem:
        async with self._semaphore:
            content = _build_content(self._static, self._dynamic_tpl, item)
            try:
                message = await self._client.messages.create(
                    model=self._model,
                    max_tokens=_MAX_TOKENS,
                    temperature=_TEMPERATURE,
                    messages=[{"role": "user", "content": content}],
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
        estimated = min(10.0, max(1.0, item.raw_score / 50.0))
        return ScoredItem(
            raw=item,
            score=round(estimated, 1),
            score_reason="[fallback] scoring API unavailable",
        )
