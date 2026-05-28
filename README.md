# aicatcher

AI/ML 트렌드를 심층 분석해서 X(Twitter), Substack, WhatsApp으로 완전 자동 배포하는 뉴스레터 봇.

---

## 스케줄링 구조

GitHub Actions의 `schedule` 트리거는 고부하 시 수 시간 지연이 발생하므로, **cron-job.org**가 정확한 시각에 `workflow_dispatch`를 트리거하는 방식으로 운영합니다.

```
cron-job.org (Europe/Berlin 기준 정각)
    → POST /repos/PythonToGo/aicatcher/actions/workflows/publish_daily.yml/dispatches
    → GitHub Actions 즉시 실행
```

### 발행 시각

| 잡 이름 | 시각 (CEST/CET) | UTC |
|---------|----------------|-----|
| morning routine | 08:00 | 06:00 |
| evening routine | 19:00 | 17:00 |

---

## cron-job.org 설정

### 사전 준비: GitHub PAT 발급

[github.com/settings/tokens](https://github.com/settings/tokens) → **Tokens (classic)** → Generate new token

- **Scopes**: `workflow` 체크

### 잡 설정 (아침/저녁 각각)

| 항목 | 값 |
|------|----|
| URL | `https://api.github.com/repos/PythonToGo/aicatcher/actions/workflows/publish_daily.yml/dispatches` |
| Method | `POST` |
| Timezone | `Europe/Berlin` |

**Headers:**

| Key | Value |
|-----|-------|
| `Authorization` | `Bearer <GitHub PAT>` |
| `Accept` | `application/vnd.github+json` |
| `X-GitHub-Api-Version` | `2022-11-28` |
| `Content-Type` | `application/json` |

**Request body:**

```json
{"ref": "main"}
```

### 테스트

ACTIONS → **Execute now** → HTTP `204 No Content` 응답 확인 → GitHub Actions 탭에서 워크플로우 실행 확인.
