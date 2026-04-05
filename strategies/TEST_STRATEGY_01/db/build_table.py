import sqlite3
from pathlib import Path

DB = "/root/apex-system/storage/db/sqlite/apex.db"
SCHEMA = Path("/root/apex-system/strategies/TEST_STRATEGY_01/db/schema.sql").read_text(encoding="utf-8")

conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.executescript(SCHEMA)
conn.commit()
conn.close()

print("OK: APEX_STRATEGY_TEST_STRATEGY_01 created")
