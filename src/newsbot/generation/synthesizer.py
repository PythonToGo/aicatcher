"""Synthesizer — Combine analyzed items into a Report headline and trend_analysis.

Prompt: src/newsbot/generation/prompts/synthesizer.md
Response format: JSON (headline, trend_analysis)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from newsbot.models import AnalyzedItem, Report

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "synthesizer.md"
_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 2048
_TEMPERATURE = 0.7
_DEFAULT_HOURS_BACK = 24


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _items_to_json(items: list[AnalyzedItem]) -> str:
    """Serialize analyzed items into prompt-ready JSON."""
    payload = [
        {
            "title": item.title,
            "url": item.url,
            "source": item.scored.raw.source,
            "score": item.score,
            "summary_ko": item.summary_ko,
            "context": item.context,
            "implications": item.implications,
        }
        for item in items
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _build_prompt(items: list[AnalyzedItem], hours_back: int) -> str:
    template = _load_prompt()
    return (
        template
        .replace("{{item_count}}", str(len(items)))
        .replace("{{hours_back}}", str(hours_back))
        .replace("{{items_json}}", _items_to_json(items))
    )


def _parse_response(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    return json.loads(cleaned)


def _validate_synthesis(data: dict) -> None:
    if not data.get("headline"):
        raise ValueError("missing headline")
    if not data.get("trend_analysis"):
        raise ValueError("missing trend_analysis")


def _make_report_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")


class Synthesizer:
    """Generate a Report by synthesizing all analyzed items."""

    def __init__(
        self,
        api_key: str,
        model: str = _MODEL,
        hours_back: int = _DEFAULT_HOURS_BACK,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._hours_back = hours_back

    async def synthesize(
        self,
        items: list[AnalyzedItem],
        report_id: str | None = None,
        language: str = "ko",
    ) -> Report:
        """Return a Report synthesized from analyzed items."""
        if not items:
            raise ValueError("cannot synthesize an empty item list")

        prompt = _build_prompt(items, self._hours_back)
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                temperature=_TEMPERATURE,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            logger.warning("[synthesizer] API error: %s", exc)
            raise

        raw_text = message.content[0].text
        try:
            data = _parse_response(raw_text)
            _validate_synthesis(data)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("[synthesizer] invalid response: %s | raw: %s", exc, raw_text[:200])
            raise ValueError(f"invalid synthesizer response: {exc}") from exc

        rid = report_id or _make_report_id()
        logger.info("[synthesizer] created report %s with %d items", rid, len(items))
        return Report(
            report_id=rid,
            items=items,
            headline=str(data["headline"]),
            trend_analysis=str(data["trend_analysis"]),
            language=language,
        )
