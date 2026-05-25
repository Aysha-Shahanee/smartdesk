-- Migration: Add timeline_index_id and extra_data columns

ALTER TABLE os_minute_windows ADD COLUMN timeline_index_id INTEGER;
ALTER TABLE os_minute_windows ADD COLUMN extra_data TEXT;

ALTER TABLE browser_minute_windows ADD COLUMN timeline_index_id INTEGER;
ALTER TABLE browser_minute_windows ADD COLUMN extra_data TEXT;

ALTER TABLE calendar_events ADD COLUMN extra_data TEXT;
