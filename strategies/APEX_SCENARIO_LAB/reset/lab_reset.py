#!/usr/bin/env python3
"""
APEX PROTOCOL™ — APEX_SCENARIO_LAB
lab_reset.py — двухуровневый сброс данных лаборатории.
Без --confirm: только показывает количество строк.
"""
import sys, sqlite3, argparse, json
from datetime import datetime, timezone

sys.path.insert(0, '/root/apex-system')

DB_PATH    = "/root/apex-system/storage/db/sqlite/apex.db"
STATE_FILE = "/root/apex-system/strategies/APEX_SCENARIO_LAB/lab_state.json"

LEVEL1_OPS = [
    ("APEX_MASTER_TRADE",    "WHERE mode='SCENARIO_LAB' AND strategy='APEX_SCENARIO_LAB'"),
    ("APEX_MASTER_SESSIONS", "WHERE session_name='SCENARIO_LAB'"),
]
LEVEL2_EXTRA = [
    ("APEX_MASTER_SCANNER", "WHERE strategy_name='APEX_SCENARIO_LAB'"),
    ("APEX_MASTER_MARKET",  "WHERE session_name='SCENARIO_LAB'"),
    ("APEX_MASTER_ERRORS",  "WHERE module LIKE 'scenario_lab%'"),
]

def _count(conn, table, where):
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()
        return row[0] if row else 0
    except Exception:
        return 0

def run_reset(level, confirm):
    conn = sqlite3.connect(DB_PATH)
    ops  = LEVEL1_OPS if level == 1 else LEVEL1_OPS + LEVEL2_EXTRA
    print(f"\n{'='*55}")
    print(f"  APEX_SCENARIO_LAB RESET — level {level}")
    print(f"  {'DRY RUN' if not confirm else 'CONFIRMED — DELETING'}")
    print(f"{'='*55}")
    total = 0
    for table, where in ops:
        cnt = _count(conn, table, where)
        total += cnt
        print(f"  {table:<35} {cnt:>6} rows")
    print(f"  {'─'*45}")
    print(f"  {'TOTAL':<35} {total:>6} rows")
    if not confirm:
        print(f"\n  Add --confirm to execute.\n")
        conn.close(); return
    print(f"\n  Deleting...")
    for table, where in ops:
        try:
            conn.execute(f"DELETE FROM {table} {where}")
            print(f"  [OK] {table}")
        except Exception as e:
            print(f"  [FAIL] {table}: {e}")
    conn.commit(); conn.close()
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"state":"IDLE","active_trade_ids":[],"last_heartbeat":None,
                       "started_at":None,"stop_requested_at":None,"stopped_at":None,
                       "reset_at":datetime.now(timezone.utc).isoformat()}, f, indent=2)
        print(f"  [OK] lab_state.json reset")
    except Exception as e:
        print(f"  [FAIL] lab_state.json: {e}")
    print(f"\n  Reset level {level} complete.\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", type=int, default=1, choices=[1,2])
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    run_reset(args.level, args.confirm)
