# Changelog

---

## [Phase E] 포맷터 + 엔트리포인트 + 워크플로 — 2026-05-20

### 개요

3개 파이프라인 모드에 맞는 포맷터를 구현하고, 모드별 실행 스크립트와 GitHub Actions 워크플로를 추가.

---

### 신규 파일

#### `src/newsbot/formatting/classic_paper.py`

| 함수 | 출력 | 용도 |
|------|------|------|
| `format_classic_paper_md(report)` | Markdown | GitHub 아카이브, 로컬 저장 |
| `format_classic_paper_html(report)` | HTML | 이메일 본문 |

구조: 📚 클래식 논문 리뷰 헤더 → "왜 지금 이 논문인가" → 역사적 배경 → 왜 혁신적이었나 → 오늘날 배울 것 → 한계. `extra` 필드 없으면 해당 섹션 자동 생략.

#### `scripts/run_new_papers.py`

`PIPELINE_MODE=new_paper`, `ANALYSIS_MODE=detail` 설정 후 `run_pipeline.main()` 위임. 별도 로직 없음.

#### `scripts/run_classic_paper.py`

`PIPELINE_MODE=classic_paper`, `ANALYSIS_MODE=detail`, `ITEMS_PER_REPORT=1` 설정 후 위임.

#### `.github/workflows/publish_new_papers.yml`

- 트리거: 화요일 09:00 UTC + `workflow_dispatch`
- `PIPELINE_MODE=new_paper`, `ITEMS_PER_NEW_PAPER=5`, `ANALYSIS_MODE=detail`
- 전용 DB 캐시 키 (`newsbot-db-new-papers-*`)

#### `.github/workflows/publish_classic_paper.yml`

- 트리거: 목요일 09:00 UTC + `workflow_dispatch`
- `PIPELINE_MODE=classic_paper`, `ITEMS_PER_CLASSIC=1`, `QUALITY_MIN_SCORE=0.75` (단일 논문이므로 완화)
- `SEMANTIC_SCHOLAR_API_KEY` 시크릿 연결
- 전용 DB 캐시 키 (`newsbot-db-classic-*`)

---

### 변경 파일

#### `src/newsbot/formatting/twitter.py`

`TwitterFormatter.format()` → `report.pipeline_mode` 기반 분기:
- `classic_paper`: 3-트윗 고정 (요약 / 왜 혁신적 / 배울 점 + URL)
- `new_paper`: 5-트윗 (연구 동향 헤드라인 + 논문별 methodology + 마무리)
- `news`: 기존 포맷 유지

#### `src/newsbot/formatting/email.py`

`format_email_html()` → 모드 분기:
- `classic_paper` → `format_classic_paper_html()` (녹색 헤더, 클래식 섹션)
- `new_paper` → `_format_new_paper_html()` (파란 헤더, methodology/contributions/benchmarks 섹션)
- `news` → `_format_news_html()` (기존 포맷)
- 공통 `_wrap_html()` 헬퍼로 HTML 골격 통합

#### `src/newsbot/monitoring/summary.py`

`build_report_md()` → 모드 분기:
- `classic_paper` → `format_classic_paper_md()`
- `new_paper` → `_build_new_paper_md()` (방법론/기여/벤치마크 섹션 포함)
- `news` → `_build_news_md()` (기존 포맷)

---

### 검증 결과

```
포맷터 유닛 테스트 (6개 케이스)       OK
  - classic twitter 3 tweets          OK — 📚 헤더, why_groundbreaking, URL
  - classic markdown                  OK — extra 필드 없으면 섹션 자동 생략
  - classic email HTML                OK — 녹색(#065f46) 헤더
  - build_report_md 라우팅            OK
  - new_paper twitter 5 tweets        OK — 📄 헤더, methodology, #AIResearch
  - news twitter 6 tweets             OK — 기존 포맷 유지

E2E scripts/run_new_papers.py         OK — PIPELINE_MODE=new_paper, top 5
E2E scripts/run_classic_paper.py      OK — PIPELINE_MODE=classic_paper, top 1
```

