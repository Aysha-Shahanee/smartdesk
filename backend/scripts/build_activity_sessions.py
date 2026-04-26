#!/usr/bin/env python3
"""Build dashboard-ready activity_sessions from model1_features_10min."""

import argparse
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.ml.activity_sessions import build_activity_sessions


def main():
    parser = argparse.ArgumentParser(description="Build activity_sessions table")
    parser.add_argument("db_path", nargs="?", default=str(backend_dir / "smartdesk.db"))
    parser.add_argument("--user-id", default="default_user")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--fallback-labeling", action="store_true", help="Enable fallback labels when manual/predicted labels are missing")
    parser.add_argument("--predicted-conf-threshold", type=float, default=0.5)
    args = parser.parse_args()

    print("=" * 70)
    print("SmartDesk Activity Sessions Builder")
    print("=" * 70)
    print(f"Database: {args.db_path}")
    print(f"User: {args.user_id}")
    print(f"Date range: start={args.start_date}, end={args.end_date}")

    result = build_activity_sessions(
        db_path=args.db_path,
        user_id=args.user_id,
        start_date=args.start_date,
        end_date=args.end_date,
        fallback_enabled=args.fallback_labeling,
        predicted_conf_threshold=args.predicted_conf_threshold,
    )

    print("-" * 70)
    for k, v in result.items():
        print(f"{k}: {v}")
    print("=" * 70)
    print("[ok] activity_sessions build complete")


if __name__ == "__main__":
    main()
