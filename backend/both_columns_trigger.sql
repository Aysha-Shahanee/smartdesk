CREATE TRIGGER trg_activity_segments_insert
AFTER INSERT ON activity_segments
FOR EACH ROW
BEGIN
    INSERT INTO activity_window_10m (
        window_start,
        window_end,
        window_id,
        active_seconds,
        idle_seconds,
        active_ratio,
        idle_ratio,
        app_switches,
        category_switches,
        unique_apps,
        work_ratio,
        learn_ratio,
        communication_ratio,
        entertainment_ratio,
        documentation_ratio,
        system_ratio,
        other_ratio,
        longest_continuous_seconds,
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
        -- Computed window boundaries
        datetime((strftime('%s', NEW.start_time_utc) / 600) * 600, 'unixepoch'),
        datetime(((strftime('%s', NEW.start_time_utc) / 600) + 1) * 600, 'unixepoch'),
        strftime('%Y-%m-%d %H:%M:%S', datetime((strftime('%s', NEW.start_time_utc) / 600) * 600, 'unixepoch')) || '_10m',

        -- MAIN columns (computed from segment data)
        CASE WHEN NEW.state = 'active' THEN NEW.duration_sec ELSE 0 END,                                    -- active_seconds
        CASE WHEN NEW.state = 'idle'   THEN NEW.duration_sec ELSE 0 END,                                    -- idle_seconds
        CASE WHEN 600.0 = 0 THEN 0 ELSE (CASE WHEN NEW.state = 'active' THEN NEW.duration_sec ELSE 0 END) / 600.0 END,  -- active_ratio
        CASE WHEN 600.0 = 0 THEN 0 ELSE (CASE WHEN NEW.state = 'idle'   THEN NEW.duration_sec ELSE 0 END) / 600.0 END,  -- idle_ratio
        0,  -- app_switches
        0,  -- category_switches
        CASE WHEN NEW.app_name IS NOT NULL AND TRIM(NEW.app_name) != '' THEN 1 ELSE 0 END,                     -- unique_apps
        CASE WHEN 600.0 = 0 THEN 0 ELSE (CASE WHEN NEW.category = 'work' THEN NEW.duration_sec ELSE 0 END) / 600.0 END,  -- work_ratio
        CASE WHEN 600.0 = 0 THEN 0 ELSE (CASE WHEN NEW.category = 'learn' THEN NEW.duration_sec ELSE 0 END) / 600.0 END,  -- learn_ratio
        CASE WHEN 600.0 = 0 THEN 0 ELSE (CASE WHEN NEW.category = 'communication' THEN NEW.duration_sec ELSE 0 END) / 600.0 END,  -- communication_ratio
        CASE WHEN 600.0 = 0 THEN 0 ELSE (CASE WHEN NEW.category = 'entertainment' THEN NEW.duration_sec ELSE 0 END) / 600.0 END,  -- entertainment_ratio
        CASE WHEN 600.0 = 0 THEN 0 ELSE (CASE WHEN NEW.category = 'documentation' THEN NEW.duration_sec ELSE 0 END) / 600.0 END,  -- documentation_ratio
        CASE WHEN 600.0 = 0 THEN 0 ELSE (CASE WHEN NEW.category = 'system' THEN NEW.duration_sec ELSE 0 END) / 600.0 END,  -- system_ratio
        CASE
            WHEN NEW.category NOT IN ('work','learn','communication','entertainment','documentation','system')
                 OR NEW.category IS NULL
                 OR TRIM(NEW.category) = ''
            THEN NEW.duration_sec
            ELSE 0
        END / 600.0,  -- other_ratio
        CASE WHEN NEW.state != 'idle' THEN NEW.duration_sec ELSE 0 END,                                     -- longest_continuous_seconds (approximation)
        CASE WHEN NEW.focus_score IS NOT NULL THEN NEW.focus_score ELSE 0 END,                              -- avg_focus_score (placeholder, will be corrected below)

        -- SUM columns (for incremental updates)
        CASE WHEN NEW.state = 'active' THEN NEW.duration_sec ELSE 0 END,                                    -- sum_active_seconds
        CASE WHEN NEW.state = 'idle'   THEN NEW.duration_sec ELSE 0 END,                                    -- sum_idle_seconds
        0,  -- sum_app_switches
        0,  -- sum_category_switches
        CASE WHEN NEW.app_name IS NOT NULL AND TRIM(NEW.app_name) != '' THEN 1 ELSE 0 END,                     -- sum_unique_apps
        CASE WHEN NEW.category = 'work' THEN NEW.duration_sec ELSE 0 END,                                     -- sum_work_time
        CASE WHEN NEW.category = 'learn' THEN NEW.duration_sec ELSE 0 END,                                    -- sum_learn_time
        CASE WHEN NEW.category = 'communication' THEN NEW.duration_sec ELSE 0 END,                            -- sum_communication_time
        CASE WHEN NEW.category = 'entertainment' THEN NEW.duration_sec ELSE 0 END,                            -- sum_entertainment_time
        CASE WHEN NEW.category = 'documentation' THEN NEW.duration_sec ELSE 0 END,                            -- sum_documentation_time
        CASE WHEN NEW.category = 'system' THEN NEW.duration_sec ELSE 0 END,                                   -- sum_system_time
        CASE
            WHEN NEW.category NOT IN ('work','learn','communication','entertainment','documentation','system')
                 OR NEW.category IS NULL
                 OR TRIM(NEW.category) = ''
            THEN NEW.duration_sec
            ELSE 0
        END,                                                                -- sum_other_time
        CASE WHEN NEW.focus_score IS NOT NULL THEN NEW.focus_score * NEW.duration_sec ELSE 0 END,             -- sum_focus_weighted
        CASE WHEN NEW.focus_score IS NOT NULL THEN NEW.duration_sec ELSE 0 END,                               -- sum_focus_duration
        1  -- seg_count
    )
    ON CONFLICT(window_id) DO UPDATE SET
        -- Update each column by adding the new segment's contribution
        active_seconds   = active_seconds   + EXCLUDED.active_seconds,
        idle_seconds     = idle_seconds     + EXCLUDED.idle_seconds,
        active_ratio     = active_ratio     + EXCLUDED.active_ratio,
        idle_ratio       = idle_ratio       + EXCLUDED.idle_ratio,
        app_switches     = app_switches     + EXCLUDED.app_switches,
        category_switches= category_switches+ EXCLUDED.category_switches,
        unique_apps      = unique_apps      + EXCLUDED.unique_apps,
        work_ratio       = work_ratio       + EXCLUDED.work_ratio,
        learn_ratio      = learn_ratio      + EXCLUDED.learn_ratio,
        communication_ratio = communication_ratio + EXCLUDED.communication_ratio,
        entertainment_ratio = entertainment_ratio + EXCLUDED.entertainment_ratio,
        documentation_ratio = documentation_ratio + EXCLUDED.documentation_ratio,
        system_ratio     = system_ratio     + EXCLUDED.system_ratio,
        other_ratio      = other_ratio      + EXCLUDED.other_ratio,
        longest_continuous_seconds = longest_continuous_seconds + EXCLUDED.longest_continuous_seconds,
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