---

### 다음 단계

**Phase F** — 테스트
- `tests/test_multi_channel.py`: 모드별 통합 테스트
- 각 모드 `MOCK_CLAUDE=true` E2E 검증 자동화

---

## [Phase D] 신규 수집기 + 레지스트리 팩토리 — 2026-05-20

### 개요

3개 파이프라인 모드별 전용 수집기를 연결. `build_registry(mode)` 팩토리 하나로 올바른 수집기 세트가 자동 구성됨.

---

### 신규 파일

#### `src/newsbot/collection/semantic_scholar.py`

| 항목 | 내용 |
|------|------|
| 소스 | Semantic Scholar Public API + 큐레이션 시드 (`data/classic_papers_seed.json`) |
| 전략 | seed-first: ISO 주차 기반 배치 로테이션(10편/주) → API 폴백 |
| 레이트 리밋 | `asyncio.Semaphore(1)` (1 req/s, API 키 없음 기준) |
| `content_type` | `"classic_paper"` 고정 |
| 에러 처리 | seed 파싱 실패 / API 실패 모두 개별 skip, 파이프라인 중단 없음 |

#### `data/classic_papers_seed.json`

53편 큐레이션 목록. 분야 커버리지:

| 분야 | 대표 논문 |
|------|---------|
| Transformers / NLP | Attention is All You Need, BERT, GPT/GPT-2/GPT-3, T5, ELMo, XLNet |
| Computer Vision | AlexNet, VGGNet, ResNet, GoogLeNet, DenseNet, ViT, EfficientNet |
| Object Detection | YOLO, Faster R-CNN, FPN, Mask R-CNN, DETR |
| Generative | GAN, DCGAN, VAE, StyleGAN, DDPM |
| RL | DQN, A3C, PPO, AlphaGo |
| Optimization | Adam, BatchNorm, Dropout, LayerNorm |
| Self-supervised | MoCo, SimCLR, CLIP |
| Graph | GCN, GAT |
| Sequence | LSTM, GRU, Seq2Seq, Bahdanau Attention |
| Audio / 3D / etc | WaveNet, PointNet, U-Net |

---

### 변경 파일

#### `src/newsbot/collection/registry.py`
- `build_registry(pipeline_mode, **kwargs)` 팩토리 추가
  - `"news"` → `HackerNewsCollector()`
  - `"new_paper"` → `ArxivCollector(max_results=50, hours_back=168)` (7일치 수집)
  - `"classic_paper"` → `SemanticScholarCollector(limit=10, api_key=...)`
- `build_default_registry()` 유지 (하위호환 alias)

#### `src/newsbot/collection/arxiv.py`
- `RawItem.content_type = "new_paper"` 명시

#### `src/newsbot/collection/hackernews.py`
- `RawItem.content_type = "news"` 명시

#### `src/newsbot/config.py`
- `semantic_scholar_api_key` 옵션 추가 (없으면 public 레이트 리밋 적용)

#### `scripts/run_pipeline.py`
- `build_default_registry()` → `build_registry(settings.pipeline_mode, api_key=...)` 교체

---

### 검증 결과

```
seed 로딩 (53편)              OK — 전체 파싱 성공
seed 배치 로테이션             OK — week 기반 10편 배치
registry 팩토리 (3 모드)      OK — news/new_paper/classic_paper 각 정확한 수집기 선택
build_default_registry        OK — 하위호환 alias 동작
E2E classic_paper             OK — semantic_scholar 10편 수집 → dedup → top 1 분석
E2E new_paper                 OK — arxiv 50편 수집 → top 5 분석
E2E news                      OK — hackernews 30편 수집 → top 6 분석
```

---

### 다음 단계

**Phase E** — 포맷터 + 엔트리포인트 스크립트 + GitHub Actions 워크플로

---

## [Phase B] Scorer / Analyzer / Synthesizer 모드-aware화 + 프롬프트 캐싱 — 2026-05-20

### 개요

