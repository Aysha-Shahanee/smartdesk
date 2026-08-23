#!/usr/bin/env python3
"""
Create a 10-minute roll-up table (activity_window_10m) from activity_segments.

Columns produced:
    window_start, window_end, window_id,
    active_seconds, idle_seconds,
    active_ratio, idle_ratio,
    app_switches, category_switches, unique_apps,
    work_ratio, learn_ratio, communication_ratio,
    entertainment_ratio, documentation_ratio,
    system_ratio, other_ratio,
    longest_continuous_seconds,
    avg_focus_score

Every duration written here is the segment's **overlap with the window**, not
its whole length. The first version of this file selected segments by start
time and credited each one's entire duration to the window containing that
start. ActivitySegmentBuilder caps segments at 900 s against a 600 s window, so
a single segment could push a ratio to 1.5 on its own -- measured across the
recorded history, 535 of 1,299 non-empty windows reported active_ratio > 1.0,
peaking at 2.47, and 419 reported work_ratio > 1.0. Every ratio here feeds
StandardScaler and KMeans in scoped_window_pattern_analysis.py, and every
recommendation rule that thresholds on one was reading a number that could
exceed its own definition. Segments are now clipped to the window and their
remainder carried into the following windows.
"""

import sys
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings

def get_db_path() -> Path:
    db_url = settings.DATABASE_URL
    if db_url.startswith("sqlite:///"):
        path_str = db_url[len("sqlite:///"):].replace("/", os.sep)
        return BACKEND_ROOT / path_str
    return BACKEND_ROOT / "smartdesk.db"

DB_PATH = get_db_path()
SRC_TABLE = "activity_segments"
DST_TABLE = "activity_window_10m"

COL_START = "start_time_utc"
COL_END = "end_time_utc"
COL_STATE = "state"
COL_APP = "app_name"
COL_CAT = "category"
COL_FOCUS = "focus_score"

WINDOW_SEC = 600.0
WINDOW_DELTA = timedelta(seconds=WINDOW_SEC)

# Categories with a dedicated ratio column. "documentation" is deliberately
# absent: ck_activity_segments_category has never permitted it and
# Categorizer.CATEGORY_ALIASES rewrites it to "work" before it can be stored,
# so the column it used to fill was constant zero across all 5,125 windows --
# a dead dimension that StandardScaler still scaled and KMeans still consumed.
# The column itself is kept and written as 0.0 so the table shape does not
# change under anything already reading it; it is no longer a clustering
# feature. See ScopedWindowPatternAnalysisService.FEATURE_COLUMNS.
RATIO_CATEGORIES = (
    "work", "learn", "communication", "entertainment", "system", "other",
)

COLUMNS = [
    "window_start", "window_end", "window_id",
    "active_seconds", "idle_seconds",
    "active_ratio", "idle_ratio",
    "app_switches", "category_switches", "unique_apps",
    "work_ratio", "learn_ratio", "communication_ratio",
    "entertainment_ratio", "documentation_ratio",
    "system_ratio", "other_ratio",
    "longest_continuous_seconds",
    "avg_focus_score",
]

COL_DEFS = """
    window_start   TEXT NOT NULL,
    window_end     TEXT NOT NULL,
    window_id      TEXT PRIMARY KEY,
    active_seconds INTEGER NOT NULL,
    idle_seconds   INTEGER NOT NULL,
    active_ratio   REAL NOT NULL,
    idle_ratio     REAL NOT NULL,
    app_switches   INTEGER NOT NULL,
    category_switches INTEGER NOT NULL,
    unique_apps    INTEGER NOT NULL,
    work_ratio     REAL NOT NULL,
    learn_ratio    REAL NOT NULL,
    communication_ratio REAL NOT NULL,
    entertainment_ratio REAL NOT NULL,
    documentation_ratio REAL NOT NULL,
    system_ratio   REAL NOT NULL,
    other_ratio    REAL NOT NULL,
    longest_continuous_seconds INTEGER NOT NULL,
    avg_focus_score REAL NOT NULL
"""


# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def floor_to_10min(dt: datetime) -> datetime:
    """Round a datetime down to the previous 10-minute boundary."""
    return dt.replace(minute=dt.minute - (dt.minute % 10), second=0, microsecond=0)


def parse_ts(value: str | None) -> datetime | None:
    """Parse a stored timestamp. These are naive local strings despite the
    column name; treating them as such keeps window keys aligned with
    local_date, which every date-filtered query in the app relies on."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class WindowAccumulator:
    """Running totals for one 10-minute window.

    Holds only scalars plus the app/category of the last segment seen, so
    memory stays flat no matter how many segments land in the window.
    """

    __slots__ = (
        "active", "idle", "focus_weighted", "focus_duration",
        "app_switches", "category_switches", "apps", "cat_time",
        "longest_run", "current_run", "last_app", "last_cat", "last_end",
    )

    def __init__(self) -> None:
        self.active = 0.0
        self.idle = 0.0
        self.focus_weighted = 0.0
        self.focus_duration = 0.0
        self.app_switches = 0
        self.category_switches = 0
        self.apps: set[str] = set()
        self.cat_time: dict[str, float] = {c: 0.0 for c in RATIO_CATEGORIES}
        self.longest_run = 0.0
        self.current_run = 0.0
        self.last_app: str | None = None
        self.last_cat: str | None = None
        self.last_end: datetime | None = None

    def add(
        self,
        overlap: float,
        state: str,
        app: str | None,
        category: str | None,
        focus: float | None,
        starts_inside: bool,
    ) -> None:
        """Fold one segment's overlap with this window into the totals.

        ``starts_inside`` says whether the segment actually began inside this
        window. A segment spilling over from the previous window contributes
        its time but not a switch: attention did not move at the window edge,
        the clock did.
        """
        if overlap <= 0:
            return

        if state == "active":
            self.active += overlap
        elif state == "idle":
            self.idle += overlap
        # 'locked' and 'gap' contribute to neither counter, matching the
        # original behaviour and the two states' meaning: nobody was there.

        if focus is not None:
            self.focus_weighted += focus * overlap
            self.focus_duration += overlap

        if app:
            self.apps.add(app)

        bucket = category if category in self.cat_time else "other"
        self.cat_time[bucket] += overlap

        # Switches are counted only at boundaries that fall inside the window,
        # and only where the thing actually changed. app_switches counts
        # app_name changes -- the original counted primary_source ('os' / 'ide'
        # / 'browser') changes, which is a source-attribution change and not an
        # attention change at all, so the column never measured what its name
        # claims. FocusScorer.neighbourhood_switch_rates counts app_name for
        # the same reason.
        if starts_inside and self.last_app is not None and app != self.last_app:
            self.app_switches += 1
        if starts_inside and self.last_cat is not None and category != self.last_cat:
            self.category_switches += 1
        self.last_app = app
        self.last_cat = category

        # Longest unbroken non-idle stretch. A gap in wall-clock between two
        # segments breaks the run just as an idle segment does; without the
        # last_end check two segments an hour apart would concatenate.
        if state == "idle":
            self.current_run = 0.0
        else:
            self.current_run += overlap
            self.longest_run = max(self.longest_run, self.current_run)

    def row(self, win_start: datetime, win_end: datetime) -> tuple:
        avg_focus = (
            self.focus_weighted / self.focus_duration
            if self.focus_duration > 0
            else 0.0
        )
        # Clamped, not merely divided. A window covered end to end sums its
        # overlaps to 600.0000000000002 s through ordinary float addition, and
        # the ratio then reads 1.0000000000000002 -- harmless arithmetically,
        # but it defeats the "no ratio exceeds 1.0" invariant that the rule
        # engine and its regression test both depend on being exact.
        ratios = {
            c: min(1.0, self.cat_time[c] / WINDOW_SEC) for c in RATIO_CATEGORIES
        }
        return (
            win_start.isoformat(sep=" "),
            win_end.isoformat(sep=" "),
            f"{win_start.strftime('%Y-%m-%d %H:%M')}_10m",
            int(round(self.active)),
            int(round(self.idle)),
            min(1.0, self.active / WINDOW_SEC),
            min(1.0, self.idle / WINDOW_SEC),
            self.app_switches,
            self.category_switches,
            len(self.apps),
            ratios["work"],
            ratios["learn"],
            ratios["communication"],
            ratios["entertainment"],
            0.0,                          # documentation_ratio -- see RATIO_CATEGORIES
            ratios["system"],
            ratios["other"],
            int(round(self.longest_run)),
            avg_focus,
        )


def main() -> None:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute(f"CREATE TABLE IF NOT EXISTS {DST_TABLE} ({COL_DEFS})")
    con.commit()

    # One pass over the segments instead of one query per window. The old loop
    # issued a SELECT and a COMMIT for each of ~5,100 windows; this reads the
    # table once and writes in a single transaction.
    rows = cur.execute(f"""
        SELECT {COL_START}, {COL_END}, {COL_STATE}, {COL_APP}, {COL_CAT}, {COL_FOCUS}
        FROM {SRC_TABLE}
        WHERE {COL_START} IS NOT NULL AND {COL_END} IS NOT NULL
        ORDER BY {COL_START}
    """).fetchall()

    if not rows:
        raise RuntimeError("activity_segments table appears to be empty.")

    # Plain ASCII: this runs unattended from a Scheduled Task, where stdout is
    # a cp1252 console. A non-breaking hyphen or an ellipsis here raises
    # UnicodeEncodeError and kills the run before a single window is written.
    print(f"Reading {len(rows)} segments...")

    windows: dict[datetime, WindowAccumulator] = {}

    for row in rows:
        seg_start = parse_ts(row[COL_START])
        seg_end = parse_ts(row[COL_END])
        if seg_start is None or seg_end is None or seg_end <= seg_start:
            continue

        state = row[COL_STATE] or ""
        app = row[COL_APP]
        category = row[COL_CAT]
        focus = row[COL_FOCUS]
        focus = float(focus) if focus is not None else None

        # Walk every window the segment touches, crediting only the overlap.
        cursor_start = floor_to_10min(seg_start)
        while cursor_start < seg_end:
            cursor_end = cursor_start + WINDOW_DELTA
            overlap = (
                min(seg_end, cursor_end) - max(seg_start, cursor_start)
            ).total_seconds()
            if overlap > 0:
                accumulator = windows.get(cursor_start)
                if accumulator is None:
                    accumulator = windows[cursor_start] = WindowAccumulator()
                accumulator.add(
                    overlap=overlap,
                    state=state,
                    app=app,
                    category=category,
                    focus=focus,
                    starts_inside=cursor_start <= seg_start < cursor_end,
                )
            cursor_start = cursor_end

    # Fill the empty windows between recorded activity. The clustering treats
    # an untouched window as a real observation of an idle stretch, so the grid
    # has to be continuous rather than only the windows that happen to have
    # segments in them.
    grid_start = floor_to_10min(min(windows))
    grid_end = floor_to_10min(max(windows)) + WINDOW_DELTA
    cursor = grid_start
    while cursor < grid_end:
        windows.setdefault(cursor, WindowAccumulator())
        cursor += WINDOW_DELTA

    placeholders = ", ".join("?" * len(COLUMNS))
    insert_sql = (
        f"INSERT OR REPLACE INTO {DST_TABLE} ({', '.join(COLUMNS)}) "
        f"VALUES ({placeholders})"
    )
    payload = [
        windows[start].row(start, start + WINDOW_DELTA)
        for start in sorted(windows)
    ]
    cur.executemany(insert_sql, payload)
    con.commit()

    over_unity = sum(1 for r in payload if r[5] > 1.0 or r[6] > 1.0)
    print(f"Finished. {len(payload)} windows written to table '{DST_TABLE}'.")
    print(f"Windows with a ratio above 1.0: {over_unity} (expected 0).")
    con.close()


if __name__ == "__main__":
    main()
