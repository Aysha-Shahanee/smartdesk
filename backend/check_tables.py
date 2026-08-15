import sqlite3
import os
print('Looking for database file...')
db_path = '../smartdesk.db'
print(f'Checking: {db_path}')
print(f'Exists: {os.path.exists(db_path)}')
if os.path.exists(db_path):
    print(f'Size: {os.path.getsize(db_path)} bytes')
conn = sqlite3.connect(db_path)
print('Connected to database')
print('Checking sqlite_master:')
cursor = conn.execute("SELECT * FROM sqlite_master")
rows = list(cursor)
print(f'Found {len(rows)} items in sqlite_master')
for row in rows[:10]:  # Show first 10
    print(f'  {row}')
