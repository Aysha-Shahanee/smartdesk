# Calendar Auth/Status Update Plan (Pre-Implementation)

## Current Logic (Observed)
- Backend runs calendar sync job on startup and uses OAuth tokens stored on disk.
- Calendar auth uses `/api/v1/calendar/auth/start` and callback at `/api/v1/calendar/auth/callback`.
- Refresh token failure raises `invalid_grant` and skips sync, but there is no explicit status endpoint for reconnect UX.
- Calendar events are stored in `calendar_events` with `event_id`, `title`, `start_time`, `end_time`, `timezone`, `duration_sec`, `status`, `extra_data`, `source`, `created_at`, `updated_at`.

## Logic Updates Needed
1. **Status endpoint**
   - Add `GET /api/v1/calendar/auth/status`.
   - Report `authorized`, `status`, `message`, `requires_reconnect`, and `auth_url` when needed.

2. **Invalid refresh handling**
   - When refresh fails with `invalid_grant`, mark auth as invalid and clear token file.
   - Log a clear warning and skip sync without crashing.

3. **Manual sync endpoint**
   - Ensure `POST /api/v1/calendar/sync` returns a clear success or reconnect-required response.

4. **Calendar sync job safety**
   - If unauthorized, skip sync and log: `[Calendar Sync] Calendar not authorized. Reconnect required.`
   - Do not delete existing `calendar_events` rows.

5. **Dashboard UX support**
   - Dashboard should call status endpoint and show reconnect/sync actions accordingly.

## Files Likely to Change
- `backend/app/services/calendar_auth_service.py`
- `backend/app/services/calendar_sync_service.py`
- `backend/app/services/calendar_sync_job.py`
- `backend/app/routes/calendar.py`
- `backend/app/core/config.py` (if status/auth helpers need config values)
- `README.md` (add calendar reconnect guidance)

## Safety Constraints
- Do not modify minute-window ingestion endpoints or any non-calendar routes.
- Keep `calendar_events` table and existing data intact.
- Avoid changes to OS collector and dashboard session logic.
