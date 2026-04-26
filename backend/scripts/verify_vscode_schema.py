#!/usr/bin/env python3
"""Quick verification of new VS Code tables."""

from sqlalchemy import inspect, create_engine

engine = create_engine('sqlite:///./smartdesk.db')
inspector = inspect(engine)
tables = inspector.get_table_names()

print("Tables in database:")
for table in sorted(tables):
    print(f"  - {table}")

print("\nvscode_sessions columns:")
if 'vscode_sessions' in tables:
    for col in inspector.get_columns('vscode_sessions'):
        print(f"  {col['name']}: {col['type']}")
else:
    print("  (table not found)")

print("\nvscode_session_snapshots columns:")
if 'vscode_session_snapshots' in tables:
    for col in inspector.get_columns('vscode_session_snapshots'):
        print(f"  {col['name']}: {col['type']}")
else:
    print("  (table not found)")
