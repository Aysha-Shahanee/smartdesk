#!/usr/bin/env python
"""
Nightly rebuild script for activity_window_10m table.
This script recreates the window table from scratch using the existing
make_window_table.py logic to recover from any trigger failures or schema changes.
"""

import os
import subprocess
import sys
from pathlib import Path
import sqlite3
import logging

BACKEND_ROOT = Path(__file__).resolve().parent
DB_PATH = BACKEND_ROOT / "smartdesk.db"
LOG_PATH = BACKEND_ROOT / "logs" / "refresh_windows_nightly.log"

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

#: Columns run_pattern_analysis.py reads that make_window_table.py does not
#: create. They used to be added only by a loose SQL script nothing ran, so a
#: fresh install failed with "no such column: sum_focus_duration". Added here
#: instead, idempotently, so the nightly job is self-sufficient.
ADDITIVE_COLUMNS = [
    ("sum_active_seconds", "REAL"), ("sum_idle_seconds", "REAL"),
    ("sum_app_switches", "INTEGER"), ("sum_category_switches", "INTEGER"),
    ("sum_unique_apps", "INTEGER"), ("sum_work_time", "REAL"),
    ("sum_learn_time", "REAL"), ("sum_communication_time", "REAL"),
    ("sum_entertainment_time", "REAL"), ("sum_documentation_time", "REAL"),
    ("sum_system_time", "REAL"), ("sum_other_time", "REAL"),
    ("sum_focus_weighted", "REAL"), ("sum_focus_duration", "REAL"),
    ("seg_count", "INTEGER"),
]


def ensure_additive_columns(cur) -> int:
    """Add any missing additive columns. SQLite has no ADD COLUMN IF NOT EXISTS."""
    existing = {row[1] for row in cur.execute("PRAGMA table_info(activity_window_10m)")}
    added = 0
    for name, sql_type in ADDITIVE_COLUMNS:
        if name not in existing:
            cur.execute(f"ALTER TABLE activity_window_10m ADD COLUMN {name} {sql_type}")
            added += 1
    if added:
        logger.info("Added %d missing additive column(s)", added)
    return added


def populate_additive_columns():
    """Populate the additive columns based on the freshly built window table."""
    logger.info("Populating additive columns after window table rebuild...")

    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        ensure_additive_columns(cur)

        # Populate additive columns based on current window table values
        cur.execute("""
            UPDATE activity_window_10m SET
                sum_active_seconds   = active_seconds,
                sum_idle_seconds     = idle_seconds,
                sum_app_switches     = app_switches,
                sum_category_switches = category_switches,
                sum_unique_apps      = unique_apps,
                sum_work_time        = work_ratio * 600.0,
                sum_learn_time       = learn_ratio * 600.0,
                sum_communication_time = communication_ratio * 600.0,
                sum_entertainment_time = entertainment_ratio * 600.0,
                sum_documentation_time = documentation_ratio * 600.0,
                sum_system_time      = system_ratio * 600.0,
                sum_other_time       = other_ratio * 600.0,
                sum_focus_weighted   = avg_focus_score * 600.0,
                sum_focus_duration   = 600.0,
                seg_count            = 1
        """)

        con.commit()
        rows_updated = cur.rowcount
        con.close()

        logger.info(f"Populated additive columns for {rows_updated} window rows")

    except Exception as e:
        logger.error(f"Failed to populate additive columns: {e}")
        raise

def main():
    """Main function to rebuild the window table."""
    logger.info("Starting nightly window table rebuild...")

    try:
        # Option 1: Call the existing make_window_table.py script
        script_path = BACKEND_ROOT / 'make_window_table.py'
        if not script_path.exists():
            raise FileNotFoundError(f"make_window_table.py not found at {script_path}")

        logger.info(f"Running {script_path}")
        # Force UTF-8 on the child: this runs from a Scheduled Task where the
        # console is cp1252, and text=True would otherwise decode with that
        # codec and blow up on any non-ASCII the child prints.
        child_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [sys.executable, str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
        )

        logger.info("Window table rebuild completed successfully")
        if result.stdout:
            logger.info(f"Output: {result.stdout}")

        # Populate our additive columns based on the freshly built table
        populate_additive_columns()

        logger.info("Nightly window table rebuild and additive column population completed successfully")

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to rebuild window table: {e}")
        logger.error(f"Stdout: {e.stdout}")
        logger.error(f"Stderr: {e.stderr}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error during window table rebuild: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
