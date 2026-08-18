#!/usr/bin/env python3
"""Nightly recommendation pass.

Third stage of the scheduled task, after the window rebuild and the clustering
it depends on. Recomputes the personal baselines, then runs the period rule
families:

- daily   every night, over the previous completed local day
- weekly  on Mondays, over the previous seven completed days
- monthly on the 1st, over the previous 30 completed days

The live family is not run here — it belongs to the 60-second job inside the
backend process, where "now" means something.
"""

import logging
import logging.handlers
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.time import local_now
from app.services.recommendations.engine import engine
from app.services.recommendations.ranker import ranker
from app.services.recommendations.types import Scope

BACKEND_ROOT = Path(__file__).resolve().parent


def setup_logging(log_dir: Path = BACKEND_ROOT / "logs") -> None:
    log_dir.mkdir(exist_ok=True)
    handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / f"recommendations_{datetime.now():%Y-%m-%d}.log",
        when="midnight", interval=1, backupCount=30,
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for existing in list(root.handlers):
        existing.close()
        root.removeHandler(existing)
    root.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s - %(message)s"))
    root.addHandler(console)


def scopes_for(run_at: datetime) -> tuple[Scope, ...]:
    """Which period families are due. Daily always; the others on their day."""
    scopes: list[Scope] = [Scope.DAILY]
    if run_at.weekday() == 0:
        scopes.append(Scope.WEEKLY)
    if run_at.day == 1:
        scopes.append(Scope.MONTHLY)
    return tuple(scopes)


def main() -> None:
    setup_logging()
    logger = logging.getLogger("smartdesk.run_recommendations")
    logger.info("=" * 60)
    logger.info("Starting nightly recommendation pass")

    run_at = local_now()
    user_id = settings.DEFAULT_USER_ID
    # Period rules describe completed periods. Running them against a day still
    # in progress compares a partial total against a full-day baseline.
    as_of = (run_at - timedelta(days=1)).replace(tzinfo=None)

    db = SessionLocal()
    try:
        baselines = engine.baselines(db, user_id, as_of, force=True)
        engine._baseline_builder.persist(db, user_id, baselines)
        logger.info(
            "Baselines: %d metrics over %d days of history",
            len(baselines.global_stats), baselines.days_of_history,
        )

        scopes = scopes_for(run_at)
        logger.info("Running scopes: %s", ", ".join(s.value for s in scopes))
        # supersede: this pass runs after the window roll-up and the clustering
        # it depends on, so it is the only one whose inputs are complete. Cards
        # the interactive path wrote earlier from a lagging roll-up are retired
        # rather than deduplicated against, which is what kept a stale total on
        # the panel next to a fresh one describing the same day.
        written = engine.generate(db, user_id, as_of, scopes=scopes, supersede=True)
        logger.info("Wrote %d recommendation(s)", written)

        # Cheap and a no-op until enough feedback exists, so there is no reason
        # to schedule it separately.
        summary = ranker.train(db)
        logger.info("Ranker: %s", summary)
    except Exception:
        logger.exception("Nightly recommendation pass failed")
        db.rollback()
        raise
    finally:
        db.close()

    logger.info("Nightly recommendation pass completed")


if __name__ == "__main__":
    main()
