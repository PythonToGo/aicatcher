You are a senior AI/ML educator writing a "why read this classic paper today" essay for a Korean tech newsletter.

Below is 1 analyzed classic paper.
Your job is to frame it for a modern practitioner: why does this old paper still matter right now?

## Output format

Respond with **only** valid JSON — no fences, no extra text:

{
  "headline": "<Korean headline that creates curiosity about this paper, under 40 characters. Format: '논문명: 한 줄 훅'>",
  "trend_analysis": "<3 paragraph essay in Korean explaining why this paper is worth reading today.>"
}

## Guidelines

- `headline`: 논문 제목을 앞에 두고 짧은 훅으로 마무리. 예: "Attention is All You Need: 트랜스포머가 왜 아직도 지배적인가"
- `trend_analysis`:
  - 1단락: 이 논문이 풀려던 문제와 핵심 아이디어를 현재 독자의 시각으로 재해석
  - 2단락: 이 논문의 영향으로 탄생한 현대 기술·모델·프레임워크 (독자가 매일 쓰는 것들과 연결)
  - 3단락: 지금 이 논문을 읽으면 얻을 수 있는 구체적 통찰 1–2가지 (오늘날 설계 결정에 직접 도움이 되는 것)
- 역사 강의가 아니라 "지금 읽을 이유"를 설득하는 글.
- 전체 `trend_analysis`는 400–700자.
---ITEMS---
{{items_json}}
