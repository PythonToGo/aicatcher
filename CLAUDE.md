# CLAUDE.md

> AI가 이 레포를 처음 열었을 때 읽는 파일.
> 프로젝트의 **목적, 구조, 컨벤션**을 담는다.
> "왜 이렇게 만들었는가"는 DECISIONS.md를 참고.
> 지금 뭘 해야 하는가는 TASK.md를 참고.

---

## 프로젝트 한 줄 요약

AI/ML 트렌드를 **심층 분석**해서 X(Twitter), Substack, WhatsApp으로 **완전 자동 배포**하는 뉴스레터 봇.

---

## 타겟 플랫폼

| 채널 | 주기 | 포맷 |
|------|------|------|
| X(Twitter) | 하루 3회 | 스레드 (최대 8트윗) |
| WhatsApp | 하루 3회 | 단문 브리핑 + Substack 링크 |
| Substack | 주 1회 (월요일) | HTML 심층 뉴스레터 |

---

## 아키텍처 — 파이프라인 흐름

```
[Collection]   → 멀티소스 병렬 수집 (HN, ArXiv, Reddit, RSS, GitHub Trending, HuggingFace)
     ↓
[Dedup]        → sentence-transformers 임베딩 + 코사인 유사도로 의미론적 중복 제거
     ↓
[Scoring]      → Claude API로 4축 스코어링 (임팩트/신선도/실무가치/콘텐츠화)
     ↓
[Generation]   → fetch 원문 → 아이템별 분석 → 전체 종합 (3단계)
     ↓
[Quality Gate] → 자동 품질 검사, 기준 미달 시 최대 2회 재생성
     ↓
[Multilingual] → 한국어 마스터 → 영어 현지화 (Phase 2, 플래그로 on/off)
     ↓
[Formatting]   → 채널별 포맷 변환 (twitter.py / substack.py / whatsapp.py)
     ↓
[Distribution] → 각 채널 API 자동 배포
     ↓
[Monitoring]   → Actions Summary + 실패 알림
```

---

## 디렉토리 구조

```
project-root/
├── CLAUDE.md
├── DECISIONS.md
├── TASK.md
├── .clinerules
├── .env.example
├── pyproject.toml
│
├── .github/workflows/
│   ├── publish_daily.yml       # X + WhatsApp (하루 3회)
│   ├── publish_weekly.yml      # Substack (주 1회)
│   ├── collect_only.yml        # 디버그용
│   └── feedback_sync.yml       # X 반응 수집 (일 1회)
│
├── src/newsbot/
│   ├── config.py               # pydantic-settings 환경변수
│   ├── models.py               # RawItem, ScoredItem, AnalyzedItem, Report
│   │
│   ├── collection/             # 수집기들
│   │   ├── base.py
│   │   ├── hackernews.py       # Firebase API
│   │   ├── arxiv.py            # 공식 API
│   │   ├── reddit.py           # PRAW
│   │   ├── github_trending.py  # HTML 스크래핑 (유일한 크롤링)
│   │   ├── rss.py              # feedparser
│   │   ├── huggingface.py      # 비공식 API
│   │   └── registry.py         # asyncio.gather 병렬 실행
│   │
│   ├── dedup/
│   │   ├── embedder.py         # all-MiniLM-L6-v2 (로컬, 무료)
│   │   └── store.py            # SQLite CRUD
│   │
│   ├── scoring/
│   │   ├── scorer.py
│   │   └── feedback.py         # 피드백 가중치
│   │
│   ├── generation/
│   │   ├── fetcher.py          # 원문 fetch (httpx + BS4)
│   │   ├── analyzer.py         # 아이템별 심층 분석
│   │   ├── synthesizer.py      # 전체 종합
│   │   ├── thumbnail.py        # Gemini Imagen 3
│   │   └── prompts/
│   │       ├── scorer.md
│   │       ├── analyzer.md
│   │       ├── synthesizer.md
│   │       ├── quality_check.md
│   │       └── translator.md
│   │
│   ├── quality/
│   │   └── checker.py
│   │
│   ├── multilingual/           # Phase 2
│   │   └── translator.py
│   │
│   ├── formatting/
│   │   ├── base.py
│   │   ├── twitter.py
│   │   ├── substack.py
│   │   └── whatsapp.py
│   │
│   ├── distribution/
│   │   ├── base.py
│   │   ├── twitter_pub.py      # tweepy X API v2
│   │   ├── substack_pub.py     # 비공식 API
│   │   ├── whatsapp_pub.py     # WhatsApp Business Cloud API
│   │   └── github_issue.py     # 아카이브
│   │
│   └── monitoring/
│       ├── summary.py          # Actions Summary
│       └── notifier.py         # 실패 알림
│
├── data/
│   └── newsbot.db              # SQLite (seen_items, feedback, logs)
│
├── reports/                    # 생성된 리포트 아카이브
│   ├── YYYYMMDD-HHMM-ko.md
│   ├── YYYYMMDD-HHMM-twitter-ko.txt
│   └── images/
│
├── scripts/
│   ├── run_pipeline.py         # 로컬 daily 실행
│   ├── run_weekly.py           # 로컬 weekly 실행
│   └── backfill_embeddings.py
│
└── tests/
    ├── test_collection.py
    ├── test_dedup.py
    ├── test_scoring.py
    ├── test_generation.py
    └── test_formatting.py
```

