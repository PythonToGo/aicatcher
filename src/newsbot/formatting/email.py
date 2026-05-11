"""EmailFormatter — Convert a Report into an HTML email body."""

from __future__ import annotations

from newsbot.models import Report


def format_email_html(report: Report) -> str:
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

    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#111827;">
  <div style="max-width:680px;margin:0 auto;padding:24px 16px;">

    <div style="background:#1d4ed8;border-radius:8px;padding:24px;margin-bottom:32px;">
      <p style="color:#93c5fd;font-size:12px;margin:0 0 8px;">AI/ML 뉴스레터 · {report.generated_at.strftime('%Y년 %m월 %d일')}</p>
      <h1 style="color:#fff;font-size:22px;margin:0;line-height:1.4;">{report.headline}</h1>
    </div>

    <div style="background:#fff;border-radius:8px;padding:24px;margin-bottom:32px;">
      <h2 style="font-size:16px;margin:0 0 12px;color:#374151;">트렌드 분석</h2>
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
