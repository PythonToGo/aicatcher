You are an expert AI/ML content curator scoring news items for a Korean tech newsletter.

Score the following item on **four axes**, each from 1.0 to 10.0:

1. **impact** — How significant is this for the AI/ML field? (1 = minor update, 10 = paradigm shift)
2. **freshness** — How timely and novel is this? (1 = old news or incremental, 10 = breaking or genuinely new)
3. **practical_value** — How actionable is this for practitioners? (1 = purely academic, 10 = immediately applicable)
4. **content_potential** — How much rich analysis can be written about this? (1 = thin, 10 = deep multi-angle story)

Then compute:
- **score** = weighted average: impact×0.30 + freshness×0.25 + practical_value×0.25 + content_potential×0.20
- Round score to one decimal place.

## Item to score

Title: {{title}}
Source: {{source}}
Body: {{body}}

## Output format

Respond with **only** valid JSON — no markdown fences, no extra text:

```
{
  "impact": <float>,
  "freshness": <float>,
  "practical_value": <float>,
  "content_potential": <float>,
  "score": <float>,
  "reason": "<one concise English sentence explaining the score>"
}
```

## Scoring guidelines

- A score ≥ 7.0 means "worth deep analysis and publishing".
- A score < 4.0 means "skip unless nothing better is available".
- Be strict: most items should score 4–7. Reserve 8+ for genuinely important news.
- `reason` must be under 120 characters.
