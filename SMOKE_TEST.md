# 로컬 스모크 테스트 가이드

Twitter 없이, 로컬에서 파이프라인 전체를 실행하고 결과를 파일로 확인하는 방법.

---

## 0. API 없이 즉시 실행 (Mock 모드)

API 키 없이 전체 파이프라인 흐름을 확인하고 싶다면:

```bash
cp .env.example .env
# .env 에서 MOCK_CLAUDE=true, DRY_RUN=true 로 변경
MOCK_CLAUDE=true DRY_RUN=true uv run python scripts/run_pipeline.py
```

또는 `.env`에 아래처럼 설정:

```bash
ANTHROPIC_API_KEY=dummy     # mock 모드에서는 실제로 사용하지 않지만 필드가 필수라 채워야 함
MOCK_CLAUDE=true
DRY_RUN=true
ITEMS_PER_REPORT=3
LOG_LEVEL=INFO
```

Mock 모드에서는:
- **API 호출 없음** — 과금 없음, 네트워크 불필요
- 수집(Collection)·중복제거(Dedup)·원문 fetch는 **실제로** 동작 (HN/ArXiv 실제 호출)
- Scoring/Analyze/Quality/Synthesize는 샘플 한국어 텍스트로 즉시 반환
- `reports/` 폴더에 동일한 형식의 `.md`, `.txt` 파일 생성

출력 예시:
```
[MOCK] mock_claude=true — API 호출 없이 실행
[MOCK] scoring 18 items (no API call)
[MOCK] analyzing 3 items (no API call)
[MOCK] quality check bypassed for 3 items
[MOCK] synthesizing 3 items → report 20260417-2000 (no API call)
report saved → reports/20260417-2000-ko.md
```

> 실제 Claude 분석 결과가 필요하면 아래 1~3번을 따라 API 키를 설정하세요.

---

## 1. ANTHROPIC_API_KEY 발급

1. [console.anthropic.com](https://console.anthropic.com) 접속
2. 우측 상단 프로필 → **API Keys**
3. **Create Key** → 이름 입력 → 키 복사 (`sk-ant-...` 형식)

> 과금 주의: 스모크 1회 실행 시 약 $0.10~0.30 소요 (Sonnet + Haiku 혼합).

---

## 2. .env 파일 작성

```bash
cp .env.example .env
```

`.env`를 열고 최소한 아래만 채운다:

```bash
# 필수 (스모크 테스트에 필요한 것만)
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxx

# Twitter는 비워두면 자동 스킵
TWITTER_BEARER_TOKEN=
TWITTER_API_KEY=
TWITTER_API_SECRET=
TWITTER_ACCESS_TOKEN=
TWITTER_ACCESS_SECRET=

# DRY_RUN — true 이면 외부 API 배포 없음
DRY_RUN=true

# 아이템 수 줄이면 API 비용 절감
ITEMS_PER_REPORT=3
LOG_LEVEL=INFO
```

---

## 3. 파이프라인 실행

```bash
uv run python scripts/run_pipeline.py
```

실행 중 터미널에 진행 로그가 출력된다:

```
2026-04-17T20:00:00 [INFO] __main__: === newsbot pipeline start | DRY_RUN=True ===
2026-04-17T20:00:02 [INFO] ...collection...: collected 24 raw items
2026-04-17T20:00:03 [INFO] ...dedup...: dedup: 18/24 items are new
2026-04-17T20:00:15 [INFO] ...scorer...: scored 18 items
2026-04-17T20:00:30 [INFO] ...analyzer...: analyzed 3 items
2026-04-17T20:00:35 [INFO] ...checker...: 3/3 items passed
2026-04-17T20:00:40 [INFO] ...synthesizer...: report 20260417-2000 created: ...
2026-04-17T20:00:40 [INFO] __main__: report saved → reports/20260417-2000-ko.md
2026-04-17T20:00:40 [INFO] [DRY_RUN][twitter] would publish report 20260417-2000
2026-04-17T20:00:40 [INFO] === newsbot pipeline done ===
```

---

## 4. 결과 확인

실행 후 `reports/` 폴더에 두 파일이 생성된다:

```
reports/
├── 20260417-2000-ko.md          ← 전체 분석 리포트 (마크다운)
└── 20260417-2000-twitter-ko.txt ← 트윗 스레드 미리보기
```

### 리포트 마크다운 보기

```bash
cat reports/20260417-2000-ko.md
```

또는 VS Code에서 `Cmd+Shift+V`로 미리보기.

### 트윗 스레드 미리보기

```bash
cat reports/20260417-2000-twitter-ko.txt
```

출력 예시:
```
=== Tweet 1/5 ===
AI 추론 비용 전쟁이 시작됐다

이번 주 AI 업계는 추론 비용 절감에 집중했습니다...

(1/5)

=== Tweet 2/5 ===
(2/5) GPT-5가 출시되어 업계에 큰 반향을...

https://openai.com/gpt-5

...
```

---

## 5. 실제 Twitter 게시 (준비됐을 때)

Twitter API 키를 `.env`에 채운 뒤:

```bash
DRY_RUN=false uv run python scripts/run_pipeline.py
```

또는 `.env`에서 `DRY_RUN=false`로 변경 후 실행.

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `ANTHROPIC_API_KEY` 오류 | `.env` 파일 없음 또는 키 오류 | `.env` 파일 확인 |
| `no items collected` | HN / ArXiv API 일시 장애 | 잠시 후 재시도 |
| `all items are duplicates` | `data/newsbot.db` 초기화 필요 | `rm data/newsbot.db` |
| `no items passed quality gate` | AI/ML 뉴스가 부족한 시간대 | `ITEMS_PER_REPORT=10`으로 늘리기 |
