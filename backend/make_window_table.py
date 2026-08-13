#!/usr/bin/env python3
"""
Create a 10‑minute roll‑up table (activity_window_10m) from activity_segments.

Columns produced (exactly as you requested):
    window_start, window_end,
    active_seconds, idle_seconds,
    active_ratio, idle_ratio,
    app_switches, category_switches, unique_apps,
    work_ratio, learn_ratio, communication_ratio,
    entertainment_ratio, documentation_ratio,
    system_ratio, other_ratio,
    longest_continuous_seconds,
    avg_focus_score
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# ----------------------------------------------------------------------
# CONFIGURATION – change only if your column names differ in activity_segments
# ----------------------------------------------------------------------
DB_PATH = Path("smartdesk.db")
SRC_TABLE = "activity_segments"
DST_TABLE = "activity_window_10m"

# Source column names (as they appear in your schema)
COL_START   = "start_time_utc"
COL_END     = "end_time_utc"
COL_DUR     = "duration_sec"
COL_STATE   = "state"
COL_PRIMARY = "primary_source"
COL_APP     = "app_name"
COL_CAT     = "category"
COL_FOCUS   = "focus_score"

# Allowed categories – anything else will be bucketed into "other"
ALLOWED_CAT = {
    "work", "learn", "communication", "entertainment",
    "documentation", "system", "other"
}

# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def floor_to_10min(dt: datetime) -> datetime:
    """Round datetime down to the previous 10‑minute boundary (seconds=0)."""
    minutes = dt.minute - (dt.minute % 10)
    return dt.replace(minute=minutes, second=0, microsecond=0)

def main():
    # ------------------------------------------------------------------
    # 1️⃣  Open the database
    # ------------------------------------------------------------------
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row          # allows column‑name access
    cur = con.cursor()

    # ------------------------------------------------------------------
    # 2️⃣  Determine the overall time range we need to cover
    # ------------------------------------------------------------------
    cur.execute(f"""
        SELECT MIN({COL_START}), MAX({COL_START})
        FROM {SRC_TABLE}
        WHERE {COL_START} IS NOT NULL
    """)
    row = cur.fetchone()
    if row[0] is None or row[1] is None:
        raise RuntimeError("activity_segments table appears to be empty.")
    min_ts = datetime.fromisoformat(row[0])
    max_ts = datetime.fromisoformat(row[1])

    # Align start to a 10‑minute grid
    window_start = floor_to_10min(min_ts)
    # We will iterate until we pass the latest start time (plus one window to catch the final partial window)
    window_end_exclusive = floor_to_10min(max_ts) + timedelta(minutes=10)

    # ------------------------------------------------------------------
    # 3️⃣  Define the destination table columns (order matters for INSERT)
    # ------------------------------------------------------------------
    columns = [
        "window_start",          # TEXT NOT NULL
        "window_end",            # TEXT NOT NULL
        "window_id",             # TEXT PRIMARY KEY
        "active_seconds",        # INTEGER NOT NULL
        "idle_seconds",          # INTEGER NOT NULL
        "active_ratio",          # REAL NOT NULL
        "idle_ratio",            # REAL NOT NULL
        "app_switches",          # INTEGER NOT NULL
        "category_switches",     # INTEGER NOT NULL
        "unique_apps",           # INTEGER NOT NULL
        "work_ratio",            # REAL NOT NULL
        "learn_ratio",           # REAL NOT NULL
        "communication_ratio",   # REAL NOT NULL
        "entertainment_ratio",   # REAL NOT NULL
        "documentation_ratio",   # REAL NOT NULL
        "system_ratio",          # REAL NOT NULL
        "other_ratio",           # REAL NOT NULL
        "longest_continuous_seconds", # INTEGER NOT NULL
        "avg_focus_score"        # REAL NOT NULL
    ]

    # ------------------------------------------------------------------
    # 4️⃣  Make sure the destination table exists (no other tables altered)
    # ------------------------------------------------------------------
    col_defs = ",\n        ".join(
        [
            "window_start   TEXT NOT NULL",
            "window_end     TEXT NOT NULL",
            "window_id      TEXT PRIMARY KEY",
            "active_seconds INTEGER NOT NULL",
            "idle_seconds   INTEGER NOT NULL",
            "active_ratio   REAL NOT NULL",
            "idle_ratio     REAL NOT NULL",
            "app_switches   INTEGER NOT NULL",
            "category_switches INTEGER NOT NULL",
            "unique_apps    INTEGER NOT NULL",
            "work_ratio     REAL NOT NULL",
            "learn_ratio    REAL NOT NULL",
            "communication_ratio REAL NOT NULL",
            "entertainment_ratio REAL NOT NULL",
            "documentation_ratio REAL NOT NULL",
            "system_ratio   REAL NOT NULL",
            "other_ratio    REAL NOT NULL",
            "longest_continuous_seconds INTEGER NOT NULL",
            "avg_focus_score REAL NOT NULL"
        ]
    )
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {DST_TABLE} (
            {col_defs}
        )
    """)
    con.commit()

    # ------------------------------------------------------------------
    # 5️⃣  Prepare the INSERT statement with dynamic placeholders
    # ------------------------------------------------------------------
    placeholders = ", ".join(["?"] * len(columns))
    insert_sql = f"""
        INSERT OR REPLACE INTO {DST_TABLE} (
            {", ".join(columns)}
        ) VALUES ({placeholders})
    """

    # ------------------------------------------------------------------
    # 6️⃣  Iterate over windows and aggregate
    # ------------------------------------------------------------------
    print(f"Processing windows from {window_start.isoformat()} "
          f"to {window_end_exclusive.isoformat()} (10‑min steps)…")
    total_windows = 0

    while window_start < window_end_exclusive:
        win_start = window_start
        win_end   = window_start + timedelta(minutes=10)

        # Pull all segments whose START time falls inside this window
        cur.execute(f"""
            SELECT
                {COL_START}, {COL_END}, {COL_DUR},
                {COL_STATE}, {COL_PRIMARY}, {COL_APP},
                {COL_CAT}, {COL_FOCUS}
            FROM {SRC_TABLE}
            WHERE {COL_START} >= ? AND {COL_START} < ?
            ORDER BY {COL_START}
        """, (win_start.isoformat(sep=' '), win_end.isoformat(sep=' ')))
        rows = cur.fetchall()

        # ---- initialise aggregates for this window ----
        active_sec = idle_sec = 0
        focus_weighted_sum = 0.0
        focus_weight_sum = 0.0

        # switches – we will count changes while iterating
        app_switches = 0
        category_switches = 0
        prev_primary = None
        prev_category = None

        # unique apps
        apps_seen = set()

        # category time accumulators
        cat_time = {c: 0 for c in ALLOWED_CAT}

        # longest continuous *non‑idle* stretch
        longest_active = 0
        current_active = 0

        for r in rows:
            dur = r[COL_DUR] or 0
            state = r[COL_STATE] or ""

            # ----- time counters -----
            if state == "active":
                active_sec += dur
            elif state == "idle":
                idle_sec += dur
            # (locked / gap are ignored for the requested columns)

            # ----- focus score (duration‑weighted) -----
            focus = r[COL_FOCUS]
            if focus is not None:
                focus_weighted_sum += float(focus) * dur
                focus_weight_sum += dur

            # ----- switches -----
            prim = r[COL_PRIMARY]
            cat  = r[COL_CAT]
            if prev_primary is not None and prim != prev_primary:
                app_switches += 1
            if prev_category is not None and cat != prev_category:
                category_switches += 1
            prev_primary = prim
            prev_category = cat

            # ----- unique apps -----
            app_name = r[COL_APP]
            if app_name:
                apps_seen.add(app_name)

            # ----- category time -----
            # bucket unknown categories into "other"
            if cat in ALLOWED_CAT:
                cat_time[cat] += dur
            else:
                cat_time["other"] += dur

            # ----- longest continuous non‑idle stretch -----
            # treat anything that is NOT idle as "active" for this metric
            if state != "idle":
                current_active += dur
                if current_active > longest_active:
                    longest_active = current_active
            else:
                current_active = 0   # break the streak

        # ---- compute ratios (avoid division by zero) ----
        win_len_sec = 600.0               # 10 minutes in seconds
        active_ratio = active_sec / win_len_sec if win_len_sec else 0.0
        idle_ratio   = idle_sec   / win_len_sec if win_len_sec else 0.0

        work_ratio        = cat_time["work"]        / win_len_sec
        learn_ratio       = cat_time["learn"]       / win_len_sec
        communication_ratio = cat_time["communication"] / win_len_sec
        entertainment_ratio = cat_time["entertainment"] / win_len_sec
        documentation_ratio = cat_time["documentation"] / win_len_sec
        system_ratio      = cat_time["system"]      / win_len_sec
        other_ratio       = cat_time["other"]       / win_len_sec

        unique_apps = len(apps_seen)

        # average focus score (duration weighted); fallback to simple mean if weight==0
        if focus_weight_sum > 0:
            avg_focus = focus_weighted_sum / focus_weight_sum
        else:
            # No focus values – use plain mean of non‑null scores (or 0)
            focus_vals = [float(r[COL_FOCUS]) for r in rows if r[COL_FOCUS] is not None]
            avg_focus = sum(focus_vals) / len(focus_vals) if focus_vals else 0.0

        # window identifier (human readable, e.g. "2026-08-08 10:20_10m")
        win_id = f"{win_start.strftime('%Y-%m-%d %H:%M')}_10m"

        # Build the values tuple in the same order as `columns`
        values = (
            win_start.isoformat(sep=' '),   # window_start
            win_end.isoformat(sep=' '),     # window_end
            win_id,                         # window_id
            active_sec,                     # active_seconds
            idle_sec,                       # idle_seconds
            active_ratio,                   # active_ratio
            idle_ratio,                     # idle_ratio
            app_switches,                   # app_switches
            category_switches,              # category_switches
            unique_apps,                    # unique_apps
            work_ratio,                     # work_ratio
            learn_ratio,                    # learn_ratio
            communication_ratio,            # communication_ratio
            entertainment_ratio,            # entertainment_ratio
            documentation_ratio,            # documentation_ratio
            system_ratio,                   # system_ratio
            other_ratio,                    # other_ratio
            longest_active,                 # longest_continuous_seconds
            avg_focus                       # avg_focus_score
        )

        # Execute the insert
        cur.execute(insert_sql, values)
        con.commit()
        total_windows += 1
        window_start = win_end   # advance to next window

    print(f"✅ Finished. {total_windows} windows written to table '{DST_TABLE}'.")
    con.close()

if __name__ == "__main__":
    main()