---

## 핵심 데이터 모델

```python
# models.py — 전체 파이프라인의 데이터 계약

@dataclass
class RawItem:
    title: str
    url: str
    body: str           # 원문 요약 or 리드 문단
    source: str         # "hackernews" | "arxiv" | "reddit" | ...
    published_at: datetime
    raw_score: float    # 소스 자체 점수 (HN points, upvotes 등)
    metadata: dict = field(default_factory=dict)

@dataclass
class ScoredItem:
    raw: RawItem
    score: float        # 1.0 ~ 10.0
    score_reason: str
    full_article: str = ""

@dataclass
class AnalyzedItem:
    scored: ScoredItem
    summary_ko: str
    context: str        # 맥락/배경
    implications: str   # 실무 시사점
    limitations: str    # 한계/의문
    related_urls: list[str] = field(default_factory=list)

@dataclass
class Report:
    report_id: str          # YYYYMMDD-HHMM
    items: list[AnalyzedItem]
    headline: str
    trend_analysis: str
    thumbnail_path: str = ""
    language: str = "ko"
    generated_at: datetime = field(default_factory=datetime.utcnow)
```

---

## 코딩 컨벤션

- Python **3.12+**, 타입 힌트 모든 함수 시그니처에 필수
- 패키지 관리: `uv` (pip/poetry 대신)
- 린터 + 포맷터: `ruff` 통합
- 비동기: 수집기 + fetch는 `async/await` + `asyncio.gather()` 병렬화
- 외부 API 호출: 반드시 `try/except` + 구조화 로깅
- 비밀값: 코드 하드코딩 절대 금지 → 환경변수만
- **프롬프트: Python 인라인 문자열 금지 → `prompts/*.md` 파일로 분리**
- 각 레이어: 독립 단위 테스트 가능하게 설계
- `DRY_RUN=true` 시: 외부 API 호출 없이 mock 반환 (모든 레이어 공통)

---

## 환경 변수 전체 목록

```bash
# 필수
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=           # Gemini Imagen 3

# 선택 (없으면 해당 기능 스킵)
TAVILY_API_KEY=           # 웹 검색 보조

# X(Twitter)
TWITTER_BEARER_TOKEN=
TWITTER_API_KEY=
TWITTER_API_SECRET=
TWITTER_ACCESS_TOKEN=
TWITTER_ACCESS_SECRET=

# Substack
SUBSTACK_EMAIL=
SUBSTACK_PASSWORD=
SUBSTACK_PUBLICATION_URL=

# WhatsApp Business
WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_GROUP_ID=

# 동작 설정
CONTENT_TOPIC=AI/ML
ITEMS_PER_REPORT=6
ITEMS_PER_WEEKLY=12
QUALITY_MIN_SCORE=0.8
DEDUP_SIMILARITY_THRESHOLD=0.92
DEFAULT_LANGUAGE=ko
ANALYSIS_MODE=light
ENABLE_MULTILINGUAL=false
DRY_RUN=false
LOG_LEVEL=INFO
```

---

## 참고 자료

- 원본 레포: https://github.com/leaf468/autothreads
- Anthropic API: https://docs.anthropic.com
- Gemini Imagen 3: https://ai.google.dev/gemini-api/docs/imagen
- sentence-transformers: https://www.sbert.net
- tweepy (X API v2): https://docs.tweepy.org/en/stable/
- WhatsApp Business Cloud API: https://developers.facebook.com/docs/whatsapp/cloud-api
- uv: https://docs.astral.sh/uv
