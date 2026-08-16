"""Rebuild activity segments across the recorded history.

Use this when the *builder* changed — boundaries, state, gap handling — not just
the scoring formula. It purges and reconstructs rows from os/ide/browser
sessions, so segment ids change and ``activity_segment_labels`` are re-anchored
by timestamp (``ActivitySegmentBuilder.backfill`` handles the relinking).

For a scoring-only change use scripts/backfill_focus_scores.py instead: it
rescores in place and leaves boundaries and ids alone.

Stop the backend first. The builder writes to the same SQLite file every five
minutes, and a tick landing inside a range being rebuilt will both fight for the
write lock and re-insert rows the purge just removed.

Run from the ``backend`` directory::

    .\\venv\\Scripts\\python.exe scripts\\rebuild_segments.py --dry-run
    .\\venv\\Scripts\\python.exe scripts\\rebuild_segments.py
"""

import argparse
import shutil
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.db import ActivitySegmentRecord  # noqa: E402
from app.services.activity_segment_builder import ActivitySegmentBuilder  # noqa: E402

DB_PATH = Path(__file__).resolve().parents[1] / "smartdesk.db"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report the range and counts, then stop")
    parser.add_argument("--chunk-sec", type=int, default=3600)
    parser.add_argument("--skip-backup", action="store_true",
                        help="do not copy the database first (not recommended)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        first = db.query(ActivitySegmentRecord.start_time_utc).order_by(
            ActivitySegmentRecord.start_time_utc.asc()).limit(1).scalar()
        last = db.query(ActivitySegmentRecord.end_time_utc).order_by(
            ActivitySegmentRecord.end_time_utc.desc()).limit(1).scalar()
        before = db.query(ActivitySegmentRecord).count()
        labels = db.execute(
            __import__("sqlalchemy").text("select count(*) from activity_segment_labels")
        ).scalar()
    finally:
        db.close()

    if first is None:
        print("no segments to rebuild")
        return 0

    # Widen by a chunk at each end so boundary segments are not clipped.
    start = first - timedelta(seconds=args.chunk_sec)
    end = last + timedelta(seconds=args.chunk_sec)
    print(f"range:    {start.isoformat()} .. {end.isoformat()}")
    print(f"segments: {before}")
    print(f"labels:   {labels} (re-anchored by timestamp, not by id)")

    if args.dry_run:
        print("\nDRY RUN — nothing rebuilt.")
        return 0

    if not args.skip_backup and DB_PATH.exists():
        backup = DB_PATH.with_suffix(".db.backup-rebuild")
        shutil.copy2(DB_PATH, backup)
        print(f"\nbacked up database -> {backup.name}")

    builder = ActivitySegmentBuilder(
        user_id=settings.DEFAULT_USER_ID,
        device_id=settings.DEVICE_ID,
    )
    summary = builder.backfill(
        from_iso=start.isoformat(),
        to_iso=end.isoformat(),
        chunk_sec=args.chunk_sec,
        purge=True,
    )
    print("\nsummary:")
    for key, value in summary.items():
        print(f"  {key:18s} {value}")

    db = SessionLocal()
    try:
        after = db.query(ActivitySegmentRecord).count()
        scored = db.query(ActivitySegmentRecord).filter(
            ActivitySegmentRecord.focus_score.isnot(None)).count()
    finally:
        db.close()
    print(f"\nsegments: {before} -> {after}   scored: {scored}")
    if summary.get("chunks_failed"):
        print(f"WARNING: {summary['chunks_failed']} chunk(s) failed; see the log above.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
