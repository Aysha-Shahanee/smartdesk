"""Live recommendation ticker.

Runs every 60 seconds in a background daemon thread, matching SessionTimeoutJob
and WorkPeriodScheduler. Each tick builds one feature snapshot and evaluates the
live rule family against it; the daily family is left to the nightly script.

The tick is deliberately cheap — two queries and a few dozen pure predicates —
so it can sit alongside the OS collector's one-second polling without competing
with it.
"""

import logging
import threading
import time

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.time import local_now
from app.services.recommendations.engine import engine
from app.services.recommendations.types import Scope

logger = logging.getLogger("smartdesk.recommendation_job")

JOB_INTERVAL_SEC: int = 60

#: Log a warning if a tick takes longer than this. The design budget is 50 ms;
#: this is the point at which something has gone wrong rather than merely run
#: slowly, and it wants to be visible in the log rather than discovered as a
#: stutter in the UI.
TICK_BUDGET_MS: float = 250.0


class RecommendationJob:
    """Background evaluator for the live rule family."""

    def __init__(self, user_id: str | None = None) -> None:
        self._timer: threading.Timer | None = None
        self._running = False
        self._user_id = user_id or settings.DEFAULT_USER_ID

    def start(self) -> None:
        if self._running:
            logger.warning("RecommendationJob already running — ignoring start().")
            return
        self._running = True
        logger.info("RecommendationJob started (interval=%ds).", JOB_INTERVAL_SEC)
        self._schedule()

    def stop(self) -> None:
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        logger.info("RecommendationJob stopped.")

    def _schedule(self) -> None:
        if not self._running:
            return
        self._timer = threading.Timer(JOB_INTERVAL_SEC, self._tick)
        self._timer.daemon = True
        self._timer.name = "smartdesk-recommendation-job"
        self._timer.start()

    def _tick(self) -> None:
        try:
            self.run_once()
        except Exception:
            logger.exception("RecommendationJob encountered an error during tick.")
        finally:
            self._schedule()

    def run_once(self) -> int:
        """Evaluate the live family once. Returns the number of cards written."""
        started = time.perf_counter()
        db = SessionLocal()
        try:
            written = engine.generate(
                db, self._user_id, local_now(), scopes=(Scope.LIVE,)
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms > TICK_BUDGET_MS:
            logger.warning(
                "Recommendation tick took %.0f ms (budget %.0f ms).",
                elapsed_ms, TICK_BUDGET_MS,
            )
        elif written:
            logger.info(
                "Recommendation tick wrote %d card(s) in %.0f ms.", written, elapsed_ms
            )
        return written
