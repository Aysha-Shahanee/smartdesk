-- Setup view and trigger for activity_window_10m
-- Assuming the incremental columns already exist and are populated

-- Drop and recreate the view
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

-- Drop and recreate the trigger (corrected version)
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
