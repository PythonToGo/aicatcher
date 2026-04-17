# DECISIONS.md

> 프로젝트에서 내린 **설계 결정과 그 이유**를 기록한다.
> "왜 이렇게 만들었는가"를 나중에 돌아볼 때, 또는 AI가 맥락을 파악할 때 읽는다.
> ADR(Architecture Decision Record) 형식. 결정을 번복할 때도 여기에 기록한다.

---

## ADR-001 — 임베딩 기반 중복 제거 채택

**날짜:** 2026-04-17
**상태:** 확정

**배경:**
autothreads는 파일명 기반으로 중복을 체크한다. "GPT-5 출시"와 "GPT-5 드디어 공개됐다"를 다른 뉴스로 인식하는 문제가 있다.

**결정:**
`sentence-transformers/all-MiniLM-L6-v2` 모델로 임베딩을 생성하고, 코사인 유사도 0.92 이상이면 중복으로 판단한다.

**이유:**
- 로컬 실행 → 비용 없음
- GitHub Actions Ubuntu에서 동작 (모델 약 80MB)
- OpenAI embedding API 대비 비용 절감, 속도도 빠름
- 0.92 임계값: 실험적으로 false positive(다른 뉴스를 중복으로 오판)와 false negative(실제 중복을 통과) 사이의 균형점

**트레이드오프:**
- 첫 실행 시 모델 다운로드로 Actions 실행 시간 약 30초 증가
- 임계값 0.92는 고정이 아니라 `.env`로 오버라이드 가능하게 설계

---

## ADR-002 — Actions cache로 SQLite DB 영속성 확보

**날짜:** 2026-04-17
**상태:** 확정

**배경:**
autothreads는 GitHub Actions 워크플로우가 끝나면 상태가 초기화된다. seen_items가 실행마다 리셋되어 중복 제거가 사실상 무의미하다.

**결정:**
`actions/cache`를 사용해 `data/newsbot.db`를 워크플로우 간에 보존한다.

```yaml
- uses: actions/cache@v4
  with:
    path: data/newsbot.db
    key: newsbot-db-${{ github.run_id }}
    restore-keys: newsbot-db-
```

**이유:**
- `restore-keys: newsbot-db-`로 가장 최근 캐시를 항상 복원
- SQLite는 단일 파일이라 캐시 대상으로 적합
- 별도 외부 DB(Supabase 등) 없이 무료로 영속성 확보

**트레이드오프:**
- Actions cache는 7일 미사용 시 자동 삭제됨. 7일 이상 실행 안 하면 seen_items 리셋.
- 동시 실행(concurrent workflows) 시 캐시 충돌 가능 → publish_daily는 `concurrency` 설정으로 직렬화.

---

## ADR-003 — 3단계 생성 파이프라인 (fetch → analyze → synthesize)

**날짜:** 2026-04-17
**상태:** 확정

**배경:**
autothreads는 Claude API를 한 번 호출해서 수집된 아이템을 번역·요약한다. 깊이가 없고, 아이템 간 연결고리나 실무 시사점이 없다.

**결정:**
3단계로 분리한다.
1. **fetch:** Top N 아이템의 원문 URL을 실제로 읽어옴
2. **analyze:** 아이템별 개별 Claude 호출 (asyncio.gather로 병렬)
3. **synthesize:** 전체 종합 + 아이템 간 연결고리 발견

**이유:**
- 원문을 실제로 읽어야 "왜 지금인가", "실무 시사점" 같은 분석이 가능
- 아이템별 분석을 병렬화해서 N배 호출이어도 시간은 1회 호출과 유사
- 마지막 종합 단계에서 아이템 간 패턴을 발견할 수 있음

**트레이드오프:**
- Claude API 호출 횟수 증가 → 비용 약 $3-4/월 추가
- fetch 실패 시 원래 body 텍스트로 fallback (파이프라인 중단 없음)
- 총 실행 시간 약 3-5분 증가

