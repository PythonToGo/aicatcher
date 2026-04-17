"""Analyzer — Deeply analyze ScoredItem values into AnalyzedItem via the Claude API.

Prompt: src/newsbot/generation/prompts/analyzer.md
Response format: JSON (summary_ko, context, implications, limitations, related_urls)
Concurrency: asyncio.gather + Semaphore
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

import anthropic

from newsbot.models import AnalyzedItem, ScoredItem

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "analyzer.md"
_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 1024
_TEMPERATURE = 0.5


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _build_prompt(item: ScoredItem) -> str:
    template = _load_prompt()
    content = item.full_article or item.raw.body
    return (
        template
        .replace("{{title}}", item.raw.title)
        .replace("{{source}}", item.raw.source)
        .replace("{{url}}", item.raw.url)
        .replace("{{content}}", content[:3000])
    )


def _parse_response(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    return json.loads(cleaned)


def _validate_analysis(data: dict) -> None:
    required = ("summary_ko", "context", "implications", "limitations")
    for key in required:
        if not data.get(key):
            raise ValueError(f"missing or empty field: {key}")
    if not isinstance(data.get("related_urls", []), list):
        raise ValueError("related_urls must be a list")


class Analyzer:
    """Deeply analyze a list of ScoredItem values in parallel."""

    def __init__(
        self,
        api_key: str,
        model: str = _MODEL,
        concurrency: int = 5,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._semaphore = asyncio.Semaphore(concurrency)

    async def analyze_all(self, items: list[ScoredItem]) -> list[AnalyzedItem]:
        """Analyze all items in parallel and fall back on failure."""
        tasks = [self._analyze_one(item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        analyzed: list[AnalyzedItem] = []
        for item, result in zip(items, results):
            if isinstance(result, BaseException):
                logger.warning("[analyzer] failed '%s': %s", item.raw.title, result)
                analyzed.append(self._fallback(item))
            else:
                analyzed.append(result)

        logger.info("[analyzer] analyzed %d items", len(analyzed))
        return analyzed

    async def analyze_one(self, item: ScoredItem) -> AnalyzedItem:
        """Analyze a single item for QualityChecker retries."""
        return await self._analyze_one(item)

    async def _analyze_one(self, item: ScoredItem) -> AnalyzedItem:
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
                logger.warning("[analyzer] API error for '%s': %s", item.raw.title, exc)
                raise

            raw_text = message.content[0].text
            try:
                data = _parse_response(raw_text)
                _validate_analysis(data)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    "[analyzer] invalid response for '%s': %s | raw: %s",
                    item.raw.title, exc, raw_text[:200],
                )
                raise ValueError(f"invalid analyzer response: {exc}") from exc

            return AnalyzedItem(
                scored=item,
                summary_ko=str(data["summary_ko"]),
                context=str(data["context"]),
                implications=str(data["implications"]),
                limitations=str(data["limitations"]),
                related_urls=[str(u) for u in data.get("related_urls", [])],
            )

    @staticmethod
    def _fallback(item: ScoredItem) -> AnalyzedItem:
        return AnalyzedItem(
            scored=item,
            summary_ko=item.raw.body[:200],
            context="분석 중 오류가 발생했습니다.",
            implications="원문을 직접 확인하세요.",
            limitations="자동 분석 실패 — 내용이 불완전할 수 있습니다.",
        )
