#!/usr/bin/env python
"""
Nightly rebuild script for activity_window_10m table.
This script recreates the window table from scratch using the existing
make_window_table.py logic to recover from any trigger failures or schema changes.
"""

import subprocess
import sys
from pathlib import Path
import sqlite3
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/refresh_windows_nightly.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def populate_additive_columns():
    """Populate the additive columns based on the freshly built window table."""
    logger.info("Populating additive columns after window table rebuild...")

    try:
        con = sqlite3.connect("backend\\smartdesk.db")
        cur = con.cursor()

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
        script_path = Path(__file__).with_name('make_window_table.py')
        if not script_path.exists():
            raise FileNotFoundError(f"make_window_table.py not found at {script_path}")

        logger.info(f"Running {script_path}")
        result = subprocess.run(
            [sys.executable, str(script_path)],
            check=True,
            capture_output=True,
            text=True
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