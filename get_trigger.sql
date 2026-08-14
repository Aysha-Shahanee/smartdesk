import sqlite3
conn = sqlite3.connect('backend\\smartdesk.db')
c = conn.cursor()
c.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='trg_activity_segments_insert'")
print(c.fetchone()[0])