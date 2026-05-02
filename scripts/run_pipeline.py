"""run_pipeline.py — Daily pipeline entrypoint for local runs and GitHub Actions.

Usage:
    uv run python scripts/run_pipeline.py
    DRY_RUN=true uv run python scripts/run_pipeline.py

Pipeline flow:
    Collection → Dedup → Scoring → Fetch → Analyze → Quality → Format → Distribute
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add the project root to sys.path when running the script directly.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from newsbot.collection.registry import build_default_registry
from newsbot.config import get_settings
from newsbot.dedup.store import DeduplicationStore
from newsbot.distribution.github_markdown import GitHubMarkdownPublisher
from newsbot.distribution.twitter_pub import TwitterPublisher
from newsbot.generation.analyzer import Analyzer
from newsbot.generation.fetcher import Fetcher
from newsbot.generation.synthesizer import Synthesizer
from newsbot.models import Report
from newsbot.monitoring.summary import save_report, write_summary
from newsbot.quality.checker import QualityChecker
from newsbot.scoring.feedback import FeedbackWeighter
from newsbot.scoring.scorer import Scorer


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


async def run_pipeline() -> Report:
    settings = get_settings()
    _setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    logger.info(
        "=== newsbot pipeline start | DRY_RUN=%s MOCK_CLAUDE=%s ANALYSIS_MODE=%s MAIN_MODEL=%s QUALITY_MODEL=%s ===",
        settings.dry_run,
        settings.mock_claude,
        settings.analysis_mode,
        settings.anthropic_main_model,
        settings.anthropic_quality_model,
    )
    errors: list[str] = []

    if not settings.mock_claude and not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY가 설정되지 않았습니다. mock 모드는 MOCK_CLAUDE=true 로 실행하세요.")

    # ── 1. Collection ─────────────────────────────────────────
    registry = build_default_registry()
    raw_items = await registry.collect_all()
    logger.info("collected %d raw items", len(raw_items))

    if not raw_items:
        raise RuntimeError("no items collected — aborting")

    # ── 2. Dedup ──────────────────────────────────────────────
    with DeduplicationStore(threshold=settings.dedup_similarity_threshold) as dedup:
        new_items = dedup.filter_new(raw_items)
        logger.info("after dedup: %d new items", len(new_items))

        if not new_items:
            raise RuntimeError("all items are duplicates — aborting")

        # ── 3. Scoring ────────────────────────────────────────
        if settings.mock_claude:
            from newsbot.mock_claude import (
                MockAnalyzer,
                MockQualityChecker,
                MockScorer,
                MockSynthesizer,
            )
            scorer = MockScorer()
            analyzer = MockAnalyzer()
            checker = MockQualityChecker()
            synthesizer = MockSynthesizer()
            logger.info("[MOCK] mock_claude=true — API 호출 없이 실행")
        else:
            scorer = Scorer(
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_main_model,
            )
            analyzer = Analyzer(
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_main_model,
                mode=settings.analysis_mode,
            )
            checker = QualityChecker(
                api_key=settings.anthropic_api_key,
                min_score=settings.quality_min_score,
                model=settings.anthropic_quality_model,
                mode=settings.analysis_mode,
            )
            synthesizer = Synthesizer(
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_main_model,
                mode=settings.analysis_mode,
            )

        scored = await scorer.score_all(new_items)

        # Feedback weighting (Phase 1: no-op)
        weighted = FeedbackWeighter().apply(scored)

        # Keep only the top N items.
        top_scored = weighted[: settings.items_per_report]
        logger.info("selected top %d items for analysis", len(top_scored))

        # ── 4. Fetch full articles ────────────────────────────
        fetcher = Fetcher(
            max_content_length=2000 if settings.analysis_mode == "light" else 4000
        )
        await fetcher.fetch_all(top_scored)

        # ── 5. Analyze ────────────────────────────────────────
        analyzed = await analyzer.analyze_all(top_scored)

        # ── 6. Quality Gate ───────────────────────────────────
        passing = await checker.filter_passing(analyzed, analyzer=analyzer)

        if not passing:
            raise RuntimeError("no items passed quality gate — aborting")

        # ── 7. Synthesize ─────────────────────────────────────
        report = await synthesizer.synthesize(passing, language=settings.default_language)
        logger.info("report %s created: %s", report.report_id, report.headline)

        # Mark published items as seen, but only for quality-passing items.
        dedup.mark_seen_batch([item.scored.raw for item in passing])

    # ── 8. Save local report ──────────────────────────────────
    from newsbot.formatting.twitter import TwitterFormatter
    tweets = TwitterFormatter().format(report)
    saved_path = save_report(report, tweets=tweets)
    logger.info("report saved → %s", saved_path)

    # ── 9. Distribution ───────────────────────────────────────
    published_channels: list[str] = []

    if settings.twitter_configured:
        publisher = TwitterPublisher(
            bearer_token=settings.twitter_bearer_token,
            api_key=settings.twitter_api_key,
            api_secret=settings.twitter_api_secret,
            access_token=settings.twitter_access_token,
            access_secret=settings.twitter_access_secret,
            dry_run=settings.dry_run,
        )
        try:
            publisher.publish(report)
            published_channels.append("twitter")
        except Exception as exc:
            err = f"twitter publish failed: {exc}"
            logger.error(err)
            errors.append(err)
    else:
        logger.info("twitter not configured, skipping")

    gh_publisher = GitHubMarkdownPublisher(
        repo_url=settings.github_archive_repo_url,
        branch=settings.github_archive_branch,
        token=settings.github_archive_token,
        dry_run=settings.dry_run,
    )
    try:
        gh_publisher.publish(report)
        published_channels.append("github_markdown")
    except Exception as exc:
        err = f"github archive failed: {exc}"
        logger.warning(err)
        errors.append(err)

    # ── 10. Summary ───────────────────────────────────────────
    write_summary(report, published_channels, errors)
    logger.info("=== newsbot pipeline done | published=%s ===", published_channels)

    return report


def main() -> None:
    try:
        asyncio.run(run_pipeline())
    except RuntimeError as exc:
        logging.getLogger(__name__).error("pipeline aborted: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
