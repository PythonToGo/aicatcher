"""FeedbackWeighter — adjusts item scores based on past X engagement.

Phase 1: stub implementation. Always returns weight 1.0.
Phase 2: reads feedback history from DB and computes real weights.

Weight semantics:
    adjusted_score = base_score * weight
    weight > 1.0  → similar topics performed well before  → boost
    weight < 1.0  → similar topics performed poorly       → penalty
"""

from __future__ import annotations

import logging
from pathlib import Path

from newsbot.models import ScoredItem

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/newsbot.db")
_MIN_WEIGHT = 0.5
_MAX_WEIGHT = 2.0


class FeedbackWeighter:
    """Adjusts ScoredItem scores based on feedback history."""

    def __init__(self, db_path: Path = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path

    def apply(self, items: list[ScoredItem]) -> list[ScoredItem]:
        """Apply feedback weights to all items and return the adjusted list.

        Phase 1 stub: weight 1.0 — scores unchanged.
        """
        logger.debug("[feedback] Phase 1 stub — weights all 1.0")
        return items

    def get_weight(self, item: ScoredItem) -> float:
        """Return the feedback weight for a single item.

        Phase 1 stub: always 1.0.
        Phase 2 implementation:
            1. Embed item.raw.title
            2. Query DB feedback table for similar past items
            3. Compute weight from likes/reposts ratio
            4. Clamp to [_MIN_WEIGHT, _MAX_WEIGHT]
        """
        return 1.0
