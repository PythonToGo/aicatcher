"""ClassicPaperFormatter — Markdown and HTML renderers for the classic_paper pipeline.

Used by:
  - monitoring/summary.py  (build_report_md routing)
  - formatting/email.py    (format_email_html routing)
"""

from __future__ import annotations

from newsbot.models import AnalyzedItem, Report


def _extra(item: AnalyzedItem, key: str) -> str:
    return item.extra.get(key, "").strip()


def _paper_metadata(item: AnalyzedItem) -> str:
    meta = item.scored.raw.metadata
    year = meta.get("year", "")
    venue = meta.get("venue", "")
    citations = meta.get("citation_count", "")
    authors = meta.get("authors", [])
    author_str = ", ".join(authors[:3]) if authors else ""
    parts = [p for p in [author_str, venue, f"인용 {citations:,}회" if citations else ""] if p]
    return f"{year}년  ·  " + "  ·  ".join(parts) if parts else str(year)


def format_classic_paper_md(report: Report) -> str:
    """Render a classic_paper Report as Markdown for GitHub archive."""
    lines = [
        f"# 📚 클래식 논문 리뷰",
        f"",
        f"> **리포트 ID**: `{report.report_id}`  ",
        f"> **생성**: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"",
        f"---",
        f"",
    ]

    # trend_analysis acts as "왜 지금 이 논문인가" in classic_paper mode
    if report.trend_analysis:
        lines += [
            f"## 지금 이 논문을 읽어야 하는 이유",
            f"",
            report.trend_analysis,
            f"",
            f"---",
            f"",
        ]

    for item in report.items:
        meta_line = _paper_metadata(item)
        historical = _extra(item, "historical_context")
        why = _extra(item, "why_groundbreaking")
        learning = _extra(item, "learning_points")

        lines += [
            f"## [{item.title}]({item.url})",
            f"",
            f"> {meta_line}" if meta_line else "",
            f"",
            f"### 한 줄 요약",
            f"",
            item.summary_ko,
            f"",
        ]

        if historical:
            lines += [f"### 역사적 배경", f"", historical, f""]

        if why:
            lines += [f"### 왜 혁신적이었는가", f"", why, f""]

        if item.implications:
            lines += [f"### 이 논문이 만들어낸 변화", f"", item.implications, f""]

        if learning:
            lines += [f"### 오늘날 배울 수 있는 것", f"", learning, f""]

        if item.limitations:
            lines += [f"### 한계 및 이후 발전", f"", item.limitations, f""]

        lines += [f"", f"---", f""]

    return "\n".join(l for l in lines)


def format_classic_paper_html(report: Report) -> str:
    """Render a classic_paper Report as an HTML email body."""
    items_html = ""
    for item in report.items:
        meta_line = _paper_metadata(item)
        historical = _extra(item, "historical_context")
        why = _extra(item, "why_groundbreaking")
        learning = _extra(item, "learning_points")

        def section(label: str, text: str) -> str:
            if not text:
                return ""
            return (
                f'<p style="margin:0 0 6px;"><strong>{label}</strong></p>'
                f'<p style="margin:0 0 16px;line-height:1.7;">{text}</p>'
            )

        items_html += f"""
        <div style="margin-bottom:40px;padding-bottom:40px;border-bottom:1px solid #e5e7eb;">
          <h2 style="font-size:20px;margin:0 0 6px;">
            <a href="{item.url}" style="color:#1d4ed8;text-decoration:none;">{item.title}</a>
          </h2>
          <p style="font-size:12px;color:#6b7280;margin:0 0 20px;">{meta_line}</p>
          {section("한 줄 요약", item.summary_ko)}
          {section("역사적 배경", historical)}
          {section("왜 혁신적이었는가", why)}
          {section("이 논문이 만들어낸 변화", item.implications)}
          {section("오늘날 배울 수 있는 것", learning)}
          {section("한계 및 이후 발전", item.limitations)}
        </div>
        """

    trend_html = ""
    if report.trend_analysis:
        trend_html = f"""
        <div style="background:#fff;border-radius:8px;padding:24px;margin-bottom:32px;">
          <h2 style="font-size:16px;margin:0 0 12px;color:#374151;">지금 이 논문을 읽어야 하는 이유</h2>
          <p style="line-height:1.7;margin:0;">{report.trend_analysis}</p>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#111827;">
  <div style="max-width:680px;margin:0 auto;padding:24px 16px;">

    <div style="background:#065f46;border-radius:8px;padding:24px;margin-bottom:32px;">
      <p style="color:#6ee7b7;font-size:12px;margin:0 0 8px;">
        📚 클래식 논문 리뷰 · {report.generated_at.strftime('%Y년 %m월 %d일')}
      </p>
      <h1 style="color:#fff;font-size:22px;margin:0;line-height:1.4;">{report.headline}</h1>
    </div>

    {trend_html}

    <div style="background:#fff;border-radius:8px;padding:24px;margin-bottom:32px;">
      {items_html}
    </div>

    <p style="text-align:center;font-size:11px;color:#9ca3af;">
      리포트 ID: {report.report_id} · ai-catcher 자동 발행
    </p>

  </div>
</body>
</html>"""
