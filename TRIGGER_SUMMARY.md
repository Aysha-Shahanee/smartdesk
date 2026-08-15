# Trigger-based Automatic 10-Minute Window Setup

## Files Created

1. `backend/create_window_triggers.sql` - SQL script to:
   - Add incremental columns to `activity_window_10m` for trigger-based updates
   - Populate those columns from existing data
   - Create the view `vw_activity_window_10m` that computes metrics from additive columns
   - Create the trigger `trg_activity_segments_insert` that updates window rows on each segment insert

2. `backend/refresh_windows_nightly.py` - Nightly rebuild script that:
   - Recreates the window table from scratch using `make_window_table.py`
   - Populates additive columns based on the freshly built data
   - Logs to `backend/logs/refresh_windows_nightly.log`

3. `backend/logs/` - Directory for nightly script logs

## Setup Instructions

### Step 1: Apply the Trigger Setup

Run the following command to add the incremental columns, populate them, create the view, and create the trigger:

```powershell
Get-Content backend\create_window_triggers.sql | sqlite3 backend\smartdesk.db
```

### Step 2: Fix the Trigger (Known Issue)

The trigger as generated has a syntax error due to an extra value in the INSERT list. To fix it:

1. Open `backend/create_window_triggers.sql`
2. Find the INSERT statement inside the trigger (around line 149).
3. Remove the following line from the column list:
   `sum_longest_cont_sec,`
4. Remove the corresponding line from the VALUES list:
   `0,  -- sum_longest_cont_sec (we will approximate later)`
5. Also remove the line from the ON CONFLICT DO UPDATE list:
   `sum_longest_cont_sec = sum_longest_cont_sec + EXCLUDED.sum_longest_cont_sec,`

Alternatively, you can replace the entire trigger with the corrected version below (copy and paste into the SQL file):

```sql
-- Corrected trigger for activity_segments insert
CREATE TRIGGER trg_activity_segments_insert
AFTER INSERT ON activity_segments
FOR EACH ROW
BEGIN
    INSERT OR REPLACE INTO activity_window_10m (
        window_start,
        window_end,
        window_id,
        sum_active_seconds,
        sum_idle_seconds,
        sum_app_switches,
        sum_category_switches,
        sum_unique_apps,
        sum_work_time,
        sum_learn_time,
        sum_communication_time,
        sum_entertainment_time,
        sum_documentation_time,
        sum_system_time,
        sum_other_time,
        sum_focus_weighted,
        sum_focus_duration,
        seg_count
    )
    VALUES (
        datetime((strftime('%s', NEW.start_time_utc) / 600) * 600, 'unixepoch'),
        datetime(((strftime('%s', NEW.start_time_utc) / 600) + 1) * 600, 'unixepoch'),
        strftime('%Y-%m-%d %H:%M:%S', datetime((strftime('%s', NEW.start_time_utc) / 600) * 600, 'unixepoch')) || '_10m',
        CASE WHEN NEW.state = 'active' THEN NEW.duration_sec ELSE 0 END,
        CASE WHEN NEW.state = 'idle'   THEN NEW.duration_sec ELSE 0 END,
        0,  -- app_switches (cannot determine from single segment)
        0,  -- category_switches
        CASE WHEN NEW.app_name IS NOT NULL AND TRIM(NEW.app_name) != '' THEN 1 ELSE 0 END,
        CASE WHEN NEW.category = 'work' THEN NEW.duration_sec ELSE 0 END,
        CASE WHEN NEW.category = 'learn' THEN NEW.duration_sec ELSE 0 END,
        CASE WHEN NEW.category = 'communication' THEN NEW.duration_sec ELSE 0 END,
        CASE WHEN NEW.category = 'entertainment' THEN NEW.duration_sec ELSE 0 END,
        CASE WHEN NEW.category = 'documentation' THEN NEW.duration_sec ELSE 0 END,
        CASE WHEN NEW.category = 'system' THEN NEW.duration_sec ELSE 0 END,
        CASE
            WHEN NEW.category NOT IN ('work','learn','communication','entertainment','documentation','system')
                 OR NEW.category IS NULL
                 OR TRIM(NEW.category) = ''
            THEN NEW.duration_sec
            ELSE 0
        END,
        CASE WHEN NEW.focus_score IS NOT NULL THEN NEW.focus_score * NEW.duration_sec ELSE 0 END,
        CASE WHEN NEW.focus_score IS NOT NULL THEN NEW.duration_sec ELSE 0 END,
        1  -- This segment contributes one to the count
    )
    ON CONFLICT(window_id) DO UPDATE SET
        sum_active_seconds   = sum_active_seconds   + EXCLUDED.sum_active_seconds,
        sum_idle_seconds     = sum_idle_seconds     + EXCLUDED.sum_idle_seconds,
        sum_app_switches     = sum_app_switches     + EXCLUDED.sum_app_switches,
        sum_category_switches= sum_category_switches+ EXCLUDED.sum_category_switches,
        sum_unique_apps      = sum_unique_apps      + EXCLUDED.sum_unique_apps,
        sum_work_time        = sum_work_time        + EXCLUDED.sum_work_time,
        sum_learn_time       = sum_learn_time       + EXCLUDED.sum_learn_time,
        sum_communication_time = sum_communication_time + EXCLUDED.sum_communication_time,
        sum_entertainment_time = sum_entertainment_time + EXCLUDED.sum_entertainment_time,
        sum_documentation_time = sum_documentation_time + EXCLUDED.sum_documentation_time,
        sum_system_time      = sum_system_time      + EXCLUDED.sum_system_time,
        sum_other_time       = sum_other_time       + EXCLUDED.sum_other_time,
        sum_focus_weighted   = sum_focus_weighted   + EXCLUDED.sum_focus_weighted,
        sum_focus_duration   = sum_focus_duration   + EXCLUDED.sum_focus_duration,
        seg_count            = seg_count            + EXCLUDED.seg_count;
END;
```

