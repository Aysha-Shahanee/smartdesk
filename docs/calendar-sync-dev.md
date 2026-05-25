# Calendar Sync Development Plan

## Goal
Sync Google Calendar events into the `calendar_events` table from the backend, using one-time OAuth consent and automatic token refresh. Poll every 10 minutes for changes.

## Scope
- Backend-only sync (no VS Code extension).
- Google Calendar API (primary calendar by default).
- Store events in SQLite (`backend/smartdesk.db`).

## Data Mapping
Map Google Calendar fields to DB columns:
- `event_id`: Google event id (stable key for upsert)
- `title`: event summary (fallback to "(no title)")
- `start_time`: event start (ISO8601)
- `end_time`: event end (ISO8601)
- `timezone`: event start time zone or calendar time zone
- `duration_sec`: end - start (seconds)
- `status`: confirmed | tentative | cancelled
- `attendees_count`: len(attendees) (0 if missing)
- `is_recurring`: 1 if `recurrence` exists, else 0
- `extra_data`: JSON blob for optional fields (location, organizer, hangout link)
- `source`: "google_calendar"
- `created_at`, `updated_at`: ISO8601 UTC
- `user_id`: default `local_user` unless overridden

## Dependencies
- `google-api-python-client`
- `google-auth`
- `google-auth-oauthlib`
- `google-auth-httplib2`

## OAuth Flow (Local Web)
1. User visits `GET /api/v1/calendar/auth/start`.
2. Backend opens OAuth flow (authorization URL) and returns it to the user.
3. User completes consent in browser.
4. Google redirects to `GET /api/v1/calendar/auth/callback`.
5. Backend stores refresh token for future use.
6. Subsequent syncs refresh access token automatically; user should not re-consent unless the token is revoked.

## Token Storage
- Store OAuth tokens in a local file or table.
- Recommended: a new table `calendar_auth` (user_id, refresh_token, scope, created_at).
- Never commit tokens to git.
### Token Lifetime Notes
- Access tokens are short-lived and will be refreshed automatically.
- Refresh tokens should remain valid unless revoked or invalidated; no repeated user consent expected.

## Sync Strategy
- Initial sync: last 30 days to next 30 days.
- Incremental sync: use `syncToken` (if present) or `updatedMin`.
- Job interval: every 10 minutes.
### Update Behavior
- Always upsert by `user_id + event_id`.
- If an event changes (title, time, attendees, etc.), update the existing row instead of inserting a new one.

## New Backend Components
- `app/services/calendar_client.py`
  - Builds Google API client with refresh token.
  - Handles token refresh automatically.
- `app/services/calendar_sync.py`
  - `sync_events(user_id, time_min, time_max)`
  - Upsert events into `calendar_events`.
  - Persist and reuse `syncToken`.
- `app/repositories/calendar_event_repository.py`
  - Upsert by `user_id + event_id` (update existing rows when details change).
  - Mark cancelled events as `status = "cancelled"`.
- `app/services/calendar_sync_job.py`
  - Background job every 10 minutes.
  - Calls `calendar_sync.sync_events`.

## API Endpoints
- `GET /api/v1/calendar/auth/start`
  - Returns OAuth URL.
- `GET /api/v1/calendar/auth/callback`
  - Stores refresh token and returns success.
- `POST /api/v1/calendar/sync`
  - Manual sync trigger (admin/debug only).
- `GET /api/v1/calendar/status`
  - Returns last sync time and token presence.

## Error Handling
- If refresh token is missing: return 401 with guidance.
- If syncToken is invalid: retry with full sync.
- Rate limit: backoff and log warning.
- If event has no end time: treat as 30-minute default or skip (decide).

## Tests
- Unit tests for mapping and upsert logic.
- Integration test for sync flow using mocked API responses.
- Manual test: trigger sync and inspect `calendar_events` table.

## Manual Verification
1. Start backend.
2. Visit auth start URL and complete consent.
3. Trigger manual sync.
4. Confirm rows appear in `calendar_events`.
5. Add new event in Google Calendar.
6. Wait 10 minutes or call manual sync.
7. Confirm new event is inserted or updated.

## Security Notes
- Keep OAuth client secret out of source control.
- Store secrets in `backend/.env` (ignored by git).
- Limit scopes to read-only calendar access.
