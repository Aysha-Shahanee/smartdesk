"""Recompute focus scores for activity segments already in the database.

Rescores in place. It does not rebuild segments, so boundaries, ids and the
labels pointing at them are all left alone — unlike
``ActivitySegmentBuilder.backfill``, which purges and reconstructs rows. Use
this when only the scoring formula has changed.

Run from the ``backend`` directory::

    .\\venv\\Scripts\\python.exe scripts\\backfill_focus_scores.py --dry-run
    .\\venv\\Scripts\\python.exe scripts\\backfill_focus_scores.py

``--dry-run`` computes and reports the resulting distribution without writing,
so the same code path that will do the update can be inspected first.
"""

import argparse
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal  # noqa: E402
from app.core.time import APP_TZ, parse_iso  # noqa: E402
from app.models.db import (  # noqa: E402
    ActivitySegmentRecord,
    BrowserSessionRecord,
    IDESessionRecord,
    OSSessionRecord,
)
from app.services.activity_segment_builder import MIN_SCORABLE_SEC  # noqa: E402
from app.services.focus_scorer import FocusScorer, neighbourhood_switch_rates  # noqa: E402

COMMIT_EVERY = 500


def as_aware(value: datetime) -> datetime:
    """Attach the app timezone to a naive timestamp read back from SQLite.

    ``activity_segments.start_time_utc`` is written from an APP_TZ-aware
    datetime, but SQLite drops the offset on the way in and hands back a naive
    value. The session tables keep theirs as ISO strings *with* the offset, so
    without this the two sides are not comparable at all.
    """
    return value if value.tzinfo else value.replace(tzinfo=APP_TZ)


def hour_key(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def bucket_sessions(sessions: list, fallback_end: datetime) -> dict:
    """Index sessions by the hours they touch, so overlap lookup stays linear."""
    buckets = defaultdict(list)
    for session in sessions:
        try:
            start = parse_iso(session.session_start)
        except (ValueError, TypeError, AttributeError):
            continue
        end = start
        if session.session_end:
            try:
                end = parse_iso(session.session_end)
            except (ValueError, TypeError, AttributeError):
                end = fallback_end
        if end < start:
            end = start

        cursor = hour_key(start)
        last = hour_key(end)
        while cursor <= last:
            buckets[cursor].append((start, end, session))
            cursor += timedelta(hours=1)
    return buckets


def overlapping(buckets: dict, start: datetime, end: datetime) -> list:
    """Sessions whose span intersects ``[start, end)``."""
    found = {}
    cursor = hour_key(start)
    last = hour_key(end)
    while cursor <= last:
        for session_start, session_end, session in buckets.get(cursor, ()):
            if session_start < end and session_end > start:
                found[id(session)] = session
        cursor += timedelta(hours=1)
    return list(found.values())


def report(scores: list[float], by_category: dict) -> None:
    if not scores:
        print("no segments scored")
        return

    print(f"\nscored          {len(scores)}")
    print(f"min / max       {min(scores):.3f} / {max(scores):.3f}")
    print(f"mean / median   {statistics.mean(scores):.3f} / {statistics.median(scores):.3f}")
    ordered = sorted(scores)
    for label, index in (("p25", 0.25), ("p75", 0.75), ("p95", 0.95)):
        print(f"{label}             {ordered[min(int(len(ordered) * index), len(ordered) - 1)]:.3f}")

    print("\ndecile histogram")
    buckets = defaultdict(int)
    for value in scores:
        buckets[min(int(value * 10), 9)] += 1
    for decile in range(10):
        count = buckets[decile]
        bar = "#" * int(60 * count / max(buckets.values()))
        print(f"  {decile / 10:.1f}-{(decile + 1) / 10:.1f}  {count:5d}  {bar}")

    print("\nmean by category")
    for category, values in sorted(by_category.items(), key=lambda item: -len(item[1])):
        print(f"  {str(category):15s} n={len(values):5d}  mean={statistics.mean(values):.3f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--user-id", default=None, help="limit to one user")
    args = parser.parse_args()

    scorer = FocusScorer()
    db = SessionLocal()
    try:
        query = db.query(ActivitySegmentRecord)
        if args.user_id:
            query = query.filter(ActivitySegmentRecord.user_id == args.user_id)
        segments = query.order_by(ActivitySegmentRecord.start_time_utc).all()
        if not segments:
            print("no segments found")
            return 0

        latest_end = max(as_aware(segment.end_time_utc) for segment in segments)
        print(f"loaded {len(segments)} segments; indexing source sessions...")
        buckets = {
            "os": bucket_sessions(db.query(OSSessionRecord).all(), latest_end),
            "ide": bucket_sessions(db.query(IDESessionRecord).all(), latest_end),
            "browser": bucket_sessions(db.query(BrowserSessionRecord).all(), latest_end),
        }

        # Every segment is in hand here, so the timeline is complete and no
        # lookback is needed — unlike the builder, which only holds one tick.
        # Computed over all segments including the sub-MIN_SCORABLE_SEC ones:
        # they are not scored themselves but they are still app switches, and
        # dropping them would understate how busy a stretch was.
        switch_rates = neighbourhood_switch_rates(
            [
                (as_aware(s.start_time_utc), as_aware(s.end_time_utc), s.app_name)
                for s in segments
            ]
        )
        print(f"computed neighbourhood switch rates over {len(segments)} segments")

        scores: list[float] = []
        by_category: dict = defaultdict(list)
        skipped = 0
        written = 0

        for index, segment in enumerate(segments):
            duration = float(segment.duration_sec or 0)
            if duration < MIN_SCORABLE_SEC:
                skipped += 1
                continue

            start = as_aware(segment.start_time_utc)
            end = as_aware(segment.end_time_utc)
            payload = {
                "start_time": start,
                "end_time": end,
                "duration": duration,
                "state": segment.state,
                "category": segment.category,
                "primary_source": segment.primary_source,
                FocusScorer.NEIGHBOURHOOD_KEY: switch_rates[index],
                "sources": {
                    source: overlapping(buckets[source], start, end)
                    for source in ("os", "ide", "browser")
                },
            }

            score, concurrent_json, signals_json = scorer.score_segment(payload)
            scores.append(score)
            by_category[segment.category].append(score)

            if not args.dry_run:
                segment.focus_score = score
                segment.concurrent_json = concurrent_json
                segment.signals_json = signals_json
                written += 1
                if written % COMMIT_EVERY == 0:
                    db.commit()
                    print(f"  committed {written}...")

        if args.dry_run:
            db.rollback()
            print(f"\nDRY RUN — nothing written. skipped (<{MIN_SCORABLE_SEC}s): {skipped}")
        else:
            db.commit()
            print(f"\nwrote {written} scores. skipped (<{MIN_SCORABLE_SEC}s): {skipped}")

        report(scores, by_category)
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
