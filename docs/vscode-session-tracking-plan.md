# VS Code Session Tracking Update Plan

## Scope
- Keep VS Code tracking session-based (no minute windows).
- Update `vscode-extension` only.
- Backend continues using `POST /api/v1/ingest/vscode/event` and `vscode_sessions`.
- No changes to OS/browser/calendar collectors or activity_session_summary logic except mapping new VS Code fields.

## Current VS Code Extension Logic (Observed)
- Session-based events: `started`, `state`, `ended`.
- Foreground context uses `vscode.window.activeTextEditor`.
- Edit tracking uses `onDidChangeTextDocument` and counts all changes, but only updates generic counters; edited file details are not tracked separately.
- Per-file change info is stored in `extra_data.changed_files` but reflects file events (create/modify/delete) and is not specific to actual edit counts/lines.

## Problems to Fix
- Background edits (e.g., Copilot edits) are not recorded as edited files.
- Foreground file context is mixed with actual edited files.

## Target Data Model Changes (Backend)
Add columns to `vscode_sessions` for session totals and summaries:
- `foreground_file_path`
- `foreground_file_name`
- `foreground_language`
- `edited_file_count`
- `changed_file_count`
- `total_edit_count`
- `total_save_count`
- `total_lines_added`
- `total_lines_deleted`
- `dominant_language`
- `languages_json`
- `edited_files_json`

Note:
- Keep existing `active_file_path`, `active_file_name`, `active_language` only if renaming is risky; otherwise rename to `foreground_*` with a migration.
- `terminal_command_count`, `debug_run_count`, and `foreground_sec` were removed from `ide_sessions` (migration 0004) — no longer collected or reported.

## Extension Payload Changes (Session-Based)
Add to VS Code session payload:
- `foreground_file_path`, `foreground_file_name`, `foreground_language`
- `edited_file_count`, `changed_file_count`
- `total_edit_count`, `total_save_count`
- `total_lines_added`, `total_lines_deleted`
- `dominant_language`, `languages_json`, `edited_files_json`

Keep:
- `active_file_path`, `active_file_name`, `active_language` if columns remain; document as foreground context.

## Tracking Rules
1. Foreground file:
   - Use `vscode.window.activeTextEditor` only for foreground context.

2. Edited files:
   - Use `onDidChangeTextDocument(event)`.
   - Always use `event.document.uri.fsPath`, even if not active.
   - Track per-file edit_count, save_count, lines_added, lines_deleted.

3. Totals:
   - `total_edit_count` increments once per change event.
   - `total_lines_added` / `total_lines_deleted` estimated from `event.contentChanges`.
   - `total_save_count` increments on `onDidSaveTextDocument`.

4. Per-language totals:
   - Aggregate edits/lines by `event.document.languageId`.
   - `dominant_language` determined by highest `lines_added + lines_deleted` (or by edit_count if ties).

5. Reset behavior:
   - Reset per-session edited-file maps on `started` and after `ended`.

## Backend Updates
- Pydantic schema updates for new VS Code fields in session payload.
- Session coordinator applies new fields to `vscode_sessions`.
- Migration to add columns to `vscode_sessions`.
- Repository/service updates to use new totals in dashboards if applicable.

## Verification Script
Create or update `scripts/verify_vscode_sessions.py` to:
- Upsert a session with foreground README.md and edited files in other paths.
- Confirm one row per session_id.
- Confirm `edited_files_json` and totals are stored.

## Documentation
Update README and architecture docs to state:
- VS Code tracking is session-based.
- Foreground file is context only.
- Actual work uses edited_files_json and totals.