3개 파이프라인 모드(news / new_paper / classic_paper)에 맞게 Scorer, Analyzer, Synthesizer가 각각 다른 프롬프트를 선택하도록 변경. Anthropic `cache_control=ephemeral`로 프롬프트 캐싱 적용.

---

### 신규 프롬프트 파일 9개

모든 프롬프트는 `---ITEM---` (scorer/analyzer) 또는 `---ITEMS---` (synthesizer) 구분자로 **정적 블록 / 동적 블록** 분리. 정적 블록은 `cache_control: ephemeral`로 캐시되어 같은 실행 내 반복 호출 시 입력 토큰 ~90% 절감.

| 파일 | 스코어링 축 |
|------|-----------|
| `scorer_news.md` | impact × 0.30 + freshness × 0.25 + practical_value × 0.25 + content_potential × 0.20 |
| `scorer_new_paper.md` | novelty × 0.35 + methodology_rigor × 0.30 + practical_value × 0.20 + reproducibility × 0.15 |
| `scorer_classic_paper.md` | historical_impact × 0.35 + citation_influence × 0.25 + educational_value × 0.25 + accessibility × 0.15 (freshness 제거) |

| 파일 | 추가 분석 필드 (`AnalyzedItem.extra`) |
|------|--------------------------------------|
| `analyzer_news.md` | (없음 — 기존 4개 필드만) |
| `analyzer_new_paper.md` | `methodology`, `contributions`, `benchmark_results` |
| `analyzer_classic_paper.md` | `historical_context`, `why_groundbreaking`, `learning_points` |

| 파일 | `trend_analysis` 성격 |
|------|----------------------|
| `synthesizer_news.md` | 뉴스 흐름 + 트렌드 분석 (600–1000자) |
| `synthesizer_new_paper.md` | 이번 주 연구 동향 서사 (500–900자) |
| `synthesizer_classic_paper.md` | "왜 지금 이 논문인가" 에세이 (400–700자) |

---

### 변경 파일

#### `src/newsbot/scoring/scorer.py`
- `pipeline_mode` 파라미터 추가 (기본값 `"news"`)
- `_PROMPT_MAP` + `_load_prompt()`: 모드별 프롬프트 파일 선택
- `_build_content()`: 정적/동적 블록 분리 + `cache_control=ephemeral`
- `_validate_scores()`: `score` + `reason`만 공통 필수 — 모드별 축 이름 차이 허용

#### `src/newsbot/generation/analyzer.py`
- `pipeline_mode` 파라미터 추가 (기본값 `"news"`)
- `_PROMPT_MAP`, `_EXTRA_FIELDS`: 모드별 프롬프트 + 추가 필드 목록
- `_content_limit()`, `_max_tokens()`: 모드별 컨텍스트 한도 (classic_paper=5000자/1500토큰, new_paper=4000자/1200토큰)
- `_analyze_one()`: `extra` 필드 자동 수집
- retry 시 마지막 블록에만 suffix 추가 (캐시된 정적 블록 불변)

#### `src/newsbot/generation/synthesizer.py`
- `pipeline_mode` 파라미터 추가 (기본값 `"news"`)
- classic_paper 모드 `max_tokens=800` (1편만 처리)
- `Report.pipeline_mode` 설정
- items_json 직렬화: 모드별 포함 필드 최적화 (classic/new_paper는 extra 필드 포함)

#### `src/newsbot/quality/checker.py`
- `AnalyzerProtocol`을 `typing.Protocol`로 변경 → structural subtyping 활성화

#### `scripts/run_pipeline.py`
- Scorer / Analyzer / Synthesizer 생성 시 `pipeline_mode=settings.pipeline_mode` 전달
- `settings.items_per_report` → `settings.effective_items_per_report` 사용
- 시작 로그에 `PIPELINE_MODE` 추가

#### `src/newsbot/mock_claude.py`
- `MockSynthesizer.synthesize()`: `pipeline_mode` 파라미터 수용 → `Report.pipeline_mode` 설정

---

