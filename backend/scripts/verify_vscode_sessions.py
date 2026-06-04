"""Script to verify VS Code session tracking database updates and payload mapping.

This runs inside the application virtual environment and tests:
- Session STARTED and STATE event ingestion.
- Mapping of new session-level fields to SQLite.
- Prevention of duplicate session records for same instance ID.
- Keeping foreground active file separate from edited files.
"""

import os
import sys
import json
from datetime import datetime

# Set up python path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models.db import VSCodeSessionRecord

# Disable background jobs for test runner to avoid thread initialization
# (lifespan manager starts background threads)
client = TestClient(app)


def verify_vscode_tracking():
    print("=== Starting VS Code Session Tracking Verification ===")
    
    # 1. Clean up any existing records for our test instance_id
    test_instance_id = "test-verification-session-12345"
    db = SessionLocal()
    try:
        db.query(VSCodeSessionRecord).filter(
            VSCodeSessionRecord.instance_id == test_instance_id
        ).delete()
        db.commit()
    finally:
        db.close()

    # Timezone ISO format (using Asia/Colombo +05:30 as requested)
    timestamp_started = "2026-06-04T01:30:00+05:30"
    timestamp_state = "2026-06-04T01:31:00+05:30"
    timestamp_update = "2026-06-04T01:32:00+05:30"

    print("\nSending session STARTED event...")
    start_payload = {
        "user_id": "local_user",
        "event": "started",
        "instance_id": test_instance_id,
        "timestamp": timestamp_started,
        "process_id": 9999,
        "trigger": "activation",
        "workspace_name": "smartdesk",
        "project_path": "d:/software project-2nd year/implementation/data collection layer"
    }
    
    res = client.post("/api/v1/ingest/vscode/event", json=start_payload)
    assert res.status_code == 200, f"Start failed: {res.text}"
    print("Session STARTED event accepted.")

    # Validate that session record is created
    db = SessionLocal()
    try:
        records = db.query(VSCodeSessionRecord).filter(
            VSCodeSessionRecord.instance_id == test_instance_id
        ).all()
        assert len(records) == 1, f"Expected 1 session record, found {len(records)}"
        record = records[0]
        assert record.session_end is None, "Session should be active/open"
        assert record.session_start == timestamp_started, f"Expected {timestamp_started}, got {record.session_start}"
    finally:
        db.close()

    print("\nSending first session STATE event with active file and edits...")
    
    edited_files = [
        {
            "file_path": "vscode-extension/extension.js",
            "file_name": "extension.js",
            "language": "javascript",
            "edit_count": 8,
            "save_count": 1,
            "lines_added": 70,
            "lines_deleted": 10
        },
        {
            "file_path": "backend/app/routes/browser.py",
            "file_name": "browser.py",
            "language": "python",
            "edit_count": 5,
            "save_count": 2,
            "lines_added": 30,
            "lines_deleted": 8
        },
        {
            "file_path": "backend/app/services/calendar_service.py",
            "file_name": "calendar_service.py",
            "language": "python",
            "edit_count": 5,
            "save_count": 0,
            "lines_added": 0,
            "lines_deleted": 0
        }
    ]
    
    languages = {
        "javascript": {
            "edit_count": 8,
            "lines_added": 70,
            "lines_deleted": 10
        },
        "python": {
            "edit_count": 10,
            "lines_added": 30,
            "lines_deleted": 8
        }
    }

    state_payload = {
        "user_id": "local_user",
        "event": "state",
        "instance_id": test_instance_id,
        "timestamp": timestamp_state,
        "process_id": 9999,
        "trigger": "heartbeat",
        "workspace_name": "smartdesk",
        "project_path": "d:/software project-2nd year/implementation/data collection layer",
        # Active foreground document (context only)
        "active_file_path": "d:/software project-2nd year/implementation/data collection layer/README.md",
        "active_file_name": "README.md",
        "active_language": "markdown",
        # New aggregation columns
        "edited_file_count": len(edited_files),
        "changed_file_count": len(edited_files),
        "total_edit_count": 18,
        "total_save_count": 3,
        "total_lines_added": 100,
        "total_lines_deleted": 18,
        "dominant_language": "javascript",  # 70+10 lines is greater than 30+8 lines
        "languages_json": languages,
        "edited_files_json": edited_files
    }

    res = client.post("/api/v1/ingest/vscode/event", json=state_payload)
    assert res.status_code == 200, f"State failed: {res.text}"
    print("Session STATE event accepted.")

    # Assert database mapping values
    db = SessionLocal()
    try:
        records = db.query(VSCodeSessionRecord).filter(
            VSCodeSessionRecord.instance_id == test_instance_id
        ).all()
        assert len(records) == 1, "Duplicate session row was created! Expected only 1 row per instance_id."
        record = records[0]
        
        # Verify foreground active fields remain correct
        assert record.active_file_name == "README.md", "active_file_name should match"
        assert record.active_language == "markdown", "active_language should match"
        assert record.active_file_path == "d:/software project-2nd year/implementation/data collection layer/README.md", "active_file_path should match"
        
        # Verify new fields
        assert record.edited_file_count == 3, f"Expected 3 edited files, got {record.edited_file_count}"
        assert record.changed_file_count == 3, f"Expected 3 changed files, got {record.changed_file_count}"
        assert record.total_edit_count == 18, f"Expected total_edit_count 18, got {record.total_edit_count}"
        assert record.total_save_count == 3, f"Expected total_save_count 3, got {record.total_save_count}"
        assert record.total_lines_added == 100, f"Expected total_lines_added 100, got {record.total_lines_added}"
        assert record.total_lines_deleted == 18, f"Expected total_lines_deleted 18, got {record.total_lines_deleted}"
        assert record.dominant_language == "javascript", f"Expected dominant_language javascript, got {record.dominant_language}"
        
        # JSON validation
        saved_languages = json.loads(record.languages_json)
        assert saved_languages["javascript"]["edit_count"] == 8
        assert saved_languages["python"]["lines_added"] == 30
        
        saved_files = json.loads(record.edited_files_json)
        assert len(saved_files) == 3
        assert saved_files[0]["file_name"] == "extension.js"
        assert saved_files[1]["language"] == "python"
        
        print("Database assertions verified successfully (Active vs. Edited files are correct).")
    finally:
        db.close()

    print("\nSending second session STATE event (updating stats)...")
    # Add one more file edit to show it updates existing row correctly
    edited_files.append({
        "file_path": "backend/app/models/db/sessions.py",
        "file_name": "sessions.py",
        "language": "python",
        "edit_count": 2,
        "save_count": 1,
        "lines_added": 12,
        "lines_deleted": 0
    })
    
    languages["python"]["edit_count"] += 2
    languages["python"]["lines_added"] += 12

    state_update_payload = {
        "user_id": "local_user",
        "event": "state",
        "instance_id": test_instance_id,
        "timestamp": timestamp_update,
        "process_id": 9999,
        "trigger": "heartbeat",
        "workspace_name": "smartdesk",
        "project_path": "d:/software project-2nd year/implementation/data collection layer",
        # Active foreground document changes to browser.py
        "active_file_path": "d:/software project-2nd year/implementation/data collection layer/backend/app/routes/browser.py",
        "active_file_name": "browser.py",
        "active_language": "python",
        # Updated metrics
        "edited_file_count": len(edited_files),
        "changed_file_count": len(edited_files),
        "total_edit_count": 20,
        "total_save_count": 4,
        "total_lines_added": 112,
        "total_lines_deleted": 18,
        "dominant_language": "javascript",  # javascript: 80, python: 50
        "languages_json": languages,
        "edited_files_json": edited_files
    }

    res = client.post("/api/v1/ingest/vscode/event", json=state_update_payload)
    assert res.status_code == 200, f"State update failed: {res.text}"
    print("Session STATE update accepted.")

    # Assert database state after update
    db = SessionLocal()
    try:
        records = db.query(VSCodeSessionRecord).filter(
            VSCodeSessionRecord.instance_id == test_instance_id
        ).all()
        assert len(records) == 1, "Duplicate row created on state update! Expected 1 row."
        record = records[0]
        
        # Verify foreground active fields updated
        assert record.active_file_name == "browser.py", "active_file_name should have updated"
        assert record.active_language == "python", "active_language should have updated"
        
        # Verify new fields updated
        assert record.edited_file_count == 4, f"Expected 4 edited files, got {record.edited_file_count}"
        assert record.total_edit_count == 20, f"Expected total_edit_count 20, got {record.total_edit_count}"
        assert record.total_lines_added == 112, f"Expected total_lines_added 112, got {record.total_lines_added}"
        
        saved_files = json.loads(record.edited_files_json)
        assert len(saved_files) == 4
        assert saved_files[3]["file_name"] == "sessions.py"
        
        print("Database assertions verified successfully on session update.")
    finally:
        db.close()

    print("\nSending third session STATE event (simulating Copilot background file creation)...")
    # Background edit scenario:
    # - active_file_name remains extension.js (foreground)
    # - a new file is created on disk and captured via filesystem watcher: docs/background_test.md
    
    timestamp_background = "2026-06-04T01:33:00+05:30"
    background_test_lines = 10
    
    # We add docs/background_test.md to edited_files
    edited_files.append({
        "file_path": "docs/background_test.md",
        "file_name": "background_test.md",
        "language": "markdown",
        "edit_count": 1,
        "save_count": 0,
        "lines_added": background_test_lines,
        "lines_deleted": 0,
        "change_source": "filesystem_created"
    })
    
    if "markdown" not in languages:
        languages["markdown"] = {"edit_count": 0, "lines_added": 0, "lines_deleted": 0}
    languages["markdown"]["edit_count"] += 1
    languages["markdown"]["lines_added"] += background_test_lines

    background_payload = {
        "user_id": "local_user",
        "event": "state",
        "instance_id": test_instance_id,
        "timestamp": timestamp_background,
        "process_id": 9999,
        "trigger": "heartbeat",
        "workspace_name": "smartdesk",
        "project_path": "d:/software project-2nd year/implementation/data collection layer",
        # Foreground active file remains extension.js
        "active_file_path": "d:/software project-2nd year/implementation/data collection layer/vscode-extension/extension.js",
        "active_file_name": "extension.js",
        "active_language": "javascript",
        # Updated metrics
        "edited_file_count": len(edited_files),
        "changed_file_count": len(edited_files),
        "total_edit_count": 21,
        "total_save_count": 4,
        "total_lines_added": 112 + background_test_lines,
        "total_lines_deleted": 18,
        "dominant_language": "javascript",
        "languages_json": languages,
        "edited_files_json": edited_files
    }

    res = client.post("/api/v1/ingest/vscode/event", json=background_payload)
    assert res.status_code == 200, f"Background test failed: {res.text}"
    print("Background STATE update accepted.")

    db = SessionLocal()
    try:
        records = db.query(VSCodeSessionRecord).filter(
            VSCodeSessionRecord.instance_id == test_instance_id
        ).all()
        assert len(records) == 1, "Duplicate row created on background update! Expected 1 row."
        record = records[0]
        
        # Verify active foreground remains extension.js
        assert record.active_file_name == "extension.js", f"Expected active_file_name extension.js, got {record.active_file_name}"
        assert record.active_language == "javascript", "active_language should be javascript"
        
        # Verify new fields
        assert record.edited_file_count == 5, f"Expected 5 edited files, got {record.edited_file_count}"
        assert record.total_lines_added == 112 + background_test_lines, f"Expected total_lines_added {112 + background_test_lines}, got {record.total_lines_added}"
        
        saved_files = json.loads(record.edited_files_json)
        assert len(saved_files) == 5
        assert saved_files[4]["file_name"] == "background_test.md"
        assert saved_files[4]["change_source"] == "filesystem_created"
        
        print("Database assertions verified successfully for Copilot background file edits.")
    finally:
        # Cleanup
        db.query(VSCodeSessionRecord).filter(
            VSCodeSessionRecord.instance_id == test_instance_id
        ).delete()
        db.commit()
        db.close()

    print("\n=== All Verification Checks Passed Successfully! ===")


if __name__ == "__main__":
    verify_vscode_tracking()
