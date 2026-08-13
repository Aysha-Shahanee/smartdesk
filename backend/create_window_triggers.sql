-- Implementation Plan: Automatic 10‑Minute Window Creation via SQLite Trigger
-- Schema Adjustments: Add incremental columns to activity_window_10m

-- First, let's check if the table exists and what columns it has
-- We'll add columns only if they don't exist to avoid "duplicate column" errors

-- Create a temporary table to hold the original data if needed
-- But for simplicity, we'll try to add columns and ignore errors if they already exist

-- Add the new columns (if they don't already exist)
-- In SQLite, we can't use IF NOT EXISTS with ALTER TABLE, so we'll try and catch the conceptually
-- Since we're executing via script, we'll just try and if it fails because column exists, we continue

-- Since we can't easily catch errors in pure SQL, we'll split this into two parts:
-- 1. Try to add columns (may fail if they exist)
-- 2. Populate the columns based on existing data

-- Let's first check current table structure by trying to select from it
-- If the table doesn't exist, we'll need to create it, but assuming it does exist from make_window_table.py

-- Adding columns - we'll use a trick: if we get an error, we'll ignore it in the application layer
-- For now, let's just add them and if they exist, we'll get an error but we can handle it

ALTER TABLE activity_window_10m ADD COLUMN sum_active_seconds   REAL;
ALTER TABLE activity_window_10m ADD COLUMN sum_idle_seconds     REAL;
ALTER TABLE activity_window_10m ADD COLUMN sum_app_switches     INTEGER;
ALTER TABLE activity_window_10m ADD COLUMN sum_category_switches INTEGER;
ALTER TABLE activity_window_10m ADD COLUMN sum_unique_apps      INTEGER;
ALTER TABLE activity_window_10m ADD COLUMN sum_work_time        REAL;
ALTER TABLE activity_window_10m ADD COLUMN sum_learn_time       REAL;
ALTER TABLE activity_window_10m ADD COLUMN sum_communication_time REAL;
ALTER TABLE activity_window_10m ADD COLUMN sum_entertainment_time REAL;
ALTER TABLE activity_window_10m ADD COLUMN sum_documentation_time REAL;
ALTER TABLE activity_window_10m ADD COLUMN sum_system_time      REAL;
ALTER TABLE activity_window_10m ADD COLUMN sum_other_time       REAL;
ALTER TABLE activity_window_10m ADD COLUMN sum_focus_weighted   REAL;  -- sum of (focus_score * duration_sec)
ALTER TABLE activity_window_10m ADD COLUMN sum_focus_duration   REAL;  -- sum of duration_sec for focused segments
ALTER TABLE activity_window_10m ADD COLUMN seg_count            INTEGER;

-- Set default values for new columns where they are NULL
UPDATE activity_window_10m SET
    sum_active_seconds   = COALESCE(sum_active_seconds,   0),
    sum_idle_seconds     = COALESCE(sum_idle_seconds,     0),
    sum_app_switches     = COALESCE(sum_app_switches,     0),
    sum_category_switches= COALESCE(sum_category_switches, 0),
    sum_unique_apps      = COALESCE(sum_unique_apps,      0),
    sum_work_time        = COALESCE(sum_work_time,        0),
    sum_learn_time       = COALESCE(sum_learn_time,       0),
    sum_communication_time = COALESCE(sum_communication_time, 0),
    sum_entertainment_time = COALESCE(sum_entertainment_time, 0),
    sum_documentation_time = COALESCE(sum_documentation_time, 0),
    sum_system_time      = COALESCE(sum_system_time,      0),
    sum_other_time       = COALESCE(sum_other_time,       0),
    sum_focus_weighted   = COALESCE(sum_focus_weighted,   0),
    sum_focus_duration   = COALESCE(sum_focus_duration,   0),
    seg_count            = COALESCE(seg_count,            0);

-- Populate the additive columns based on existing data in activity_window_10m
-- We need to reverse-engineer the sums from the current values
-- Note: This assumes the current window table was populated correctly by make_window_table.py

-- For rows where seg_count is NULL or 0 (uninitialized), set based on existing averaged columns
UPDATE activity_window_10m SET
    sum_active_seconds   = active_seconds,
    sum_idle_seconds     = idle_seconds,
    sum_work_time        = work_ratio * 600.0,  -- work_ratio is work_time/600, so work_time = work_ratio * 600
    sum_learn_time       = learn_ratio * 600.0,
    sum_communication_time = communication_ratio * 600.0,
    sum_entertainment_time = entertainment_ratio * 600.0,
    sum_documentation_time = documentation_ratio * 600.0,
    sum_system_time      = system_ratio * 600.0,
    sum_other_time       = other_ratio * 600.0,
    sum_focus_weighted   = avg_focus_score * 600.0,  -- Assuming avg_focus_score is already the average
    sum_focus_duration   = 600.0,                   -- Assumes full window had focus score (will be corrected by nightly)
    seg_count            = 1
WHERE (seg_count IS NULL OR seg_count = 0) AND window_id IS NOT NULL;

-- For rows where seg_count > 0, compute the additive columns from the averaged columns
UPDATE activity_window_10m SET
    sum_active_seconds   = active_seconds,
    sum_idle_seconds     = idle_seconds,
    sum_work_time        = work_ratio * 600.0,
    sum_learn_time       = learn_ratio * 600.0,
    sum_communication_time = communication_ratio * 600.0,
    sum_entertainment_time = entertainment_ratio * 600.0,
    sum_documentation_time = documentation_ratio * 600.0,
    sum_system_time      = system_ratio * 600.0,
    sum_other_time       = other_ratio * 600.0,
    sum_focus_weighted   = avg_focus_score * 600.0,
    sum_focus_duration   = 600.0
WHERE seg_count > 0 AND window_id IS NOT NULL;

-- Create the view that presents the window data exactly as the original table
-- but computes metrics from the additive columns (maintaining backward compatibility)
DROP VIEW IF EXISTS vw_activity_window_10m;
CREATE VIEW vw_activity_window_10m AS
SELECT
    w.window_start,
    w.window_end,
    w.window_id,
    w.sum_active_seconds   AS active_seconds,
    w.sum_idle_seconds     AS idle_seconds,
    CASE WHEN 600.0 = 0 THEN 0 ELSE w.sum_active_seconds   / 600.0 END AS active_ratio,
    CASE WHEN 600.0 = 0 THEN 0 ELSE w.sum_idle_seconds     / 600.0 END AS idle_ratio,
    w.sum_app_switches     AS app_switches,
    w.sum_category_switches AS category_switches,
    w.sum_unique_apps      AS unique_apps,
    CASE WHEN 600.0 = 0 THEN 0 ELSE w.sum_work_time        / 600.0 END AS work_ratio,
    CASE WHEN 600.0 = 0 THEN 0 ELSE w.sum_learn_time       / 600.0 END AS learn_ratio,
    CASE WHEN 600.0 = 0 THEN 0 ELSE w.sum_communication_time / 600.0 END AS communication_ratio,
    CASE WHEN 600.0 = 0 THEN 0 ELSE w.sum_entertainment_time / 600.0 END AS entertainment_ratio,
    CASE WHEN 600.0 = 0 THEN 0 ELSE w.sum_documentation_time / 600.0 END AS documentation_ratio,
    CASE WHEN 600.0 = 0 THEN 0 ELSE w.sum_system_time      / 600.0 END AS system_ratio,
    CASE WHEN 600.0 = 0 THEN 0 ELSE w.sum_other_time       / 600.0 END AS other_ratio,
    w.sum_longest_cont_sec AS longest_continuous_seconds,
    CASE WHEN w.sum_focus_duration = 0 THEN 0
         ELSE w.sum_focus_weighted / w.sum_focus_duration
    END AS avg_focus_score
FROM activity_window_10m w;

-- Create the trigger for incremental updates on activity_segments insert
-- This trigger fires for each inserted segment and updates the appropriate window row incrementally
-- CORRECTED VERSION - removed sum_longest_cont_sec as it cannot be updated incrementally
DROP TRIGGER IF EXISTS trg_activity_segments_insert;
CREATE TRIGGER trg_activity_segments_insert
AFTER INSERT ON activity_segments
FOR EACH ROW
BEGIN
    INSERT OR REPLACE INTO activity_window_10m (
        window_start,
        window_end,
        window_id,
        avg_focus_score,
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
        CASE WHEN NEW.focus_score IS NOT NULL THEN NEW.focus_score ELSE 0 END,
        CASE WHEN NEW.state = 'active' THEN NEW.duration_sec ELSE 0 END,
        CASE WHEN NEW.state = 'idle'   THEN NEW.duration_sec ELSE 0 END,
        0,  -- sum_app_switches (cannot determine from single segment - will be corrected by nightly rebuild)
        0,  -- sum_category_switches (cannot determine from single segment - will be corrected by nightly rebuild)
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
        avg_focus_score  = CASE
            WHEN (sum_focus_duration + EXCLUDED.sum_focus_duration) = 0 THEN 0
            ELSE (sum_focus_weighted + EXCLUDED.sum_focus_weighted) / (sum_focus_duration + EXCLUDED.sum_focus_duration)
        END,
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
