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
_TEMPERATURE = 0.7
_DEFAULT_HOURS_BACK = 24
_DETAIL_MAX_TOKENS = 2048
_LIGHT_MAX_TOKENS = 1400
_MAX_PARSE_RETRIES = 1
_RETRY_SUFFIX = (
    "\n\nIMPORTANT: Your previous response was not valid complete JSON. "
    "Reply again with only one complete JSON object. Keep the headline under 40 characters "
    "and the trend_analysis concise while still complete."
)


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _items_to_json(items: list[AnalyzedItem], mode: str = "detail") -> str:
    """Serialize analyzed items into prompt-ready JSON."""
    if mode == "light":
        payload = [
            {
                "title": item.title,
                "score": item.score,
                "summary_ko": _truncate(item.summary_ko, 180),
                "implications": _truncate(item.implications, 160),
            }
            for item in items
        ]
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

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


def _build_prompt(items: list[AnalyzedItem], hours_back: int, mode: str = "detail") -> str:
    template = _load_prompt()
    return (
        template
        .replace("{{item_count}}", str(len(items)))
        .replace("{{hours_back}}", str(hours_back))
        .replace("{{items_json}}", _items_to_json(items, mode))
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
        mode: str = "detail",
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._hours_back = hours_back
        self._mode = mode
        self._max_tokens = _LIGHT_MAX_TOKENS if mode == "light" else _DETAIL_MAX_TOKENS

    async def synthesize(
        self,
        items: list[AnalyzedItem],
        report_id: str | None = None,
        language: str = "ko",
    ) -> Report:
        """Return a Report synthesized from analyzed items."""
        if not items:
            raise ValueError("cannot synthesize an empty item list")

        prompt = _build_prompt(items, self._hours_back, self._mode)
        data = await self._request_valid_synthesis(prompt)

        rid = report_id or _make_report_id()
        logger.info("[synthesizer] created report %s with %d items", rid, len(items))
        return Report(
            report_id=rid,
            items=items,
            headline=str(data["headline"]),
            trend_analysis=str(data["trend_analysis"]),
            language=language,
        )

    async def _request_valid_synthesis(self, prompt: str) -> dict:
        current_prompt = prompt
        for attempt in range(_MAX_PARSE_RETRIES + 1):
            try:
                message = await self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    temperature=_TEMPERATURE,
                    messages=[{"role": "user", "content": current_prompt}],
                )
            except anthropic.APIError as exc:
                logger.warning("[synthesizer] API error: %s", exc)
                raise

            raw_text = message.content[0].text
            try:
                data = _parse_response(raw_text)
                _validate_synthesis(data)
                return data
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    "[synthesizer] invalid response (attempt %d/%d): %s | raw: %s",
                    attempt + 1,
                    _MAX_PARSE_RETRIES + 1,
                    exc,
                    raw_text[:200],
                )
                if attempt >= _MAX_PARSE_RETRIES:
                    raise ValueError(f"invalid synthesizer response: {exc}") from exc
                current_prompt = prompt + _RETRY_SUFFIX
