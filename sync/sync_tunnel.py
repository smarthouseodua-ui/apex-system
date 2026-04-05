import sqlite3
import paramiko
import schedule
import time
import logging
import json
import os
import io

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
    """Новые строки (ещё не отправлялись)."""
    try:
        conn = sqlite3.connect(LOCAL_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM APEX_MASTER_TRADE WHERE id > ? ORDER BY id ASC",
            (last_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error(f"get_new_trades error: {e}")
        return []

def get_closed_trades():
    """Закрытые строки — для UPDATE на remote."""
    try:
        conn = sqlite3.connect(LOCAL_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM APEX_MASTER_TRADE WHERE finalized_at IS NOT NULL"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error(f"get_closed_trades error: {e}")
        return []

def _remote_exec(script_text, json_data, label="sync"):
    """SSH → remote: загрузить JSON + скрипт, выполнить."""
    tmp = "/tmp/apex_sync_batch.json"
    try:
        with open(tmp, "w") as f:
            json.dump(json_data, f, default=str)

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(REMOTE_HOST, username=REMOTE_USER, key_filename=SSH_KEY_PATH)
        sftp = ssh.open_sftp()
        sftp.put(tmp, "/tmp/apex_sync_batch.json")
        sftp.putfo(io.BytesIO(script_text.encode()), "/tmp/apex_sync_insert.py")
        sftp.close()
        _, out, err = ssh.exec_command("python3 /tmp/apex_sync_insert.py")
        res = out.read().decode().strip()
        err_out = err.read().decode().strip()
        if err_out:
            log.error(f"[{label}] Remote stderr: {err_out}")
        ssh.close()
        os.remove(tmp)
        return res
    except Exception as e:
        log.error(f"[{label}] SSH error: {e}")
        return ""

# ── Remote script: INSERT новых строк ────────────────────────────────
REMOTE_INSERT = (
    'import sqlite3, json\n'
    'DB = "/root/apex-core03/db/apex_data.db"\n'
    'data = json.load(open("/tmp/apex_sync_batch.json"))\n'
    'conn = sqlite3.connect(DB)\n'
    'cur = conn.cursor()\n'
    'n = 0\n'
    'for t in data:\n'
    '    t.pop("id", None)\n'
    '    cols = ",".join(t.keys())\n'
    '    vals = ",".join(["?"]*len(t))\n'
    '    cur.execute(f"INSERT OR IGNORE INTO APEX_MASTER_TRADE ({cols}) VALUES ({vals})", list(t.values()))\n'
    '    n += cur.rowcount\n'
    'conn.commit()\n'
    'conn.close()\n'
    'print("INSERTED:" + str(n))\n'
)

# ── Remote script: UPDATE закрытых строк ─────────────────────────────
REMOTE_UPDATE = (
    'import sqlite3, json\n'
    'DB = "/root/apex-core03/db/apex_data.db"\n'
    'data = json.load(open("/tmp/apex_sync_batch.json"))\n'
    'conn = sqlite3.connect(DB)\n'
    'cur = conn.cursor()\n'
    'n = 0\n'
    'for t in data:\n'
    '    tid = t.get("trade_id")\n'
    '    if not tid:\n'
    '        continue\n'
    '    cur.execute("""UPDATE APEX_MASTER_TRADE SET\n'
    '        strategy=?, session_hour=?, leverage=?,\n'
    '        risk_pct=?, risk_usdt=?, rr=?,\n'
    '        close_price=?, close_reason=?, exit_route=?,\n'
    '        tp_level_reached_max=?, minutes_to_tp1=?, minutes_to_sl=?, minutes_to_close=?,\n'
    '        pnl_pct=?, pnl_usdt=?, result_label=?,\n'
    '        closed_at=?, finalized_at=?, duration_minutes=?,\n'
    '        market_phase=?, bos_present=?, choch_present=?,\n'
    '        entry_in_discount=?, entry_near_ob=?, entry_near_fvg=?,\n'
    '        orb_high=?, orb_low=?, orb_mid=?, retest_price=?\n'
    '    WHERE trade_id=?""",\n'
    '    (\n'
    '        t.get("strategy"), t.get("session_hour"), t.get("leverage"),\n'
    '        t.get("risk_pct"), t.get("risk_usdt"), t.get("rr"),\n'
    '        t.get("close_price"), t.get("close_reason"), t.get("exit_route"),\n'
    '        t.get("tp_level_reached_max"), t.get("minutes_to_tp1"), t.get("minutes_to_sl"), t.get("minutes_to_close"),\n'
    '        t.get("pnl_pct"), t.get("pnl_usdt"), t.get("result_label"),\n'
    '        t.get("closed_at"), t.get("finalized_at"), t.get("duration_minutes"),\n'
    '        t.get("market_phase"), t.get("bos_present"), t.get("choch_present"),\n'
    '        t.get("entry_in_discount"), t.get("entry_near_ob"), t.get("entry_near_fvg"),\n'
    '        t.get("orb_high"), t.get("orb_low"), t.get("orb_mid"), t.get("retest_price"),\n'
    '        tid,\n'
    '    ))\n'
    '    n += cur.rowcount\n'
    'conn.commit()\n'
    'conn.close()\n'
    'print("UPDATED:" + str(n))\n'
)

def sync():
    state = load_state()

    # ── Фаза 1: INSERT новых строк ──────────────────────────────────
    new_trades = get_new_trades(state["last_id"])
    if new_trades:
        res = _remote_exec(REMOTE_INSERT, new_trades, "INSERT")
        if "INSERTED:" in res:
            n = int(res.split("INSERTED:")[1])
            new_last = max(t["id"] for t in new_trades)
            save_state({"last_id": new_last})
            log.info(f"INSERT: {n} новых строк (last_id → {new_last})")
        else:
            log.warning(f"INSERT: unexpected response: {res}")
    else:
        log.info(f"Нет новых строк (last_id={state['last_id']})")

    # ── Фаза 2: UPDATE закрытых строк ───────────────────────────────
    closed = get_closed_trades()
    if closed:
        res = _remote_exec(REMOTE_UPDATE, closed, "UPDATE")
        if "UPDATED:" in res:
            n = int(res.split("UPDATED:")[1])
            log.info(f"UPDATE: {n} закрытых строк обновлено")
        else:
            log.warning(f"UPDATE: unexpected response: {res}")

if __name__ == "__main__":
    log.info("APEX SYNC TUNNEL запущен")
    sync()
    schedule.every(SYNC_INTERVAL).seconds.do(sync)
    while True:
        schedule.run_pending()
        time.sleep(1)
