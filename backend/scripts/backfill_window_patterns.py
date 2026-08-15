"""Backfill day-scope window pattern clustering for past days.

``run_pattern_analysis.py`` only ever clusters the *previous* completed day, so
``activity_window_patterns`` at ``scope='day'`` grows one day at a time from
whenever the nightly job was first switched on. Every earlier day that has
10-minute windows has no day-scope rows at all, which is why the Insights
"Day Analysis" date strip renders empty for everything but the most recent
day or two.

This script fills that history in by replaying exactly what the nightly job
would have done on each of those mornings: one clustering run per local day,
over that day alone, with ``run_date`` set to the following day. Keeping
``run_date`` per-day matters — the Dashboard's Pattern Snapshot asks for the
rows with ``MAX(run_date)``, so stamping every backfilled row with today's
date would fold a month of history into what the card calls "yesterday".

Run from the ``backend`` directory::

    .\\venv\\Scripts\\python.exe scripts\\backfill_window_patterns.py --dry-run
    .\\venv\\Scripts\\python.exe scripts\\backfill_window_patterns.py

``--dry-run`` reports which days would be clustered without writing.
``--force`` re-clusters days that already have rows; by default they are left
alone so re-running is cheap and does not churn existing results.
"""

import argparse
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.time import APP_TZ, local_now  # noqa: E402
from app.services.scoped_window_pattern_analysis import (  # noqa: E402
    ScopedWindowPatternAnalysisService,
    ScopeRun,
)

# The clustering itself needs at least this many windows (KMeans with k=3);
# ``run_scope`` enforces it too, but checking here keeps the plan honest about
# which days will actually produce rows.
MIN_WINDOWS = 3


def windowed_days(session) -> list[date]:
    """Local days that have 10-minute windows recorded, oldest first."""
    rows = session.execute(text("""
        SELECT substr(window_start, 1, 10) AS day, COUNT(*) AS n
        FROM activity_window_10m
        GROUP BY day
        HAVING n >= :minimum
        ORDER BY day
    """), {"minimum": MIN_WINDOWS}).mappings().all()
    return [date.fromisoformat(row["day"]) for row in rows]


def days_with_patterns(session) -> set[date]:
    """Local days that already have day-scope pattern rows."""
    rows = session.execute(text("""
        SELECT DISTINCT substr(window_start, 1, 10) AS day
        FROM activity_window_patterns
        WHERE scope = 'day'
    """)).mappings().all()
    return {date.fromisoformat(row["day"]) for row in rows}


def scope_run_for(day: date, model_stamp: str) -> ScopeRun:
    """The ScopeRun the nightly job would have built on the morning after ``day``."""
    range_from = datetime.combine(day, time.min, tzinfo=APP_TZ)
    range_to = range_from + timedelta(days=1)
    return ScopeRun(
        scope="day",
        run_date=(day + timedelta(days=1)).isoformat(),
        range_from=range_from,
        range_to=range_to,
        model_version=f"day_backfill_{model_stamp}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--force", action="store_true", help="re-cluster days that already have rows")
    parser.add_argument("--from", dest="from_date", default=None, help="earliest day to backfill (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", default=None, help="latest day to backfill (YYYY-MM-DD)")
    args = parser.parse_args()

    # Today is still being recorded, so it is not a completed day — the nightly
    # job would not have clustered it and the Day Analysis strip never offers it.
    today = local_now().date()

    with SessionLocal() as session:
        available = windowed_days(session)
        existing = days_with_patterns(session)

    if not available:
        print("no days in activity_window_10m have enough windows to cluster")
        return 0

    candidates = [day for day in available if day < today]
    if args.from_date:
        start = date.fromisoformat(args.from_date)
        candidates = [day for day in candidates if day >= start]
    if args.to_date:
        end = date.fromisoformat(args.to_date)
        candidates = [day for day in candidates if day <= end]

    skipped = [day for day in candidates if day in existing and not args.force]
    targets = [day for day in candidates if day not in existing or args.force]

    print(f"days with windows      {len(available)} ({available[0]} .. {available[-1]})")
    print(f"already clustered      {len(existing)}")
    print(f"skipping (has rows)    {len(skipped)}")
    print(f"to backfill            {len(targets)}")

    if not targets:
        print("\nnothing to do")
        return 0

    if args.dry_run:
        print("\nDRY RUN — nothing written. Would cluster:")
        for day in targets:
            print(f"  {day}")
        return 0

    model_stamp = local_now().strftime("%Y%m%dT%H%M%S")
    service = ScopedWindowPatternAnalysisService()

    total_rows = 0
    clustered = 0
    empty: list[date] = []
    for day in targets:
        rows = service.run_scope(scope_run_for(day, model_stamp))
        if rows:
            clustered += 1
            total_rows += rows
            print(f"  {day}  {rows} windows")
        else:
            empty.append(day)
            print(f"  {day}  skipped (too few windows in range)")

    print(f"\nclustered {clustered} day(s), {total_rows} pattern rows written")
    if empty:
        print(f"produced no rows for {len(empty)} day(s): {', '.join(str(d) for d in empty)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
