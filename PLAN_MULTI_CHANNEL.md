# 멀티 채널 파이프라인 리팩토링 플랜

> 작성일: 2026-05-18  
> 목표: 단일 파이프라인 → 3개 콘텐츠 타입 파이프라인으로 분리

---

## 1. 현재 상태 분석

### 현재 파이프라인 (단일)

```
Collection (HN + ArXiv)
  → Dedup (SQLite + embeddings)
  → Scoring (Claude, 4-axis: impact/freshness/practical_value/content_potential)
  → Fetch (httpx + BS4)
  → Analyze (Claude, JSON: summary_ko/context/implications/limitations)
  → Quality Gate (Claude, 0~1 score, max 2 retries)
  → Synthesize (Claude, headline + trend_analysis)
  → Format (Twitter/Threads/Email)
  → Distribute
```

### 문제점
- ArXiv 신논문과 HN 뉴스가 같은 스코어 기준으로 혼합 처리됨
- `freshness` 축이 클래식 논문에는 부적합 (오래된 게 패널티)
- 클래식 논문용 수집 소스가 없음
- 채널별 포맷/배포 주기가 콘텐츠 특성과 불일치

---

## 2. 목표 아키텍처

### 3개 파이프라인 모드

| 모드 | 콘텐츠 | 소스 | 주기 | 배포 |
|------|--------|------|------|------|
| `new_paper` | 최근 AI/ML 신논문 | ArXiv, HuggingFace Papers | 주 1회 (화) | Twitter + GitHub Archive + Email |
| `classic_paper` | 영향력 있는 구논문 1편 심층 요약 | Semantic Scholar + 큐레이션 목록 | 주 1회 (목) | Twitter + GitHub Archive + Email |
| `news` | 최신 AI/ML 이슈·뉴스 | HN, Reddit, RSS | 하루 3회 (기존) | Twitter + Threads + GitHub Archive + Email |

### 파이프라인 분기 방식

`PIPELINE_MODE` 환경변수로 모드 선택 → 각 컴포넌트가 mode-aware하게 동작.  
모드별 스크립트(`run_new_papers.py`, `run_classic_paper.py`) + 기존 `run_pipeline.py`(news 용도 유지).

---

## 3. 변경 범위

### 3-1. 데이터 모델 (`models.py`)

**변경:** `RawItem`에 `content_type` 필드 추가.

```python
# 기존
@dataclass
class RawItem:
    source: str  # "hackernews" | "arxiv" | ...

# 변경 후
@dataclass
class RawItem:
    source: str
    content_type: str = "news"  # "new_paper" | "classic_paper" | "news"
```

`Report`에도 `pipeline_mode` 추가 → 포맷터/배포기가 모드를 인식.

```python
@dataclass
class Report:
    ...
    pipeline_mode: str = "news"  # "new_paper" | "classic_paper" | "news"
```

---

### 3-2. Config (`config.py`)

`PIPELINE_MODE` 환경변수 추가. 기본값 `"news"` (기존 동작 유지).

```python
pipeline_mode: str = Field(
    default="news",
    description="'news' | 'new_paper' | 'classic_paper'"
)
```

**토큰 최적화:** 모드별 기본 모델/토큰 설정 추가.

```python
# classic_paper는 단일 아이템 심층 분석 → Opus 사용 가능
# new_paper 스코어링은 많은 아이템 처리 → Haiku로 1차 필터
items_per_classic: int = Field(default=1)   # 한 번에 논문 1편만
items_per_new_paper: int = Field(default=5) # 주간 신논문 5편
```

---

### 3-3. Collection — 신규 수집기

#### `collection/semantic_scholar.py` (클래식 논문용)

Semantic Scholar Public API 활용. 무료, 인증 불필요.

```python
# 전략: 고인용 AI/ML 논문을 회전 방식으로 1편씩 반환
# - fields_of_study=Computer Science, year<=2020 (5년 이상 된 논문)
# - citationCount >= 500
# - 이미 발행된 논문은 SQLite에서 제외 (dedup 재활용)
# API: https://api.semanticscholar.org/graph/v1/paper/search
```

큐레이션 시드 목록 (`data/classic_papers_seed.json`) 병행:
- Attention is All You Need, BERT, GPT-2, ResNet, GAN, Word2Vec 등
- 시드 소진 시 Semantic Scholar API 폴백

#### `collection/registry.py` 수정

