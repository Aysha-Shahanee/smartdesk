#!/usr/bin/env python3
"""
Integration test for the new VS Code session/snapshot architecture.

This test simulates:
1. First POST request (periodic snapshot)
2. Second POST request (another periodic snapshot)
3. Final POST request (session ends)

Verifies:
- vscode_sessions gets upserted correctly
- vscode_session_snapshots maintains all snapshots
- is_final flag is set correctly
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.vscode import VSCodePayload, VSCodeSessionData
from app.services.vscode_service import VSCodeService
from app.core.database import SessionLocal
from app.models.db_models import VSCodeSession, VSCodeSessionSnapshot

# Test data
TEST_EVENT_ID = "evt_test_12345"
TEST_PROJECT = "/home/user/my-project"
TEST_FILE = "src/main.py"


def simulate_extension_post(snapshot_num: int, is_final: bool = False) -> VSCodePayload:
    """Create a simulated POST request from the VS Code extension."""
    
    active_sec = 30 * snapshot_num
    edit_count = 5 * snapshot_num
    
    end_time = None
    duration_sec = None
    if is_final:
        end_time = (datetime.now() + timedelta(seconds=60)).isoformat(timespec='milliseconds')
        duration_sec = 60
    
    data = VSCodeSessionData(
        event_id=TEST_EVENT_ID,
        project_name="my-project",
        project_path=TEST_PROJECT,
        file_path=TEST_FILE,
        language="python",
        workspace_name="Python Dev",
        repo_id="repo_xyz",
        git_branch="main",
        start_time=datetime.now().isoformat(timespec='milliseconds'),
        end_time=end_time,
        duration_seconds=duration_sec,
        active_seconds=active_sec,
        idle_seconds=30 - active_sec if active_sec < 30 else 0,
        edit_count=edit_count,
        save_count=1 if snapshot_num % 2 == 0 else 0,
        debug_runs=0,
        terminal_commands=0,
        approx_lines_added=edit_count * 2,
        approx_lines_removed=0,
        approx_chars_added=edit_count * 20,
        approx_chars_removed=0
    )
    
    payload = VSCodePayload(
        timestamp=datetime.now(),
        event_type="vscode_session",
        data=data
    )
    
    return payload


def test_workflow():
    """Run the complete test workflow."""
    
    print("=" * 70)
    print("VS Code Session/Snapshot Integration Test")
    print("=" * 70)
    
    service = VSCodeService()
    db = SessionLocal()
    
    try:
        # Clean up any existing test data
        print("\n[SETUP] Cleaning up existing test data...")
        existing_sessions = db.query(VSCodeSession).filter(
            VSCodeSession.event_id == TEST_EVENT_ID
        ).all()
        for session in existing_sessions:
            db.delete(session)
        
        existing_snapshots = db.query(VSCodeSessionSnapshot).filter(
            VSCodeSessionSnapshot.event_id == TEST_EVENT_ID
        ).all()
        for snapshot in existing_snapshots:
            db.delete(snapshot)
        
        db.commit()
        print("✓ Test data cleaned up")
        # Test 1: First periodic snapshot
        print("\n[TEST 1] First periodic snapshot (30s mark)")
        print("-" * 70)
        payload1 = simulate_extension_post(snapshot_num=1, is_final=False)
        result1 = service.process_and_save(payload1)
        print(f"Result: {result1}")
        
        # Clear session cache to ensure fresh queries from DB
        db.expunge_all()
        
        # Verify state after first request
        session_count = db.query(VSCodeSession).filter(
            VSCodeSession.event_id == TEST_EVENT_ID
        ).count()
        snapshot_count = db.query(VSCodeSessionSnapshot).filter(
            VSCodeSessionSnapshot.event_id == TEST_EVENT_ID
        ).count()
        print(f"Sessions: {session_count}, Snapshots: {snapshot_count}")
        assert session_count == 1, "Should have 1 session"
        assert snapshot_count == 1, "Should have 1 snapshot"
        
        session1 = db.query(VSCodeSession).filter(
            VSCodeSession.event_id == TEST_EVENT_ID
        ).first()
        print(f"Session active_sec: {session1.active_sec}, is_final: {session1.is_final}")
        assert session1.active_sec == 30, "Session active_sec should be 30"
        assert session1.is_final == 0, "Session should not be final yet"
        assert session1.end_time is None, "Session end_time should be None"
        print("✓ Test 1 passed")
        
        # Test 2: Second periodic snapshot
        print("\n[TEST 2] Second periodic snapshot (60s mark)")
        print("-" * 70)
        payload2 = simulate_extension_post(snapshot_num=2, is_final=False)
        result2 = service.process_and_save(payload2)
        print(f"Result: {result2}")
        
        # Clear session cache to ensure fresh queries from DB
        db.expunge_all()
        
        # Verify state after second request
        session_count = db.query(VSCodeSession).filter(
            VSCodeSession.event_id == TEST_EVENT_ID
        ).count()
        snapshot_count = db.query(VSCodeSessionSnapshot).filter(
            VSCodeSessionSnapshot.event_id == TEST_EVENT_ID
        ).count()
        print(f"Sessions: {session_count}, Snapshots: {snapshot_count}")
        assert session_count == 1, "Should still have 1 session (upserted, not new)"
        assert snapshot_count == 2, "Should have 2 snapshots now"
        
        session2 = db.query(VSCodeSession).filter(
            VSCodeSession.event_id == TEST_EVENT_ID
        ).first()
        print(f"Session active_sec: {session2.active_sec}, edit_count: {session2.edit_count}")
        assert session2.active_sec == 60, "Session active_sec should be updated to 60"
        assert session2.edit_count == 10, "Session edit_count should be 10"
        assert session2.is_final == 0, "Session should not be final yet"
        assert session2.end_time is None, "Session end_time should still be None"
        print("✓ Test 2 passed")
        
        # Test 3: Final snapshot (session ends)
        print("\n[TEST 3] Final snapshot (session ends)")
        print("-" * 70)
        payload3 = simulate_extension_post(snapshot_num=3, is_final=True)
        result3 = service.process_and_save(payload3)
        print(f"Result: {result3}")
        
        # Clear session cache to ensure fresh queries from DB
        db.expunge_all()
        
        # Verify state after final request
        session_count = db.query(VSCodeSession).filter(
            VSCodeSession.event_id == TEST_EVENT_ID
        ).count()
        snapshot_count = db.query(VSCodeSessionSnapshot).filter(
            VSCodeSessionSnapshot.event_id == TEST_EVENT_ID
        ).count()
        print(f"Sessions: {session_count}, Snapshots: {snapshot_count}")
        assert session_count == 1, "Should still have 1 session"
        assert snapshot_count == 3, "Should have 3 snapshots now"
        
        session3 = db.query(VSCodeSession).filter(
            VSCodeSession.event_id == TEST_EVENT_ID
        ).first()
        print(f"Session active_sec: {session3.active_sec}, is_final: {session3.is_final}, end_time: {session3.end_time}")
        assert session3.active_sec == 90, "Session active_sec should be 90"
        assert session3.is_final == 1, "Session should be final"
        assert session3.end_time is not None, "Session end_time should be set"
        assert session3.duration_sec == 60, "Session duration_sec should be set"
        print("✓ Test 3 passed")
        
        # Summary
        print("\n" + "=" * 70)
        print("All tests passed! ✓")
        print("=" * 70)
        print("\nFinal state:")
        print(f"  vscode_sessions: 1 row (event_id={TEST_EVENT_ID}, is_final=1)")
        print(f"  vscode_session_snapshots: 3 rows (periodic + final updates)")
        print(f"\nKey behaviors verified:")
        print(f"  ✓ First POST creates session row")
        print(f"  ✓ Subsequent POSTs update the same session row (no duplicates)")
        print(f"  ✓ Final POST sets is_final=1 and end_time")
        print(f"  ✓ All POSTs create snapshot rows (3 snapshots captured)")
        
    finally:
        db.close()


if __name__ == "__main__":
    try:
        test_workflow()
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
