"""Mock Claude — Stub implementation for testing the full pipeline without the API.

When MOCK_CLAUDE=true, it returns Korean sample content through the same
interface without making Anthropic API calls.

Use cases:
  - Early MVP validation without API cost
  - CI unit tests
  - Debugging in network-restricted environments
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from newsbot.models import AnalyzedItem, RawItem, Report, ScoredItem
from newsbot.quality.checker import AnalyzerProtocol, QualityResult

logger = logging.getLogger(__name__)

# ── Sample analysis text pools ───────────────────────────────────────────────
# Korean sample text that resembles real Claude output.

_SUMMARIES = [
    "대형 언어 모델의 추론 속도가 기존 대비 3배 향상되어 실시간 응용 가능성이 크게 높아졌습니다.",
    "오픈소스 멀티모달 모델이 공개되어 이미지와 텍스트를 동시에 처리할 수 있는 기반이 마련됐습니다.",
    "새로운 파인튜닝 기법이 데이터 효율을 10배 개선해 소규모 팀도 전문 모델 구축이 가능해졌습니다.",
    "RAG 아키텍처의 한계를 극복한 새 검색 방식이 제안되어 환각 문제 해결에 진전을 보였습니다.",
    "AI 에이전트 프레임워크가 복잡한 멀티스텝 작업을 자율적으로 수행하는 능력을 입증했습니다.",
    "임베딩 모델의 크기를 1/4로 줄이면서 성능을 유지하는 압축 기술이 발표됐습니다.",
]

_CONTEXTS = [
    "최근 추론 비용 절감이 업계 최대 과제로 부상한 가운데, 이 발표는 직접적인 해법을 제시합니다.",
    "GPT-4 출시 이후 멀티모달 모델 경쟁이 본격화되었으며, 오픈소스 진영도 빠르게 추격 중입니다.",
    "기업들이 LLM 도입을 확대하면서 파인튜닝 비용 절감이 실용적 과제로 떠올랐습니다.",
    "ChatGPT 출시 후 환각 문제가 실제 서비스 장벽으로 지적되어 왔으며, 이에 대한 연구가 활발합니다.",
    "AI 에이전트는 2024년부터 주요 투자 테마로 부상했으며 실용화 단계에 접어들고 있습니다.",
    "엣지 디바이스에서의 AI 실행 수요가 증가하면서 경량화 기술의 중요성이 높아지고 있습니다.",
]

_IMPLICATIONS = [
    "API 호출 비용을 직접 절감할 수 있으므로, 프로덕션 워크로드 비용 분석을 즉시 재검토할 필요가 있습니다.",
    "기존 파이프라인에 비전 입력을 추가하는 것이 현실적으로 가능해졌습니다. 프로토타입 단계에서 테스트해 볼 것을 권장합니다.",
    "소규모 팀도 도메인 특화 모델을 보유할 수 있게 됐습니다. 데이터 라벨링 파이프라인 구축부터 시작하세요.",
    "RAG 시스템을 운영 중이라면 새 검색 방식과 A/B 테스트를 통해 환각 발생률 변화를 측정해보세요.",
    "반복적 작업 자동화에 에이전트를 적용해볼 시점입니다. 단, 사람의 검토 루프는 여전히 필수입니다.",
    "모바일/엣지 환경에서 AI 기능이 필요한 경우, 이 모델을 직접 통합하는 것을 검토할 수 있습니다.",
]

_LIMITATIONS = [
    "벤치마크 기반 성능 수치이므로 실제 워크로드에서의 성능은 다를 수 있습니다. 자체 평가가 필요합니다.",
    "아직 연구 단계이며 프로덕션 안정성은 검증되지 않았습니다. 충분한 테스트 없이 도입은 위험합니다.",
    "학술 환경에서 검증된 결과로, 실세계 노이즈가 있는 데이터에서의 성능은 보장되지 않습니다.",
    "특정 도메인 데이터에 편향되어 있을 가능성이 있어, 범용 적용 전 충분한 검증이 필요합니다.",
    "현재는 영어 중심이며 한국어 등 비영어권 언어에서의 성능은 추가 평가가 필요합니다.",
]


def _pick(pool: list[str], index: int) -> str:
    return pool[index % len(pool)]


def _mock_analyzed(item: ScoredItem, index: int = 0) -> AnalyzedItem:
    return AnalyzedItem(
        scored=item,
        summary_ko=_pick(_SUMMARIES, index),
        context=_pick(_CONTEXTS, index),
        implications=_pick(_IMPLICATIONS, index),
        limitations=_pick(_LIMITATIONS, index),
    )


# ── MockScorer ────────────────────────────────────────────────────────────────

class MockScorer:
    """Create ScoredItem values from raw_score without calling the API."""

    async def score_all(self, items: list[RawItem]) -> list[ScoredItem]:
        logger.info("[MOCK] scoring %d items (no API call)", len(items))
        scored = []
        for i, item in enumerate(items):
            # Normalize raw_score into the 1-10 range.
            score = round(min(10.0, max(1.0, 5.0 + (item.raw_score / 200.0))), 1)
            scored.append(ScoredItem(
                raw=item,
                score=score,
                score_reason=f"[MOCK] estimated from raw_score={item.raw_score}",
            ))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored


# ── MockAnalyzer ──────────────────────────────────────────────────────────────

class MockAnalyzer(AnalyzerProtocol):
    """Create AnalyzedItem values from sample Korean text without the API."""

    async def analyze_all(self, items: list[ScoredItem]) -> list[AnalyzedItem]:
        logger.info("[MOCK] analyzing %d items (no API call)", len(items))
        return [_mock_analyzed(item, i) for i, item in enumerate(items)]

    async def analyze_one(self, item: ScoredItem) -> AnalyzedItem:
        return _mock_analyzed(item)


# ── MockSynthesizer ───────────────────────────────────────────────────────────

class MockSynthesizer:
    """Create a Report from sample trend analysis without the API."""

    def __init__(self, hours_back: int = 24) -> None:
        self._hours_back = hours_back

    async def synthesize(
        self,
        items: list[AnalyzedItem],
        report_id: str | None = None,
        language: str = "ko",
        pipeline_mode: str = "news",
    ) -> Report:
        if not items:
            raise ValueError("cannot synthesize an empty item list")

        rid = report_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        logger.info("[MOCK] synthesizing %d items → report %s (no API call)", len(items), rid)

        top_sources = list({item.scored.raw.source for item in items})
        source_str = ", ".join(top_sources[:3])

        headline = f"[MOCK] {items[0].title[:20]}… 외 {len(items) - 1}건"
        trend_analysis = (
            f"이번 분석은 Mock 모드로 실행됐습니다. 실제 Claude API 응답이 아닙니다.\n\n"
            f"수집 출처: {source_str}\n\n"
            f"총 {len(items)}개 아이템을 분석했습니다. "
            f"상위 아이템은 '{items[0].title}'이며 점수는 {items[0].score}점입니다.\n\n"
            f"파이프라인 구조(Collection → Dedup → Scoring → Fetch → Analyze → "
            f"Quality → Synthesize → Format → Distribute) 전체가 정상 동작함을 확인했습니다.\n\n"
            f"실제 분석을 원하면 MOCK_CLAUDE=false로 변경하고 ANTHROPIC_API_KEY를 설정하세요."
        )

        return Report(
            report_id=rid,
            items=items,
            headline=headline,
            trend_analysis=trend_analysis,
            language=language,
            pipeline_mode=pipeline_mode,
        )


# ── MockQualityChecker ────────────────────────────────────────────────────────

class MockQualityChecker:
    """Quality checker that passes all items without calling the API."""

    async def check(self, item: AnalyzedItem) -> QualityResult:
        return QualityResult(
            passed=True,
            overall=1.0,
            feedback="[MOCK] all checks bypassed",
            scores={},
        )

    async def filter_passing(
        self,
        items: list[AnalyzedItem],
        analyzer: AnalyzerProtocol | None = None,
    ) -> list[AnalyzedItem]:
        logger.info("[MOCK] quality check bypassed for %d items", len(items))
        return items