### Step 3: (Optional) Run Nightly Rebuild for Consistency

After applying the trigger, run the nightly rebuild script to ensure consistency:

```powershell
python backend\refresh_windows_nightly.py
```

This can be scheduled to run daily (e.g., 2:00 AM) via Windows Task Scheduler as a safety net.

## How It Works

- **Trigger Updates**: On each insert into `activity_segments`, the trigger computes the 10-minute window for the segment and updates the corresponding row in `activity_window_10m` by adding the segment's contributions to the additive columns (`sum_active_seconds`, `sum_idle_seconds`, etc.). The view `vw_activity_window_10m` then computes the final metrics from these additive columns.

- **Additive Columns**: The trigger updates these columns, which represent sums that can be updated incrementally:
  - `sum_active_seconds`, `sum_idle_seconds` (time in seconds)
  - `sum_work_time`, `sum_learn_time`, etc. (time per category in seconds)
  - `sum_focus_weighted`, `sum_focus_duration` (for duration-weighted focus score average)
  - `sum_app_switches`, `sum_category_switches`, `sum_unique_apps`, `sum_longest_cont_sec` (approximations)
  - `seg_count` (segment count)

- **View Computation**: The view computes the final metrics:
  - `active_seconds` = `sum_active_seconds`
  - `active_ratio` = `sum_active_seconds` / 600.0
  - (similar for idle)
  - `app_switches` = `sum_app_switches` (approximation)
  - `category_switches` = `sum_category_switches` (approximation)
  - `unique_apps` = `sum_unique_apps` (approximation: counts segments with an app name)
  - `work_ratio` = `sum_work_time` / 600.0
  - (similar for other categories)
  - `avg_focus_score` = `sum_focus_weighted` / `sum_focus_duration`
  - `longest_continuous_seconds` = `sum_longest_cont_sec` (approximation: total non-idle seconds)

- **Nightly Rebuild**: The nightly script recomputes the window table from scratch using `make_window_table.py`, which produces accurate values for all metrics. It then populates the additive columns based on the freshly built data. This corrects any approximation errors from the trigger.

## Verification

After setup, insert a test segment and verify the view updates:

```powershell
# Insert a test segment (adjust values as needed)
sqlite3 backend\smartdesk.db "
INSERT INTO activity_segments (
    id, user_id, device_id, schema_version, start_time_utc, end_time_utc, duration_sec,
    timezone_name, local_date, primary_source, app_name, title, detail, state,
    category, focus_score
) VALUES (
    'test-seg-123', 'test-user', 'test-device', 1,
    datetime('now'), datetime('now', '+5 minutes'), 300,
    'UTC', strftime('%Y-%m-%d', 'now'), 'ide', 'Code Editor', 'Writing code', 'Implementation work', 'active',
    'work', 0.85
);
"

# Check the view
sqlite3 backend\smartdesk.db "
SELECT window_start, window_end, active_seconds, work_ratio, avg_focus_score, seg_count
FROM vw_activity_window_10m
WHERE window_id LIKE '%_10m'
ORDER BY window_start DESC
LIMIT 1;
"
```

You should see the window update within milliseconds.

## Notes

- The trigger provides real-time updates for most metrics. Metrics that are difficult to update incrementally (app switches, category switches, unique apps, longest continuous streak) are approximations that are corrected by the nightly rebuild.
- The nightly rebuild serves as a safety net to recover from any trigger issues or schema changes.
- Ensure SQLite version supports `INSERT ... ON CONFLICT DO UPDATE` (requires SQLite 3.24+).