"""run_new_papers.py — Weekly new-paper pipeline entrypoint.

Sets PIPELINE_MODE=new_paper and delegates to run_pipeline.main().
Run: uv run python scripts/run_new_papers.py
"""

import os
import sys
from pathlib import Path

# Must be set before get_settings() is called anywhere
os.environ.setdefault("PIPELINE_MODE", "new_paper")
os.environ.setdefault("ANALYSIS_MODE", "detail")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from run_pipeline import main  # noqa: E402

if __name__ == "__main__":
    main()