```python
def build_registry(mode: str) -> CollectorRegistry:
    if mode == "news":
        registry.register(HackerNewsCollector())
        # registry.register(RedditCollector())  # Phase 2
        # registry.register(RSSCollector())     # Phase 2
    elif mode == "new_paper":
        registry.register(ArxivCollector(days_back=7))
        # registry.register(HuggingFaceCollector())  # Phase 2
    elif mode == "classic_paper":
        registry.register(SemanticScholarCollector(limit=10))
    return registry
```

---

### 3-4. Scoring — 모드별 프롬프트

현재 단일 `prompts/scorer.md` → 모드별 프롬프트 파일로 분리.

| 파일 | 4축 기준 |
|------|---------|
| `prompts/scorer_news.md` | impact / freshness / practical_value / content_potential |
| `prompts/scorer_new_paper.md` | novelty / methodology_rigor / practical_value / reproducibility |
| `prompts/scorer_classic_paper.md` | historical_impact / citation_influence / educational_value / accessibility |

**`Scorer` 변경:** `mode` 파라미터 추가, 프롬프트 파일 동적 선택.

```python
_PROMPT_MAP = {
    "news": "scorer_news.md",
    "new_paper": "scorer_new_paper.md",
    "classic_paper": "scorer_classic_paper.md",
}
```

**토큰 최적화:**
- `news` 모드: Haiku로 1차 스코어링 → 상위 N개만 Sonnet 분석 (2단계 필터)
- `classic_paper` 모드: 논문 1편만 처리하므로 Sonnet 사용 가능
- 프롬프트 캐싱 활성화 (시스템 프롬프트 부분을 cache_control로 고정)

---

### 3-5. Analysis — 모드별 프롬프트

| 파일 | 핵심 필드 |
|------|---------|
| `prompts/analyzer_news.md` | summary_ko, context, implications, limitations |
| `prompts/analyzer_new_paper.md` | summary_ko, methodology, contributions, benchmark_results, limitations, related_work |
| `prompts/analyzer_classic_paper.md` | summary_ko, historical_context, why_groundbreaking, field_impact, key_insight, learning_points |

`AnalyzedItem` 모델 확장: 추가 필드는 `metadata: dict` 로 수용 (기존 필드 하위호환 유지).

```python
@dataclass
class AnalyzedItem:
    ...
    metadata: dict = field(default_factory=dict)
    # new_paper: {"contributions": ..., "benchmark_results": ...}
    # classic_paper: {"historical_context": ..., "learning_points": ...}
```

**`Analyzer` 변경:** `mode` 파라미터 추가.

---

### 3-6. Synthesis — 모드별 프롬프트

| 파일 | 출력 |
|------|------|
| `prompts/synthesizer_news.md` | headline + trend_analysis (기존) |
| `prompts/synthesizer_new_paper.md` | headline + weekly_research_trend (이번 주 연구 동향) |
| `prompts/synthesizer_classic_paper.md` | headline + why_read_today (왜 지금 이 논문인가) |

`classic_paper` 모드는 논문 1편이므로 synthesis가 단순 래퍼 역할 → `max_tokens` 800으로 축소.

---

### 3-7. Formatting

#### `formatting/twitter.py` (기존, 모드 분기 추가)

- `news`: 현재 포맷 유지 (헤드라인 + 아이템 스레드)
- `new_paper`: 논문 제목 + 핵심 기여 + arXiv 링크 스레드
- `classic_paper`: "📚 오늘의 클래식 논문" 고정 헤더 + 핵심 인사이트 1~2트윗

#### `formatting/classic_paper.py` (신규)

이메일/GitHub 아카이브용 클래식 논문 전용 Markdown 포맷.

```
# 📚 [논문 제목] (YYYY)

> 저자 | 발표 학회/저널 | 인용 수

## 한 줄 요약
...

## 왜 이 논문이 중요한가
...

## 핵심 인사이트
...

## 배울 점
...

## 원문 링크
```

---

### 3-8. 엔트리포인트 스크립트

| 스크립트 | 설명 |
|---------|------|
| `scripts/run_pipeline.py` | 기존 유지 (news 모드) |
| `scripts/run_new_papers.py` | 신논문 모드 |
| `scripts/run_classic_paper.py` | 클래식 논문 모드 |

`run_new_papers.py`와 `run_classic_paper.py`는 `run_pipeline.py`를 **코드 복사 없이** `PIPELINE_MODE` 환경변수만 다르게 설정해서 재사용.

