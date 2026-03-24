import sqlite3
import paramiko
import schedule
import time
import logging
import json
import os

LOCAL_DB      = "/root/apex-system/storage/db/sqlite/apex.db"
REMOTE_HOST   = "104.248.206.152"
REMOTE_USER   = "root"
SSH_KEY_PATH  = "/root/.ssh/id_rsa"
LOG_FILE      = "/root/apex-system/sync/sync_tunnel.log"
STATE_FILE    = "/root/apex-system/sync/sync_state.json"
SYNC_INTERVAL = 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [TUNNEL] %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_id": 0}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def get_new_trades(last_id):
    try:
        conn = sqlite3.connect(LOCAL_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM SKL01_T07_final_trade_results WHERE id > ? ORDER BY id ASC", (last_id,))
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:
        log.error(f"Ошибка чтения: {e}")
        return []

def map_trade(row):
    return {
        "trade_id":            row["trade_id"],
        "symbol":              row["symbol"],
        "direction":           row["direction"],
        "strategy_id":         row["strategy"] or "UNKNOWN",
        "strategy_version":    "1.0",
        "timeframe_signal":    "5m",
        "exchange_name":       "binance",
        "market_type":         "futures",
        "opened_at":           row["opened_at"],
        "closed_at":           row["closed_at"],
        "duration_minutes":    row["duration_minutes"],
        "trade_status":        "FINALIZED",
        "close_reason":        row["close_reason"],
        "session_name":        row["session_name"],
        "session_hour":        row["session_hour"],
        "entry_price_planned": row["entry"] or 0,
        "sl_price_planned":    row["sl"] or 0,
        "tp1_price_planned":   row["tp1"],
        "tp2_price_planned":   row["tp2"],
        "tp3_price_planned":   row["tp3"],
        "size_usdt_planned":   row["size"] or 0,
        "leverage_planned":    row["leverage"] or 1,
        "risk_pct_planned":    0,
        "rr_planned":          0,
        "entry_price_actual":  row["entry"],
        "exit_price_actual":   row["close_price"],
        "leverage_actual":     row["leverage"],
        "finalized_at":        row["finalized_at"],
        "final_status":        "CLOSED",
        "exit_reason_primary": row["close_reason"],
        "gross_pnl_usdt":      row["pnl_usdt"],
        "net_pnl_usdt":        row["pnl_usdt"],
        "pnl_pct":             row["pnl_pct"],
        "environment_mode":    row["mode"] or "simulation",
        "bot_id":              "BOT-1",
        "server_id":           "core-02",
    }

def send_to_core03(trades):
    if not trades:
        return 0
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(REMOTE_HOST, username=REMOTE_USER, key_filename=SSH_KEY_PATH)
        tmp = "/tmp/apex_sync_batch.json"
        with open(tmp, "w") as f:
            json.dump([dict(t) for t in trades], f)
        remote_script = "/tmp/apex_sync_insert.py"
        script_content = (
            'import sqlite3, json\n'
            'DB = "/root/apex-core03/db/apex_data.db"\n'
            'data = json.load(open("/tmp/apex_sync_batch.json"))\n'
            'conn = sqlite3.connect(DB)\n'
            'cur = conn.cursor()\n'
            'for t in data:\n'
            '    cols = ",".join(t.keys())\n'
            '    vals = ",".join(["?"]*len(t))\n'
            '    cur.execute(f"INSERT OR IGNORE INTO T07_FINAL_TRADE_RESULTS ({cols}) VALUES ({vals})", list(t.values()))\n'
            'n = conn.total_changes\n'
            'conn.commit()\n'
            'conn.close()\n'
            'print("INSERTED:" + str(n))\n'
        )
        import io
        sftp = ssh.open_sftp()
        sftp.put(tmp, "/tmp/apex_sync_batch.json")
        sftp.putfo(io.BytesIO(script_content.encode()), remote_script)
        sftp.close()
        _, out, err = ssh.exec_command(f"python3 {remote_script}")
        res = out.read().decode().strip()
        err_out = err.read().decode().strip()
        if err_out:
            log.error(f"Remote stderr: {err_out}")
        ssh.close()
        os.remove(tmp)
        return int(res.split("INSERTED:")[1]) if "INSERTED:" in res else 0
    except Exception as e:
        log.error(f"SSH ошибка: {e}")
        return 0

def sync():
    state = load_state()
    rows = get_new_trades(state["last_id"])
    if not rows:
        log.info(f"Нет новых данных (last_id={state['last_id']})")
        return
    inserted = send_to_core03([map_trade(r) for r in rows])
    if inserted > 0:
        save_state({"last_id": max(r["id"] for r in rows)})
        log.info(f"OK: {inserted} сделок")
    else:
        log.warning("Нет вставок")

def get_open_positions():
    try:
        conn = sqlite3.connect(LOCAL_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT trade_id, symbol, direction, fill_price, sl, tp1, tp2, tp3,
                   size_usdt, opened_at, status, session_name
            FROM SKL01_T05_execution_log
            WHERE status = 'open'
            ORDER BY opened_at
        """)
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error(f"get_open_positions ошибка: {e}")
        return []

def sync_positions():
    import io
    positions = get_open_positions()
    try:
        tmp = "/tmp/apex_open_positions.json"
        with open(tmp, "w") as f:
            json.dump(positions, f)
        remote_script = "/tmp/apex_sync_positions.py"
        script_content = (
            'import sqlite3, json\n'
            'DB = "/root/apex-core03/db/apex_data.db"\n'
            'data = json.load(open("/tmp/apex_open_positions.json"))\n'
            'conn = sqlite3.connect(DB)\n'
            'cur = conn.cursor()\n'
            'cur.execute("""CREATE TABLE IF NOT EXISTS T_OPEN_POSITIONS ('
            'trade_id TEXT, symbol TEXT, direction TEXT, fill_price REAL, '
            'sl REAL, tp1 REAL, tp2 REAL, tp3 REAL, size_usdt REAL, '
            'opened_at TEXT, status TEXT, session_name TEXT)""")\n'
            'cur.execute("DELETE FROM T_OPEN_POSITIONS")\n'
            'for t in data:\n'
            '    cols = ",".join(t.keys())\n'
            '    vals = ",".join(["?"]*len(t))\n'
            '    cur.execute(f"INSERT INTO T_OPEN_POSITIONS ({cols}) VALUES ({vals})", list(t.values()))\n'
            'n = conn.total_changes\n'
            'conn.commit()\n'
            'conn.close()\n'
            'print("SYNCED:" + str(n))\n'
        )
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(REMOTE_HOST, username=REMOTE_USER, key_filename=SSH_KEY_PATH)
        sftp = ssh.open_sftp()
        sftp.put(tmp, "/tmp/apex_open_positions.json")
        sftp.putfo(io.BytesIO(script_content.encode()), remote_script)
        sftp.close()
        _, out, err = ssh.exec_command(f"python3 {remote_script}")
        res = out.read().decode().strip()
        err_out = err.read().decode().strip()
        if err_out:
            log.error(f"sync_positions remote stderr: {err_out}")
        ssh.close()
        os.remove(tmp)
        n = int(res.split("SYNCED:")[1]) if "SYNCED:" in res else 0
        log.info(f"sync_positions: {len(positions)} открытых позиций → Core03 ({n} строк)")
    except Exception as e:
        log.error(f"sync_positions SSH ошибка: {e}")

if __name__ == "__main__":
    log.info("APEX SYNC TUNNEL запущен")
    sync()
    sync_positions()
    schedule.every(SYNC_INTERVAL).seconds.do(sync)
    schedule.every(15).seconds.do(sync_positions)
    while True:
        schedule.run_pending()
        time.sleep(1)
