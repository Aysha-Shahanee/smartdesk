#!/usr/bin/env python3
"""
Migration script to create or upgrade VS Code tracking tables.

This script handles:
1. Creating new vscode_sessions and vscode_session_snapshots tables
2. Optionally populating them from existing vscode_signals data
3. Preserving backward compatibility with vscode_signals table

Usage:
    python scripts/migrate_vscode_tables.py [--migrate-data]
    
    --migrate-data: Also migrate existing data from vscode_signals to new tables
                    (optional, only useful if you have existing vscode_signals data)
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import engine, Base
# Explicitly import all models to ensure they're registered with Base
from app.models.db_models import (
    VSCodeSession, 
    VSCodeSessionSnapshot, 
    VSCodeRecord,
    OSSignalRecord,
    BrowserRecord,
    CalendarRecord
)
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_tables():
    """Create all new VS Code tables if they don't exist."""
    logger.info("Creating VS Code tables...")
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    logger.info("✓ Tables created successfully")


def check_table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def migrate_data():
    """
    Migrate existing data from vscode_signals to new tables.
    
    This function:
    1. Reads all records from vscode_signals
    2. Groups them by event_id
    3. Creates session rows in vscode_sessions (one per event_id)
    4. Creates snapshot rows in vscode_session_snapshots (one per original signal)
    """
    if not check_table_exists("vscode_signals"):
        logger.warning("vscode_signals table does not exist, skipping data migration")
        return
    
    logger.info("Starting data migration from vscode_signals...")
    
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        # Query all vscode_signals records
        all_signals = db.query(VSCodeRecord).all()
        
        if not all_signals:
            logger.info("No data in vscode_signals to migrate")
            return
        
        logger.info(f"Found {len(all_signals)} records in vscode_signals")
        
        # Group by event_id
        events_by_id = {}
        for signal in all_signals:
            event_data = signal.data or {}
            event_id = event_data.get("event_id")
            
            if not event_id:
                logger.warning(f"Signal {signal.id} has no event_id, skipping")
                continue
            
            if event_id not in events_by_id:
                events_by_id[event_id] = []
            
            events_by_id[event_id].append(signal)
        
        logger.info(f"Grouped signals into {len(events_by_id)} unique sessions")
        
        # Process each session
        migrated_sessions = 0
        migrated_snapshots = 0
        
        for event_id, signals in events_by_id.items():
            # Sort signals by timestamp to get last one for session metadata
            signals_sorted = sorted(signals, key=lambda s: s.timestamp)
            last_signal = signals_sorted[-1]
            last_data = last_signal.data or {}
            
            # Check if this session already exists
            existing = db.query(VSCodeSession).filter(
                VSCodeSession.event_id == event_id
            ).first()
            
            if existing:
                logger.debug(f"Session {event_id} already exists, skipping migration")
                continue
            
            # Create session row from last signal (final state)
            is_final = 1 if last_data.get("is_final") else 0
            
            session = VSCodeSession(
                event_id=event_id,
                user_id=None,
                file_path=last_data.get("file_path", "unknown"),
                file_name=last_data.get("file_path", "unknown").split("/")[-1],
                language=last_data.get("language"),
                project_path=last_data.get("project_path", "unknown"),
                project_name=last_data.get("project_name"),
                workspace_name=last_data.get("workspace_name"),
                repo_id=last_data.get("repo_id"),
                git_branch=last_data.get("git_branch"),
                start_time=signals_sorted[0].timestamp,
                end_time=last_signal.timestamp if is_final else None,
                duration_sec=last_data.get("duration_seconds"),
                active_sec=last_data.get("active_seconds", 0),
                idle_sec=last_data.get("idle_seconds", 0),
                edit_count=last_data.get("edit_count", 0),
                save_count=last_data.get("save_count", 0),
                debug_run_count=last_data.get("debug_runs", 0),
                terminal_command_count=last_data.get("terminal_commands", 0),
                approx_lines_added=last_data.get("approx_lines_added", 0),
                approx_lines_removed=last_data.get("approx_lines_removed", 0),
                approx_chars_added=last_data.get("approx_chars_added", 0),
                approx_chars_removed=last_data.get("approx_chars_removed", 0),
                is_final=is_final,
                created_at=signals_sorted[0].timestamp,
                updated_at=last_signal.timestamp
            )
            db.add(session)
            migrated_sessions += 1
            
            # Create snapshot rows from all signals
            for signal in signals_sorted:
                data = signal.data or {}
                snapshot = VSCodeSessionSnapshot(
                    event_id=event_id,
                    user_id=None,
                    snapshot_time=signal.timestamp,
                    file_path=data.get("file_path"),
                    language=data.get("language"),
                    active_sec=data.get("active_seconds", 0),
                    idle_sec=data.get("idle_seconds", 0),
                    edit_count=data.get("edit_count", 0),
                    save_count=data.get("save_count", 0),
                    debug_run_count=data.get("debug_runs", 0),
                    terminal_command_count=data.get("terminal_commands", 0),
                    approx_lines_added=data.get("approx_lines_added", 0),
                    approx_lines_removed=data.get("approx_lines_removed", 0),
                    approx_chars_added=data.get("approx_chars_added", 0),
                    approx_chars_removed=data.get("approx_chars_removed", 0),
                    is_final=1 if data.get("is_final") else 0,
                    created_at=signal.timestamp
                )
                db.add(snapshot)
                migrated_snapshots += 1
        
        db.commit()
        logger.info(f"✓ Migration complete: {migrated_sessions} sessions, {migrated_snapshots} snapshots")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Migration failed: {str(e)}")
        raise
    finally:
        db.close()


def print_table_stats():
    """Print statistics about the VS Code tables."""
    logger.info("\n--- Table Statistics ---")
    
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        if check_table_exists("vscode_sessions"):
            count = db.query(VSCodeSession).count()
            logger.info(f"vscode_sessions: {count} rows")
        
        if check_table_exists("vscode_session_snapshots"):
            count = db.query(VSCodeSessionSnapshot).count()
            logger.info(f"vscode_session_snapshots: {count} rows")
        
        if check_table_exists("vscode_signals"):
            count = db.query(VSCodeRecord).count()
            logger.info(f"vscode_signals (legacy): {count} rows")
    
    finally:
        db.close()


def main():
    """Main migration entry point."""
    migrate_data_flag = "--migrate-data" in sys.argv
    
    logger.info("=" * 60)
    logger.info("VS Code Tables Migration")
    logger.info("=" * 60)
    
    try:
        # Step 1: Create tables
        create_tables()
        
        # Step 2: Optionally migrate data
        if migrate_data_flag:
            logger.info("\nData migration requested...")
            migrate_data()
        else:
            logger.info("\nSkipping data migration (use --migrate-data to enable)")
        
        # Step 3: Print stats
        print_table_stats()
        
        logger.info("\n" + "=" * 60)
        logger.info("✓ Migration complete!")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"\n✗ Migration failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