---

## ADR-004 — 발행 주기: daily 3회 + weekly 1회

**날짜:** 2026-04-17
**상태:** 확정

**배경:**
autothreads는 하루 6회 고정 cron. 뉴스가 없어도 발행하고, 품질보다 빈도에 집중하는 구조.

**결정:**
- X + WhatsApp: 하루 3회 (08:00, 13:00, 20:00 KST)
- Substack: 주 1회 (월요일 09:00 KST)

**이유:**
- 3회: 출근 전 / 점심 / 퇴근 후 — 독자 행동 패턴에 맞춤
- 6회에서 3회로 줄이면 Claude API 비용 절반, 품질에 더 집중 가능
- Substack은 짧은 브리핑보다 깊은 분석이 맞는 채널이므로 주 1회 심층호

**트레이드오프:**
- 빈도 감소로 실시간성 일부 포기
- Breaking news 대응 불가 → 대신 `workflow_dispatch`로 수동 실행 가능

---

## ADR-005 — Substack 배포 방식: 비공식 API 사용

**날짜:** 2026-04-17
**상태:** 검토 중 (결정 보류)

**배경:**
Substack은 공식 배포 API를 제공하지 않는다.

**선택지:**
- **Option A:** 비공식 `/api/v1/posts` 엔드포인트 (세션 쿠키 기반)
- **Option B:** Substack 이메일 발행 기능 (특정 이메일 수신 시 초안 생성)

**현재 판단:**
Option A를 먼저 시도. Substack이 비공식 API를 막으면 Option B로 전환.
비공식 API 구현 참고: https://github.com/wedjelek/substack-api

**리스크:**
- Substack 정책 변경 시 동작 중단 가능
- 세션 쿠키 만료 시 재로그인 필요

**결정 시점:** Phase 2 시작 전에 최종 결정.

---

## ADR-006 — 멀티 언어를 Phase 2로 미룸

**날짜:** 2026-04-17
**상태:** 확정

**배경:**
처음부터 한국어 + 영어를 동시에 운영하면 복잡도와 비용이 2배.

**결정:**
`ENABLE_MULTILINGUAL=false` 플래그로 Phase 2에서 활성화. 코드 구조는 처음부터 멀티 언어를 고려해 설계하되 (Report.language 필드, multilingual/ 디렉토리 존재), 실제 번역 파이프라인은 Phase 2에서 구현.

**이유:**
- Phase 1에서 한국어 파이프라인의 품질과 안정성을 먼저 검증
- 영어 번역은 "현지화(Localization)" 방식 — 추가 프롬프트 설계 시간 필요
- 플래그 하나로 켜고 끌 수 있도록 설계하면 전환 비용 낮음

---

## ADR-007 — 프롬프트를 .md 파일로 분리

**날짜:** 2026-04-17
**상태:** 확정

**결정:**
모든 Claude 프롬프트는 `src/newsbot/generation/prompts/*.md` 파일로 분리. Python 코드 안에 인라인 문자열로 작성 금지.

**이유:**
- Git에서 프롬프트 변경 이력 추적 가능
- 코드 수정 없이 프롬프트만 실험/튜닝 가능
- `.clinerules`에서도 이를 명시적으로 강제
- 프롬프트 파일만 수정하는 PR과 코드 수정 PR을 분리할 수 있음

---

## ADR-008 — 패키지 매니저로 uv 채택

**날짜:** 2026-04-17
**상태:** 확정

**결정:** pip, poetry 대신 `uv` 사용.

**이유:**
- pip 대비 10-100배 빠른 설치
- GitHub Actions에서 캐시 없이도 빠른 의존성 설치
- `pyproject.toml` 표준 준수
- lock 파일(`uv.lock`) 지원으로 재현 가능한 빌드

**트레이드오프:**
- uv에 익숙하지 않으면 초기 러닝커브
- 일부 엣지케이스에서 pip와 다른 동작 가능