```python
# run_classic_paper.py — 핵심부만
os.environ.setdefault("PIPELINE_MODE", "classic_paper")
os.environ.setdefault("ANALYSIS_MODE", "detail")   # 심층 분석
os.environ.setdefault("ITEMS_PER_REPORT", "1")
from scripts.run_pipeline import main
main()
```

---

### 3-9. GitHub Actions 워크플로

#### 신규: `.github/workflows/publish_new_papers.yml`

```yaml
on:
  schedule:
    - cron: "0 9 * * 2"   # 화요일 09:00 UTC
  workflow_dispatch:
env:
  PIPELINE_MODE: new_paper
  ANALYSIS_MODE: detail
  ITEMS_PER_REPORT: "5"
```

#### 신규: `.github/workflows/publish_classic_paper.yml`

```yaml
on:
  schedule:
    - cron: "0 9 * * 4"   # 목요일 09:00 UTC
  workflow_dispatch:
env:
  PIPELINE_MODE: classic_paper
  ANALYSIS_MODE: detail
  ITEMS_PER_REPORT: "1"
  ANTHROPIC_MAIN_MODEL: claude-sonnet-4-6
```

#### 기존: `publish_daily.yml`

`PIPELINE_MODE: news` 명시 추가 (하위호환).

---

## 4. 토큰 사용 최적화 전략

### 4-1. 2단계 스코어링 (news 모드)

```
전체 아이템 (30~50개)
  → Haiku 1차 스코어 (빠름, 저비용)  ← 상위 10개 선별
    → Sonnet 2차 분석 (상세)          ← 최종 6개
```

현재: 6개 × Sonnet 스코어링 → 6개 × Sonnet 분석  
변경: N개 × Haiku 스코어링 → 6개 × Sonnet 분석  
**예상 절감: 스코어링 비용 ~60% 감소**

### 4-2. 프롬프트 캐싱 (Anthropic cache_control)

```python
# scorer.py — 시스템 프롬프트 캐시
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},  # 5분 TTL
            },
            {"type": "text", "text": item_prompt},
        ],
    }
]
```

같은 실행 내에서 동일 시스템 프롬프트 반복 호출 시 캐시 히트 → 입력 토큰 90% 절감.

### 4-3. 모드별 컨텍스트 한도

| 모드 | content_limit | max_tokens (분석) |
|------|-------------|-----------------|
| news (light) | 1,500자 | 900 |
| news (detail) | 3,000자 | 1,024 |
| new_paper | 4,000자 | 1,200 |
| classic_paper | 5,000자 | 1,500 |

`classic_paper`는 1편만 처리하므로 토큰 한도를 높여 품질 우선.

### 4-4. Dedup 재활용

클래식 논문도 기존 `DeduplicationStore`를 그대로 재활용.  
같은 논문이 다른 주에 재발행되는 것을 방지.

---

## 5. 구현 순서 (단계별)

### Phase A — 모델/설정 확장 (Breaking change 없음)
1. `models.py`: `RawItem.content_type`, `Report.pipeline_mode` 추가 (기본값으로 하위호환)
2. `config.py`: `pipeline_mode`, `items_per_new_paper`, `items_per_classic` 추가

### Phase B — Scorer/Analyzer/Synthesizer 모드-aware화
3. `scorer.py`: `mode` 파라미터 + 프롬프트 선택 로직
4. `prompts/scorer_news.md`: 기존 `scorer.md`를 복사 후 이름 변경
5. `prompts/scorer_new_paper.md`, `scorer_classic_paper.md`: 신규 작성
6. `analyzer.py` + 프롬프트 3종, `synthesizer.py` + 프롬프트 3종 동일 패턴 적용

### Phase C — 프롬프트 캐싱 적용
7. `scorer.py`, `analyzer.py`, `synthesizer.py`에 `cache_control` 추가
8. 2단계 스코어링 (news 모드 Haiku → Sonnet)

### Phase D — 신규 수집기
9. `collection/semantic_scholar.py` 구현
10. `data/classic_papers_seed.json` 큐레이션 목록 작성 (50편)
11. `collection/registry.py`: `build_registry(mode)` 모드-aware 팩토리

### Phase E — 포맷/배포 + 엔트리포인트
12. `formatting/classic_paper.py` + `formatting/twitter.py` 모드 분기
13. `scripts/run_new_papers.py`, `scripts/run_classic_paper.py`
14. `.github/workflows/publish_new_papers.yml`, `publish_classic_paper.yml`

