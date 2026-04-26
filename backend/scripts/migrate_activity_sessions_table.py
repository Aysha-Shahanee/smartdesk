#!/usr/bin/env python3
"""Create/verify activity_sessions derived table."""

import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.ml.activity_sessions import create_activity_sessions_table
import sqlite3


def main():
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else backend_dir / "smartdesk.db"
    conn = sqlite3.connect(str(db_path))
    try:
        create_activity_sessions_table(conn)
        print(f"[ok] activity_sessions table ready in {db_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
