"""run_classic_paper.py — Weekly classic-paper pipeline entrypoint.

Sets PIPELINE_MODE=classic_paper and delegates to run_pipeline.main().
Run: uv run python scripts/run_classic_paper.py
"""

import os
import sys
from pathlib import Path

# Must be set before get_settings() is called anywhere
os.environ.setdefault("PIPELINE_MODE", "classic_paper")
os.environ.setdefault("ANALYSIS_MODE", "detail")
os.environ.setdefault("ITEMS_PER_REPORT", "1")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from run_pipeline import main  # noqa: E402

if __name__ == "__main__":
    main()
