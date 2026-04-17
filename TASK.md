# TASK.md

> 지금 뭘 하고 있는가, 다음엔 뭘 해야 하는가.
> AI 에이전트가 세션을 시작할 때 이 파일을 먼저 읽는다.
> 완료된 항목은 `[x]`로 표시. 진행 중은 `[~]`.

---

## 현재 세션 목표

**세션 목표:** 프로젝트 문서 체계 수립 (CLAUDE.md / .clinerules / TASK.md / DECISIONS.md 분리 작성)

**다음 세션에서 할 일:** Phase 1 코드 작성 시작 — `models.py` + `config.py` + HackerNews 수집기

---

## 전체 로드맵

### Phase 1 — 기반 + X 단일 채널

#### 프로젝트 초기화
- [x] `uv init` + `pyproject.toml` 작성
- [x] 의존성 추가: `anthropic`, `httpx`, `beautifulsoup4`, `feedparser`, `praw`, `tweepy`, `sentence-transformers`, `numpy`, `pydantic-settings`, `ruff`, `pytest`, `pytest-asyncio`
- [x] `.env.example` 작성
- [x] `.gitignore` 작성

#### 공통 기반
- [x] `src/newsbot/models.py` — `RawItem`, `ScoredItem`, `AnalyzedItem`, `Report` 데이터클래스
- [x] `src/newsbot/config.py` — pydantic-settings로 환경변수 관리

#### Collection Layer
- [x] `collection/base.py` — `BaseCollector` ABC
- [x] `collection/hackernews.py` — Firebase API, score > 100 필터
- [x] `collection/arxiv.py` — cs.AI, cs.LG, cs.CL, 최근 48시간
- [x] `collection/registry.py` — `asyncio.gather()` 병렬 실행
- [x] `tests/test_collection.py`

#### Dedup Layer
- [x] `dedup/embedder.py` — `all-MiniLM-L6-v2` 로컬 임베딩
- [x] `dedup/store.py` — SQLite seen_items CRUD (코사인 유사도 0.92)
- [x] SQLite 스키마 초기화 스크립트
- [x] `tests/test_dedup.py`

#### Scoring Layer
- [x] `generation/prompts/scorer.md` — 4축 스코어링 프롬프트
- [x] `scoring/scorer.py` — Claude API 호출, JSON 응답 파싱
- [x] `scoring/feedback.py` — DB 피드백 가중치 계산 (Phase 1에서는 stub)
- [x] `tests/test_scoring.py`

#### Generation Layer
- [x] `generation/prompts/analyzer.md` — 아이템별 심층 분석 프롬프트
- [x] `generation/prompts/synthesizer.md` — 전체 종합 프롬프트
- [x] `generation/fetcher.py` — httpx + BS4 원문 fetch, 실패 시 fallback
- [x] `generation/analyzer.py` — 아이템별 분석 (`asyncio.gather` 병렬)
- [x] `generation/synthesizer.py` — 전체 트렌드 종합
- [x] `tests/test_generation.py`

#### Quality Gate
- [x] `generation/prompts/quality_check.md`
- [x] `quality/checker.py` — 길이/한글비율/반복/섹션 체크
- [x] 재시도 로직 (최대 2회, 실패 시 스킵)

#### Distribution (X만)
- [x] `formatting/base.py` — `BaseFormatter` ABC
- [x] `formatting/twitter.py` — 280자 스레드 분할
- [x] `distribution/base.py` — `BasePublisher` ABC
- [x] `distribution/twitter_pub.py` — tweepy Client, DRY_RUN 분기
- [x] `distribution/github_issue.py` — 아카이브용
- [x] `tests/test_formatting.py`

#### 실행 + Actions
- [x] `scripts/run_pipeline.py` — 로컬 실행 진입점
- [x] `.github/workflows/publish_daily.yml` — X 배포 동작 확인
- [x] Actions cache 설정 (newsbot.db 영속성)
- [x] `monitoring/summary.py` — Actions Summary 생성

**Phase 1 완료 기준:** 로컬에서 `DRY_RUN=false`로 실행 시 X에 스레드가 실제 게시됨.

---

### Phase 2 — 멀티채널 완성

#### 추가 수집기
- [ ] `collection/reddit.py` — PRAW, upvotes > 200
- [ ] `collection/github_trending.py` — HTML 스크래핑
- [ ] `collection/rss.py` — feedparser
- [ ] `collection/huggingface.py` — 비공식 API

#### WhatsApp
- [ ] `formatting/whatsapp.py`
- [ ] `distribution/whatsapp_pub.py` — WhatsApp Business Cloud API
- [ ] WhatsApp 관련 Secrets 설정 가이드 작성

#### Substack
- [ ] `formatting/substack.py` — HTML 이메일 (인라인 CSS)
- [ ] `distribution/substack_pub.py` — 비공식 API
- [ ] `.github/workflows/publish_weekly.yml` — 매주 월요일 09:00 KST
- [ ] `scripts/run_weekly.py`

#### 썸네일
- [ ] `generation/thumbnail.py` — Gemini Imagen 3

#### 피드백 루프
- [ ] `feedback/collector.py` — X likes/reposts 수집
- [ ] `.github/workflows/feedback_sync.yml` — 일 1회 실행
- [ ] `scoring/feedback.py` 실제 구현 (Phase 1 stub → 실제 DB 연동)

#### 모니터링
- [ ] `monitoring/notifier.py` — 실패 시 WhatsApp/Slack webhook 알림

**Phase 2 완료 기준:** X + WhatsApp + Substack 세 채널 모두 무인 자동 배포.

---

### Phase 3 — 멀티 언어 (선택)

- [ ] `generation/prompts/translator.md` — 한→영 현지화 프롬프트
- [ ] `multilingual/translator.py`
- [ ] 영어 X 계정 + Substack EN edition 배포 설정
- [ ] `ENABLE_MULTILINGUAL=true` 전환 후 검증

---

## 알려진 이슈 / 블로커

| 이슈 | 상태 | 비고 |
|------|------|------|
| Substack 공식 API 없음 | 조사 필요 | 비공식 API or 이메일 발행 방식 결정 필요 → DECISIONS.md 참고 |
| WhatsApp Business 앱 승인 | 대기 필요 | Meta 개발자 앱 승인에 수일 소요 가능 |
| GitHub Trending 스크래핑 | 취약 | HTML 구조 변경 시 파서 깨짐, 주기적 확인 필요 |
