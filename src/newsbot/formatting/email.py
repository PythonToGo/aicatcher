"""EmailFormatter — Convert a Report into an HTML email body (mode-aware)."""

from __future__ import annotations

from newsbot.models import Report


def format_email_html(report: Report) -> str:
    """Route to the appropriate HTML formatter based on pipeline_mode."""
    if report.pipeline_mode == "classic_paper":
        from newsbot.formatting.classic_paper import format_classic_paper_html
        return format_classic_paper_html(report)
    if report.pipeline_mode == "new_paper":
        return _format_new_paper_html(report)
    return _format_news_html(report)


def _format_new_paper_html(report: Report) -> str:
    """HTML email for the new_paper pipeline — includes extra fields."""
    items_html = ""
    for i, item in enumerate(report.items, 1):
        methodology = item.extra.get("methodology", "")
        contributions = item.extra.get("contributions", "")
        benchmarks = item.extra.get("benchmark_results", "")
        related = ""
        if item.related_urls:
            links = "".join(f'<li><a href="{u}">{u}</a></li>' for u in item.related_urls)
            related = f"<p><strong>관련 링크</strong></p><ul>{links}</ul>"

        def sec(label: str, text: str) -> str:
            if not text:
                return ""
            return (
                f'<p style="margin:0 0 6px;"><strong>{label}</strong></p>'
                f'<p style="margin:0 0 12px;line-height:1.6;">{text}</p>'
            )

        items_html += f"""
        <div style="margin-bottom:32px;padding-bottom:32px;border-bottom:1px solid #e5e7eb;">
          <h2 style="font-size:18px;margin:0 0 8px;">
            {i}. <a href="{item.url}" style="color:#1d4ed8;text-decoration:none;">{item.title}</a>
          </h2>
          <p style="font-size:12px;color:#6b7280;margin:0 0 12px;">
            출처: {item.scored.raw.source} &nbsp;|&nbsp; 점수: {item.score:.1f}
          </p>
          {sec("요약", item.summary_ko)}
          {sec("방법론", methodology)}
          {sec("주요 기여", contributions)}
          {sec("실험 결과", benchmarks)}
          {sec("맥락", item.context)}
          {sec("실무 시사점", item.implications)}
          {sec("한계", item.limitations)}
          {related}
        </div>
        """

    return _wrap_html(
        report,
        header_color="#1e40af",
        badge_color="#bfdbfe",
        badge_text="📄 신논문 리뷰",
        trend_title="이번 주 연구 동향",
        items_html=items_html,
    )


def _format_news_html(report: Report) -> str:
    """Original HTML email for the news pipeline."""
    items_html = ""
    for i, item in enumerate(report.items, 1):
        related = ""
        if item.related_urls:
            links = "".join(f'<li><a href="{u}">{u}</a></li>' for u in item.related_urls)
            related = f"<p><strong>관련 링크</strong></p><ul>{links}</ul>"

        items_html += f"""
        <div style="margin-bottom:32px;padding-bottom:32px;border-bottom:1px solid #e5e7eb;">
          <h2 style="font-size:18px;margin:0 0 8px;">
            {i}. <a href="{item.url}" style="color:#1d4ed8;text-decoration:none;">{item.title}</a>
          </h2>
          <p style="font-size:12px;color:#6b7280;margin:0 0 12px;">
            출처: {item.scored.raw.source} &nbsp;|&nbsp; 점수: {item.score:.1f}
          </p>
          <p style="margin:0 0 8px;"><strong>요약</strong></p>
          <p style="margin:0 0 12px;line-height:1.6;">{item.summary_ko}</p>
          <p style="margin:0 0 8px;"><strong>맥락</strong></p>
          <p style="margin:0 0 12px;line-height:1.6;">{item.context}</p>
          <p style="margin:0 0 8px;"><strong>실무 시사점</strong></p>
          <p style="margin:0 0 12px;line-height:1.6;">{item.implications}</p>
          <p style="margin:0 0 8px;"><strong>한계 및 의문</strong></p>
          <p style="margin:0 0 12px;line-height:1.6;">{item.limitations}</p>
          {related}
        </div>
        """

    return _wrap_html(
        report,
        header_color="#1d4ed8",
        badge_color="#93c5fd",
        badge_text="AI/ML 뉴스레터",
        trend_title="트렌드 분석",
        items_html=items_html,
    )


def _wrap_html(
    report: Report,
    header_color: str,
    badge_color: str,
    badge_text: str,
    trend_title: str,
    items_html: str,
) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#111827;">
  <div style="max-width:680px;margin:0 auto;padding:24px 16px;">

    <div style="background:{header_color};border-radius:8px;padding:24px;margin-bottom:32px;">
      <p style="color:{badge_color};font-size:12px;margin:0 0 8px;">{badge_text} · {report.generated_at.strftime('%Y년 %m월 %d일')}</p>
      <h1 style="color:#fff;font-size:22px;margin:0;line-height:1.4;">{report.headline}</h1>
    </div>

    <div style="background:#fff;border-radius:8px;padding:24px;margin-bottom:32px;">
      <h2 style="font-size:16px;margin:0 0 12px;color:#374151;">{trend_title}</h2>
      <p style="line-height:1.7;margin:0;">{report.trend_analysis}</p>
    </div>

    <div style="background:#fff;border-radius:8px;padding:24px;margin-bottom:32px;">
      {items_html}
    </div>

    <p style="text-align:center;font-size:11px;color:#9ca3af;">
      리포트 ID: {report.report_id} · ai-catcher 자동 발행
    </p>

  </div>
</body>
</html>"""
