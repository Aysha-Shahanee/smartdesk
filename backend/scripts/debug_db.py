#!/usr/bin/env python3
"""Debug script to see what's in the database."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.core.database import SessionLocal
from app.models.db_models import VSCodeSession, VSCodeSessionSnapshot

db = SessionLocal()

# Get all sessions
sessions = db.query(VSCodeSession).filter(
    VSCodeSession.event_id == "evt_test_12345"
).all()

print(f"Found {len(sessions)} session(s) for evt_test_12345:")
for session in sessions:
    print(f"  ID: {session.id}")
    print(f"  active_sec: {session.active_sec}")
    print(f"  edit_count: {session.edit_count}")
    print(f"  updated_at: {session.updated_at}")
    print()

# Get all snapshots
snapshots = db.query(VSCodeSessionSnapshot).filter(
    VSCodeSessionSnapshot.event_id == "evt_test_12345"
).all()

print(f"Found {len(snapshots)} snapshot(s) for evt_test_12345:")
for i, snap in enumerate(snapshots):
    print(f"  Snapshot {i+1}:")
    print(f"    active_sec: {snap.active_sec}")
    print(f"    edit_count: {snap.edit_count}")
    print(f"    snapshot_time: {snap.snapshot_time}")

db.close()
