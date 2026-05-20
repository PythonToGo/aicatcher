"""ActionsSummary + ReportSaver — Record run results and save report files.

If GITHUB_STEP_SUMMARY is set, write markdown to that file.
Otherwise print to stdout for local runs.

save_report():
    reports/YYYYMMDD-HHMM-{lang}.md        — full analysis report
    reports/YYYYMMDD-HHMM-twitter-{lang}.txt — tweet thread text
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from newsbot.models import Report

_REPORTS_DIR = Path("reports")

logger = logging.getLogger(__name__)


def write_summary(report: Report, published_channels: list[str], errors: list[str]) -> None:
    """Write pipeline results to the Actions summary."""
    md = _build_markdown(report, published_channels, errors)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(md)
            logger.info("[summary] written to GITHUB_STEP_SUMMARY")
        except OSError as exc:
            logger.warning("[summary] failed to write summary file: %s", exc)
    else:
        print(md, file=sys.stdout)


def _build_markdown(
    report: Report,
    published_channels: list[str],
    errors: list[str],
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    status = "✅ 성공" if not errors else f"⚠️ 부분 실패 ({len(errors)}개 오류)"
    channels = ", ".join(published_channels) if published_channels else "없음"

    lines = [
        f"## 📰 newsbot 실행 결과 — {now}",
        f"",
        f"| 항목 | 값 |",
        f"|------|-----|",
        f"| 상태 | {status} |",
        f"| 리포트 ID | `{report.report_id}` |",
        f"| 발행 채널 | {channels} |",
        f"| 아이템 수 | {len(report.items)} |",
        f"| 언어 | {report.language} |",
        f"",
        f"### 헤드라인",
        f"",
        f"> {report.headline}",
        f"",
    ]

    if report.items:
        lines += [
            "### 아이템 목록",
            "",
        ]
        for i, item in enumerate(report.items, 1):
            lines.append(f"{i}. **[{item.title}]({item.url})** (점수: {item.score})")
        lines.append("")

    if errors:
        lines += [
            "### ❌ 오류 목록",
            "",
        ]
        for err in errors:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines)


# ── Save local report files ──────────────────────────────────────────────────

def save_report(report: Report, tweets: list[str] | None = None) -> Path:
    """Save the report as markdown under the reports/ directory.

    Returns: path to the saved .md file
    """
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lang = report.language

    # ── Full report markdown ──
    md_path = _REPORTS_DIR / f"{report.report_id}-{lang}.md"
    md_content = build_report_md(report)
    md_path.write_text(md_content, encoding="utf-8")
    logger.info("[save] report → %s", md_path)

    # ── Tweet thread text ──
    if tweets:
        txt_path = _REPORTS_DIR / f"{report.report_id}-twitter-{lang}.txt"
        txt_path.write_text(_build_tweet_txt(tweets), encoding="utf-8")
        logger.info("[save] tweets → %s", txt_path)

    return md_path


def build_report_md(report: Report) -> str:
    """Route to the appropriate markdown renderer based on pipeline_mode."""
    if report.pipeline_mode == "classic_paper":
        from newsbot.formatting.classic_paper import format_classic_paper_md
        return format_classic_paper_md(report)
    if report.pipeline_mode == "new_paper":
        return _build_new_paper_md(report)
    return _build_news_md(report)


def _build_news_md(report: Report) -> str:
    lines = [
        f"# {report.headline}",
        f"",
        f"> **리포트 ID**: `{report.report_id}`  ",
        f"> **생성**: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"> **아이템**: {len(report.items)}개  ",
        f"",
        f"## 트렌드 분석",
        f"",
        report.trend_analysis,
        f"",
        f"---",
        f"",
        f"## 아이템 분석",
        f"",
    ]
    for i, item in enumerate(report.items, 1):
        lines += [
            f"### {i}. {item.title}",
            f"",
            f"- **출처**: {item.scored.raw.source}",
            f"- **점수**: {item.score}",
            f"- **URL**: {item.url}",
            f"",
            f"**요약**", f"", item.summary_ko, f"",
            f"**맥락**", f"", item.context, f"",
            f"**실무 시사점**", f"", item.implications, f"",
            f"**한계 및 의문**", f"", item.limitations, f"",
        ]
        if item.related_urls:
            lines += ["**관련 링크**", ""]
            lines += [f"- {u}" for u in item.related_urls]
            lines.append("")
        lines += ["---", ""]
    return "\n".join(lines)


def _build_new_paper_md(report: Report) -> str:
    lines = [
        f"# 📄 {report.headline}",
        f"",
        f"> **리포트 ID**: `{report.report_id}`  ",
        f"> **생성**: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"> **논문 수**: {len(report.items)}편  ",
        f"",
        f"## 이번 주 연구 동향",
        f"",
        report.trend_analysis,
        f"",
        f"---",
        f"",
        f"## 논문 분석",
        f"",
    ]
    for i, item in enumerate(report.items, 1):
        methodology = item.extra.get("methodology", "")
        contributions = item.extra.get("contributions", "")
        benchmarks = item.extra.get("benchmark_results", "")
        lines += [
            f"### {i}. {item.title}",
            f"",
            f"- **출처**: {item.scored.raw.source}",
            f"- **점수**: {item.score}",
            f"- **URL**: {item.url}",
            f"",
            f"**요약**", f"", item.summary_ko, f"",
        ]
        if methodology:
            lines += [f"**방법론**", f"", methodology, f""]
        if contributions:
            lines += [f"**주요 기여**", f"", contributions, f""]
        if benchmarks:
            lines += [f"**실험 결과**", f"", benchmarks, f""]
        lines += [
            f"**맥락**", f"", item.context, f"",
            f"**실무 시사점**", f"", item.implications, f"",
            f"**한계**", f"", item.limitations, f"",
        ]
        if item.related_urls:
            lines += ["**관련 링크**", ""]
            lines += [f"- {u}" for u in item.related_urls]
            lines.append("")
        lines += ["---", ""]
    return "\n".join(lines)


def _build_tweet_txt(tweets: list[str]) -> str:
    parts = []
    for i, tweet in enumerate(tweets, 1):
        parts.append(f"=== Tweet {i}/{len(tweets)} ===")
        parts.append(tweet)
        parts.append("")
    return "\n".join(parts)