### Phase F — 테스트
15. `tests/test_collection.py`: SemanticScholarCollector 유닛 테스트
16. `tests/test_scoring.py`: 모드별 프롬프트 로딩 테스트
17. 각 모드 `DRY_RUN=true MOCK_CLAUDE=true`로 E2E 검증

---

## 6. 파일 변경 요약

### 수정 파일 (7개)
| 파일 | 변경 내용 |
|------|---------|
| `src/newsbot/models.py` | `RawItem.content_type`, `Report.pipeline_mode` 추가 |
| `src/newsbot/config.py` | `pipeline_mode`, `items_per_classic`, `items_per_new_paper` 추가 |
| `src/newsbot/collection/registry.py` | `build_registry(mode)` 팩토리로 교체 |
| `src/newsbot/scoring/scorer.py` | 모드별 프롬프트 선택 + 프롬프트 캐싱 |
| `src/newsbot/generation/analyzer.py` | 모드별 프롬프트 선택 + metadata 필드 |
| `src/newsbot/generation/synthesizer.py` | 모드별 프롬프트 선택 |
| `src/newsbot/formatting/twitter.py` | 모드 분기 포맷 |

### 신규 파일 (17개)
| 파일 | 설명 |
|------|------|
| `src/newsbot/collection/semantic_scholar.py` | 클래식 논문 수집기 |
| `data/classic_papers_seed.json` | 큐레이션 논문 목록 50편 |
| `src/newsbot/generation/prompts/scorer_news.md` | 기존 scorer.md 대체 |
| `src/newsbot/generation/prompts/scorer_new_paper.md` | 신논문 스코어링 기준 |
| `src/newsbot/generation/prompts/scorer_classic_paper.md` | 클래식 논문 스코어링 기준 |
| `src/newsbot/generation/prompts/analyzer_news.md` | 기존 analyzer.md 대체 |
| `src/newsbot/generation/prompts/analyzer_new_paper.md` | 신논문 분석 프롬프트 |
| `src/newsbot/generation/prompts/analyzer_classic_paper.md` | 클래식 논문 분석 프롬프트 |
| `src/newsbot/generation/prompts/synthesizer_news.md` | 기존 synthesizer.md 대체 |
| `src/newsbot/generation/prompts/synthesizer_new_paper.md` | 신논문 종합 프롬프트 |
| `src/newsbot/generation/prompts/synthesizer_classic_paper.md` | 클래식 논문 종합 프롬프트 |
| `src/newsbot/formatting/classic_paper.py` | 클래식 논문 Markdown 포맷 |
| `scripts/run_new_papers.py` | 신논문 파이프라인 엔트리 |
| `scripts/run_classic_paper.py` | 클래식 논문 파이프라인 엔트리 |
| `.github/workflows/publish_new_papers.yml` | 화요일 신논문 워크플로 |
| `.github/workflows/publish_classic_paper.yml` | 목요일 클래식 논문 워크플로 |
| `tests/test_multi_channel.py` | 멀티 채널 통합 테스트 |

---

## 7. 리스크 및 대응

| 리스크 | 대응 |
|--------|------|
| Semantic Scholar API 레이트 리밋 (100 req/5min) | `asyncio.Semaphore(3)` + 지수 백오프 |
| 클래식 논문 시드 소진 | SQLite에서 발행 이력 관리, 자동 Semantic Scholar 폴백 |
| 모드별 프롬프트 품질 편차 | Phase F에서 `DRY_RUN+MOCK_CLAUDE`로 각 모드 E2E 검증 후 merge |
| 기존 `publish_daily.yml` 하위호환 | `PIPELINE_MODE` 기본값 `"news"`, 기존 동작 100% 유지 |
| 토큰 비용 증가 (새 워크플로 2개 추가) | 프롬프트 캐싱 + Haiku 1차 필터로 순증 최소화 |

---

## 8. 예상 토큰 비용 비교

| 시나리오 | 현재 (daily × 3) | 변경 후 |
|---------|-----------------|--------|
| news (일 3회) | Sonnet × ~36 calls | Haiku×30 + Sonnet×18 calls → 약 40% 절감 |
| new_paper (주 1회) | — | Sonnet × ~15 calls (5편 × 3단계) |
| classic_paper (주 1회) | — | Sonnet × ~3 calls (1편 × 3단계, 캐싱 적용) |

프롬프트 캐싱이 효과적으로 적용되면 반복 호출 시 입력 토큰 캐시 히트율 70~90% 기대.
