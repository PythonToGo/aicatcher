"""QualityChecker — Validate AnalyzedItem quality and request regeneration when needed.

Checks:
  1. Rule-based pre-checks for fast failure without API calls
  2. Claude API-based quality evaluation across five dimensions

Retries:
  - Re-run the Analyzer up to MAX_RETRIES (2)
  - Skip the item if it still fails after retries without stopping the pipeline
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import anthropic

from newsbot.models import AnalyzedItem, ScoredItem

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "generation" / "prompts" / "quality_check.md"
_MODEL = "claude-haiku-4-5-20251001"  # Use Haiku to keep quality-check costs down.
_MAX_TOKENS = 256
_DETAIL_MAX_RETRIES = 2
_LIGHT_MAX_RETRIES = 0

# Rule-based pre-check thresholds.
_MIN_FIELD_LENGTH = 20          # Minimum length for each text field.
_MIN_KOREAN_RATIO = 0.3         # Minimum Korean-character ratio across all text.
_MAX_REPETITION_RATIO = 0.4     # Maximum allowed repeated-sentence ratio.


@dataclass
class QualityResult:
    passed: bool
    overall: float
    feedback: str
    scores: dict[str, float]

    @classmethod
    def rule_fail(cls, reason: str) -> "QualityResult":
        return cls(passed=False, overall=0.0, feedback=reason, scores={})

    @classmethod
    def skip(cls) -> "QualityResult":
        return cls(passed=True, overall=1.0, feedback="rule check skipped", scores={})


def _korean_char_ratio(text: str) -> float:
    """Return the ratio of Korean Hangul characters in the string."""
    if not text:
        return 0.0
    korean = sum(1 for c in text if "\uac00" <= c <= "\ud7a3")
    return korean / len(text)


def _repetition_ratio(text: str) -> float:
    """Return the repetition ratio at the sentence level."""
    sentences = [s.strip() for s in re.split(r"[.。!?！？]", text) if len(s.strip()) > 10]
    if len(sentences) <= 1:
        return 0.0
    unique = len(set(sentences))
    return 1.0 - (unique / len(sentences))


def _rule_check(item: AnalyzedItem) -> QualityResult | None:
    """Run rule-based pre-checks and return QualityResult only on failure."""
    fields = {
        "summary_ko": item.summary_ko,
        "context": item.context,
        "implications": item.implications,
        "limitations": item.limitations,
    }

    # 1. Empty or too-short fields.
    for name, value in fields.items():
        if len(value.strip()) < _MIN_FIELD_LENGTH:
            return QualityResult.rule_fail(f"field '{name}' is too short ({len(value)} chars)")

    # 2. Korean character ratio.
    all_text = " ".join(fields.values())
    ratio = _korean_char_ratio(all_text)
    if ratio < _MIN_KOREAN_RATIO:
        return QualityResult.rule_fail(
            f"Korean ratio too low: {ratio:.2f} < {_MIN_KOREAN_RATIO}"
        )

    # 3. Repeated sentences.
    rep = _repetition_ratio(all_text)
    if rep > _MAX_REPETITION_RATIO:
        return QualityResult.rule_fail(
            f"Too much repetition: {rep:.2f} > {_MAX_REPETITION_RATIO}"
        )

    return None  # Passed.


def _build_prompt(item: AnalyzedItem, min_score: float) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return (
        template
        .replace("{{title}}", item.title)
        .replace("{{summary_ko}}", item.summary_ko)
        .replace("{{context}}", item.context)
        .replace("{{implications}}", item.implications)
        .replace("{{limitations}}", item.limitations)
        .replace("{{min_score}}", str(min_score))
    )


def _parse_quality_response(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    return json.loads(cleaned)


class QualityChecker:
    """Run quality checks for AnalyzedItem instances."""

    def __init__(
        self,
        api_key: str,
        min_score: float = 0.8,
        model: str = _MODEL,
        mode: str = "detail",
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._min_score = min_score
        self._model = model
        self._mode = mode
        self._max_retries = _LIGHT_MAX_RETRIES if mode == "light" else _DETAIL_MAX_RETRIES

    async def check(self, item: AnalyzedItem) -> QualityResult:
        """Check a single item.

        Stage 1: rule-based checks without API calls
        Stage 2: Claude Haiku-based checks
        """
        # Stage 1
        rule_result = _rule_check(item)
        if rule_result is not None:
            logger.debug("[quality] rule fail '%s': %s", item.title, rule_result.feedback)
            return rule_result

        if self._mode == "light":
            return QualityResult.skip()

        # Stage 2
        try:
            return await self._api_check(item)
        except Exception as exc:
            logger.warning("[quality] API check failed for '%s': %s", item.title, exc)
            # Treat API failures as pass/skip because unavailable checks do not imply bad quality.
            return QualityResult.skip()

    async def _api_check(self, item: AnalyzedItem) -> QualityResult:
        prompt = _build_prompt(item, self._min_score)
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text
        try:
            data = _parse_quality_response(raw)
        except (json.JSONDecodeError, KeyError) as exc:
            raise ValueError(f"invalid quality response: {exc}") from exc

        scores = {
            k: float(data.get(k, 0.0))
            for k in ("korean_ratio", "length_adequacy", "no_repetition",
                      "section_completeness", "factual_coherence")
        }
        overall = float(data.get("overall", sum(scores.values()) / len(scores)))
        passed = bool(data.get("passed", overall >= self._min_score))
        feedback = str(data.get("feedback", ""))

        return QualityResult(passed=passed, overall=overall, feedback=feedback, scores=scores)

    async def filter_passing(
        self,
        items: list[AnalyzedItem],
        analyzer: "AnalyzerProtocol | None" = None,
    ) -> list[AnalyzedItem]:
        """Return only items that pass quality checks.

        If analyzer is provided, failed items are regenerated and re-checked
        up to MAX_RETRIES times.
        """
        passing: list[AnalyzedItem] = []

        for item in items:
            result = await self.check(item)
            if result.passed:
                passing.append(item)
                continue

            logger.info(
                "[quality] failed '%s' (%.2f): %s", item.title, result.overall, result.feedback
            )

            if analyzer is None:
                logger.info("[quality] no analyzer provided, skipping '%s'", item.title)
                continue

            if self._max_retries == 0:
                logger.info("[quality] retries disabled in %s mode, skipping '%s'", self._mode, item.title)
                continue

            # Retry.
            current = item
            for attempt in range(1, self._max_retries + 1):
                logger.info("[quality] retry %d/%d for '%s'", attempt, self._max_retries, item.title)
                try:
                    retried = await analyzer.analyze_one(current.scored)
                except Exception as exc:
                    logger.warning("[quality] retry %d failed: %s", attempt, exc)
                    break

                retry_result = await self.check(retried)
                if retry_result.passed:
                    passing.append(retried)
                    logger.info("[quality] retry %d passed for '%s'", attempt, item.title)
                    break
                current = retried
            else:
                logger.info("[quality] all retries exhausted for '%s', skipping", item.title)

        logger.info("[quality] %d/%d items passed", len(passing), len(items))
        return passing


# ── Analyzer protocol for retries ────────────────────────────────────────────

class AnalyzerProtocol:
    """Analyzer interface used by QualityChecker for retries."""

    async def analyze_one(self, item: ScoredItem) -> AnalyzedItem:
        raise NotImplementedError