### 토큰 최적화 수치

| 항목 | 효과 |
|------|------|
| 프롬프트 캐싱 (정적 블록 1000–1300자) | 아이템당 입력 토큰 ~90% 절감 (5분 TTL 내 반복 호출) |
| classic_paper max_tokens=800 | 기존 synthesizer 2048 대비 61% 절감 |
| new_paper content_limit=4000자 | 논문 원문 충분히 반영하면서 news(3000자)보다 품질 우선 |

---

### 검증 결과

```
프롬프트 로딩 (9종)          OK — 정적/동적 블록 분리 확인
cache_control 구조           OK — 첫 번째 블록에 ephemeral 설정 확인
E2E PIPELINE_MODE=news       OK — top 6 items, pipeline done
E2E PIPELINE_MODE=new_paper  OK — top 5 items, pipeline done
E2E PIPELINE_MODE=classic_paper OK — top 1 item, pipeline done
```

---

### 다음 단계

**Phase D** — 신규 수집기
- `collection/semantic_scholar.py`: Semantic Scholar API + 큐레이션 시드
- `collection/registry.py`: `build_registry(mode)` 모드-aware 팩토리

---

## [Phase A] 멀티 채널 모델·설정 확장 — 2026-05-20

### 개요

단일 파이프라인을 3개 콘텐츠 채널(news / new_paper / classic_paper)로 분리하는 리팩토링의 첫 단계.
**Breaking change 없음** — 기본값이 기존 동작과 동일하도록 설계.

---

### 변경 파일

#### `src/newsbot/models.py`

| 변경 | 내용 |
|------|------|
| `RawItem.content_type: str = "news"` 추가 | 허용값: `"news"` \| `"new_paper"` \| `"classic_paper"`. 기본값 `"news"` → 기존 수집기 코드 무수정 |
| `RawItem.__post_init__` 확장 | `content_type` 유효성 검사 추가 |
| `RawItem.source` 주석 | `"semantic_scholar"` 소스 추가 명시 (Phase D에서 구현) |
| `AnalyzedItem.extra: dict = {}` 추가 | 모드별 추가 필드 수용 (new_paper: `contributions`/`benchmark_results`, classic_paper: `historical_context`/`learning_points`) |
| `Report.pipeline_mode: str = "news"` 추가 | 포맷터·배포기가 모드를 인식하기 위한 필드 |

#### `src/newsbot/config.py`

| 변경 | 내용 |
|------|------|
| `pipeline_mode: str = "news"` 추가 | 환경변수 `PIPELINE_MODE`로 제어. validator로 3개 값만 허용 |
| `items_per_new_paper: int = 5` 추가 | 신논문 모드에서 분석할 논문 수 (1~10) |
| `items_per_classic: int = 1` 추가 | 클래식 논문 모드에서 분석할 논문 수 (1~3, 기본 1) |
| `effective_items_per_report` 프로퍼티 추가 | `pipeline_mode`에 따라 올바른 아이템 수를 자동 반환 |

```python
# 사용 예
settings.effective_items_per_report
# news         → items_per_report (기본 6)
# new_paper    → items_per_new_paper (기본 5)
# classic_paper → items_per_classic (기본 1)
```

---

### 검증 결과

```
모든 모델 테스트 통과   (content_type 기본값, 유효성 검사, extra 필드)
모든 config 테스트 통과  (pipeline_mode 기본값, effective_items_per_report, ValidationError)
DRY_RUN+MOCK_CLAUDE E2E  → 기존 파이프라인 정상 동작 확인 (리포트 20260520-1306)
```

---

### 다음 단계

**Phase B** — Scorer / Analyzer / Synthesizer 모드-aware화
- `scorer.py`: mode 파라미터 + 프롬프트 파일 선택
- 프롬프트 3종 × 3 컴포넌트 = 9개 `.md` 파일 신규 작성
- `analyzer.py`: `extra` 필드 채우기 (모드별 추가 분석 필드)
- Anthropic `cache_control` 적용 (프롬프트 캐싱)
