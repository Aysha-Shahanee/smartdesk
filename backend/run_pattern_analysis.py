#!/usr/bin/env python3
"""
Daily scoped pattern analysis runner.

Runs:
- day scope every day over the previous completed local day
- week scope only on Mondays over the previous 7 completed local days
- month scope only on the 1st day of each month over the previous 30 completed local days
"""

import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.core.time import local_now
from app.services.scoped_window_pattern_analysis import ScopedWindowPatternAnalysisService, compute_scope_runs

BACKEND_ROOT = Path(__file__).resolve().parent

def setup_logging(log_dir: str | Path = BACKEND_ROOT / "logs") -> None:
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    log_file = log_path / f"pattern_analysis_{datetime.now():%Y-%m-%d}.log"
    handler = logging.handlers.TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=30,
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for existing in list(root.handlers):
        existing.close()
        root.removeHandler(existing)
    root.addHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s - %(message)s"))
    root.addHandler(console)


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("Starting scoped pattern analysis run")
    logger.info("=" * 60)

    run_at = local_now()
    runs = compute_scope_runs(run_at)
    service = ScopedWindowPatternAnalysisService()

    try:
        total_rows = 0
        for scope_run in runs:
            logger.info(
                "Running %s scope for range %s -> %s",
                scope_run.scope,
                scope_run.range_from.isoformat(),
                scope_run.range_to.isoformat(),
            )
            total_rows += service.run_scope(scope_run)
        logger.info("Scoped pattern analysis completed successfully. Rows stored: %d", total_rows)
    except Exception as exc:
        logger.exception("Scoped pattern analysis failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
