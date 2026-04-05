import sqlite3

DB_PATH = "/root/apex-system/storage/db/sqlite/apex.db"

NEW_COLUMNS = [
    "scan_run_id TEXT",
    "score REAL",
    "candidate_status TEXT",
    "trend TEXT",
    "ema REAL",
    "distance_to_ema REAL",

    "is_premium_zone INTEGER",
    "is_discount_zone INTEGER",
    "is_equilibrium_zone INTEGER",

    "bos INTEGER",
    "choch INTEGER",
    "liq_sweep INTEGER",
    "fvg INTEGER",
    "ob INTEGER",

    "reason_tags TEXT",
    "raw_json TEXT"
]


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(APEX_MASTER_SCANNER)")
    existing = {row[1] for row in cur.fetchall()}

    added = 0

    for col in NEW_COLUMNS:
        name = col.split()[0]
        if name not in existing:
            sql = f"ALTER TABLE APEX_MASTER_SCANNER ADD COLUMN {col}"
            cur.execute(sql)
            print(f"[ADD] {col}")
            added += 1
        else:
            print(f"[SKIP] {name}")

    conn.commit()
    conn.close()

    print(f"\nDONE. Added columns: {added}")


if __name__ == "__main__":
    main()
