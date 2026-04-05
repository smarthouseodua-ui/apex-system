#!/usr/bin/env python3
"""
APEX PROTOCOL™ — APEX_SCENARIO_LAB
lab_runner.py

STATES: IDLE → RUNNING → STOPPING → STOPPED
--start: acquire lock, run loop
--stop:  write STOPPING only, no position closing
"""
import sys, json, time, fcntl, logging, argparse, sqlite3, os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/root/apex-system')
sys.path.insert(0, '/root/apex-system/strategies/APEX_SCENARIO_LAB')

from storage.db.repository import Repository
from modules.finalizer import get_price, close_trade

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")
logger = logging.getLogger("apex.scenario_lab.runner")

LAB_DIR         = "/root/apex-system/strategies/APEX_SCENARIO_LAB"
STATE_FILE      = f"{LAB_DIR}/lab_state.json"
CFG_FILE        = f"{LAB_DIR}/lab_config.json"
DB_PATH         = "/root/apex-system/storage/db/sqlite/apex.db"
LOCK_FILE       = "/tmp/apex_scenario_lab.lock"
STATE_LOCK_FILE = "/tmp/apex_scenario_lab_state.lock"

HEARTBEAT_STALE_MULTIPLIER = 3
STOP_PRICE_RETRIES         = 3
STOP_PRICE_RETRY_DELAY     = 2

_lock_fh = None

def _acquire_lock() -> bool:
    global _lock_fh
    try:
        _lock_fh = open(LOCK_FILE, "w")
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fh.write(str(os.getpid()))
        _lock_fh.flush()
        return True
    except BlockingIOError:
        if _lock_fh: _lock_fh.close(); _lock_fh = None
        return False
    except Exception as e:
        logger.error(f"[LAB] Lock acquire error: {e}")
        if _lock_fh: _lock_fh.close(); _lock_fh = None
        return False

def _release_lock():
    global _lock_fh
    try:
        if _lock_fh:
            fcntl.flock(_lock_fh, fcntl.LOCK_UN)
            _lock_fh.close(); _lock_fh = None
    except Exception:
        pass

def _read_state() -> dict:
    try:
        with open(STATE_LOCK_FILE, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_SH)
            try:
                with open(STATE_FILE) as f:
                    return json.load(f)
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
    except Exception:
        return {"state":"IDLE","active_trade_ids":[],"last_heartbeat":None,
                "started_at":None,"stop_requested_at":None,"stopped_at":None}

def _write_state(updates: dict):
    try:
        with open(STATE_LOCK_FILE, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                try:
                    with open(STATE_FILE) as f:
                        state = json.load(f)
                except Exception:
                    state = {}
                incoming = updates.get("state")
                current  = state.get("state", "IDLE")
                ALLOWED = {
                    "IDLE":     ["RUNNING"],
                    "RUNNING":  ["STOPPING"],
                    "STOPPING": ["STOPPED"],
                    "STOPPED":  ["RUNNING"],
                }
                if incoming is not None and incoming not in ALLOWED.get(current, []):
                    updates.pop("state", None)
                state.update(updates)
                tmp = STATE_FILE + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(state, f, indent=2)
                os.replace(tmp, STATE_FILE)
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
    except Exception as e:
        logger.error(f"[LAB] _write_state error: {e}")

def _read_config() -> dict:
    with open(CFG_FILE) as f: return json.load(f)

def _log_error(event, message, level="ERROR", tb=None):
    try:
        Repository().log_system_event(event=event, module="scenario_lab.runner",
            message=message, level=level, traceback=tb)
    except Exception:
        pass

def _is_heartbeat_stale(last_heartbeat, interval) -> bool:
    if not last_heartbeat: return True
    try:
        hb = datetime.fromisoformat(last_heartbeat.replace("Z",""))
        if hb.tzinfo is None: hb = hb.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - hb) > timedelta(seconds=interval * HEARTBEAT_STALE_MULTIPLIER)
    except Exception:
        return True

def _restore_active_positions() -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM APEX_MASTER_TRADE
            WHERE mode='SCENARIO_LAB' AND strategy='APEX_SCENARIO_LAB' AND closed_at IS NULL
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        _log_error("RESTORE_POSITIONS_ERROR", str(e))
        return []

def _load_scenarios(cfg) -> list:
    scenarios = []
    for name in cfg.get("active_scenarios", []):
        try:
            if name == "SC_001_FULL_PATH":
                from scenarios.sc_001_full_path import SC001FullPath
                s = SC001FullPath()
            elif name == "SC_002_SECOND_CANDLE":
                from scenarios.sc_002_second_candle import SC002SecondCandle
                s = SC002SecondCandle()
            else:
                logger.warning(f"[LAB] Unknown scenario: {name}")
                continue
            if s.validate():
                scenarios.append(s)
                logger.info(f"[LAB] Loaded scenario: {name}")
            else:
                logger.warning(f"[LAB] Scenario {name} failed validate()")
        except Exception as e:
            _log_error("SCENARIO_LOAD_ERROR", f"{name}: {e}")
    return scenarios

def _scenario_by_name(scenarios) -> dict:
    return {sc.name: sc for sc in scenarios}

def _execute_fallback(params) -> str | None:
    try:
        from core.id_manager import IdManager
        from modules.config import EXCHANGE_NAME
        now = datetime.now(timezone.utc).isoformat()
        trade_id = IdManager().next_trade_id()
        position = {
            "trade_id": trade_id, "symbol": params["symbol"],
            "direction": params["direction"], "strategy": "APEX_SCENARIO_LAB",
            "strategy_family": "SCENARIO_LAB",
            "setup_name": params.get("_scenario_name", "SC_001_FULL_PATH"),
            "mode": "SCENARIO_LAB", "session_name": "SCENARIO_LAB",
            "entry": params["entry_price"], "entry_price": params["entry_price"],
            "fill_price": params["entry_price"],
            "sl": params.get("sl"), "tp1": params.get("tp1"),
            "tp2": params.get("tp2"), "tp3": params.get("tp3"),
            "size": params.get("size"), "leverage": params.get("leverage", 20),
            "risk_usdt": params.get("risk_usdt"), "risk_pct": params.get("risk_pct"),
            "rr": params.get("rr"), "opened_at": now, "exchange_name": EXCHANGE_NAME,
            "market_type": "FUTURES", "instrument_type": "PERPETUAL",
            "calc_version": "v2.0", "scanner_score": 0.0, "entry_signal_score": 0.0,
            "entry_reason_code": params.get("entry_reason_code", "SCENARIO_LAB"),
            "entry_reason_text": f"APEX_SCENARIO_LAB: {params.get('_scenario_name')}",
            "event_context": "NORMAL", "scanner_passed": 1, "filter_passed": 1,
            "execution_attempted": 1, "execution_success": 1,
            "market_phase": params.get("market_phase"),
            "bos_present": params.get("bos_present", 0),
            "choch_present": params.get("choch_present", 0),
            "entry_in_discount": params.get("entry_in_discount", 0),
            "entry_near_ob": params.get("entry_near_ob", 0),
            "entry_near_fvg": params.get("entry_near_fvg", 0),
            "orb_high": params.get("orb_high"), "orb_low": params.get("orb_low"),
            "orb_mid": params.get("orb_mid"),
        }
        if not position.get('source_pipeline'):
            position['source_pipeline'] = 'apex-pipeline'
        if not position.get('account_balance_snapshot'):
            position['account_balance_snapshot'] = params.get('test_balance') or params.get('balance') or 5000.0
        if not position.get('risk_model_name'):
            position['risk_model_name'] = params.get('risk_model_name') or 'FIXED'
        if not position.get('risk_per_trade_usdt_plan'):
            position['risk_per_trade_usdt_plan'] = params.get('position_size_usdt') or params.get('risk_usdt') or 500.0
        if not position.get('confidence_score'):
            position['confidence_score'] = params.get('confidence_score') or params.get('score') or 0.0
        Repository().log_execution(position)
        logger.info(f"[LAB] OPENED {params['symbol']} {params['direction']} "
                    f"entry={params['entry_price']} trade_id={trade_id}")
        return trade_id
    except Exception as e:
        import traceback as _tb
        _log_error("EXECUTION_ERROR", f"{params.get('symbol')}: {e}", tb=_tb.format_exc())
        return None

def _process_closes(active_positions, scenario_map, conn):
    for pos in active_positions:
        try:
            symbol = pos["symbol"]
            sc = scenario_map.get(pos.get("setup_name") or "")
            if sc is None:
                logger.warning(f"[LAB] No scenario for setup_name='{pos.get('setup_name')}' on {symbol} — skipped")
                continue
            try:
                current_price = get_price(symbol)
            except Exception as e:
                _log_error("PRICE_FETCH_ERROR", f"{symbol}: {e}", level="WARNING"); continue
            try:
                result = sc.get_close_event(pos, current_price)
                if result:
                    close_price, reason = result
                    close_trade(conn, pos, close_price, reason)
                    logger.info(f"[LAB] CLOSED {symbol} scenario={sc.name} reason={reason} price={close_price}")
            except Exception as e:
                import traceback as _tb
                _log_error("CLOSE_EVENT_ERROR", f"{symbol}: {e}", tb=_tb.format_exc())
        except Exception as e:
            import traceback as _tb
            _log_error("CLOSE_BLOCK_ERROR", str(e), tb=_tb.format_exc())

def _get_price_with_retry(symbol) -> float | None:
    for attempt in range(1, STOP_PRICE_RETRIES + 1):
        try:
            price = get_price(symbol)
            if price and price > 0: return price
            logger.warning(f"[LAB] price={price} invalid for {symbol} (attempt {attempt}/{STOP_PRICE_RETRIES})")
        except Exception as e:
            logger.warning(f"[LAB] price fetch error for {symbol}: {e} (attempt {attempt}/{STOP_PRICE_RETRIES})")
        if attempt < STOP_PRICE_RETRIES: time.sleep(STOP_PRICE_RETRY_DELAY)
    return None

def _run_stopping_iteration(conn) -> bool:
    active = _restore_active_positions()
    if not active: return True
    logger.info(f"[LAB] STOPPING: {len(active)} position(s) remaining")
    for pos in active:
        symbol = pos["symbol"]
        price = _get_price_with_retry(symbol)
        if price is None:
            _log_error("STOP_PRICE_UNAVAILABLE",
                f"Could not get real price for {symbol}. Position NOT closed. Will retry. trade_id={pos.get('trade_id')}",
                level="ERROR")
            logger.error(f"[LAB] STOPPING: SKIPPED {symbol} — price unavailable, will retry")
            continue
        try:
            close_trade(conn, pos, price, "MANUAL_STOP")
            logger.info(f"[LAB] STOPPING: closed {symbol} price={price}")
        except Exception as e:
            import traceback as _tb
            _log_error("STOP_CLOSE_ERROR", f"{symbol}: {e}", tb=_tb.format_exc())
    return len(_restore_active_positions()) == 0

def cmd_stop():
    state = _read_state()
    current = state.get("state", "IDLE")
    if current in ("STOPPED", "IDLE"):
        logger.info(f"[LAB] --stop: already {current}, nothing to do"); return
    if current == "STOPPING":
        logger.info("[LAB] --stop: already STOPPING, waiting for main process"); return
    _write_state({"state": "STOPPING", "stop_requested_at": datetime.now(timezone.utc).isoformat()})
    logger.info("[LAB] STOP REQUEST sent: state=STOPPING. Main process will close positions.")

def cmd_start():
    cfg      = _read_config()
    interval = int(cfg.get("interval_seconds", 5))

    if not _acquire_lock():
        logger.error(f"[LAB] START REJECTED: another process is running (lock: {LOCK_FILE})")
        sys.exit(1)
    logger.info(f"[LAB] Process lock acquired: {LOCK_FILE}")

    state = _read_state()
    if state["state"] == "RUNNING":
        if _is_heartbeat_stale(state.get("last_heartbeat"), interval):
            logger.warning("[LAB] Previous instance crashed — resuming")
            _log_error("LAB_UNEXPECTED_STOP", f"Stale heartbeat (last={state.get('last_heartbeat')})", level="WARNING")
        else:
            logger.warning("[LAB] State=RUNNING + fresh heartbeat but lock free — race condition, proceeding")
    elif state["state"] == "STOPPING":
        logger.info("[LAB] Resuming in STOPPING state")

    lab_balance  = float(cfg.get("lab_balance", 100000.0))
    scenarios    = _load_scenarios(cfg)
    scenario_map = _scenario_by_name(scenarios)
    if not scenarios:
        logger.warning("[LAB] No scenarios loaded — loop continues without opening trades")

    active_positions = _restore_active_positions()
    _write_state({
        "state": state["state"] if state["state"] == "STOPPING" else "RUNNING",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "active_trade_ids": [p["trade_id"] for p in active_positions],
        "stopped_at": None,
        "stop_requested_at": state.get("stop_requested_at"),
    })
    logger.info(f"[LAB] START — loop. Restored {len(active_positions)} positions from DB")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        while True:
            current_state = _read_state().get("state", "IDLE")

            if current_state == "STOPPED":
                logger.info("[LAB] State=STOPPED — exiting"); break

            if current_state == "STOPPING":
                _write_state({"last_heartbeat": datetime.now(timezone.utc).isoformat()})
                try:
                    all_closed = _run_stopping_iteration(conn)
                except Exception as e:
                    import traceback as _tb
                    _log_error("STOPPING_ITER_ERROR", str(e), level="CRITICAL", tb=_tb.format_exc())
                    all_closed = False
                if all_closed:
                    _write_state({"state":"STOPPED","stopped_at":datetime.now(timezone.utc).isoformat(),"active_trade_ids":[]})
                    logger.info("[LAB] All positions closed — state=STOPPED, exiting"); break
                else:
                    logger.info("[LAB] Some positions still open — retrying")
                    time.sleep(interval); continue

            # RUNNING
            _write_state({"last_heartbeat": datetime.now(timezone.utc).isoformat()})

            try:
                new_ids = []

                # Проверка 1: перед входом в цикл сценариев
                if _read_state().get("state") == "STOPPING":
                    logger.info("[LAB] STOPPING detected before scenario loop — skipping entries")
                else:
                    for sc in scenarios:
                        try:
                            try:
                                symbol = sc.pick_symbol()
                            except Exception as e:
                                import traceback as _tb
                                _log_error("PICK_SYMBOL_ERROR", str(e), tb=_tb.format_exc()); symbol = None
                            if symbol is None: continue

                            try:
                                context = sc.get_context(symbol)
                            except Exception as e:
                                import traceback as _tb
                                _log_error("CONTEXT_ERROR", str(e), tb=_tb.format_exc()); context = {}
                            if context is None:
                                logger.info(f"[LAB] {sc.name}: no SMC context (STRICT) → skip"); continue

                            try:
                                signal = sc.generate_signal(symbol, context)
                            except Exception as e:
                                import traceback as _tb
                                _log_error("SIGNAL_ERROR", str(e), tb=_tb.format_exc()); signal = None
                            if signal is None: continue

                            try:
                                params = sc.apply_risk(signal, cfg)
                            except Exception as e:
                                import traceback as _tb
                                _log_error("RISK_ERROR", str(e), tb=_tb.format_exc()); params = None
                            if params is None: continue

                            params["_scenario_name"] = sc.name

                            # Проверка 2: прямо перед execution
                            if _read_state().get("state") == "STOPPING":
                                logger.info(f"[LAB] STOPPING before execution {sc.name}/{params.get('symbol')} — skipping")
                                break

                            exec_path = cfg.get("execution_path", "FALLBACK")
                            trade_id  = None
                            if exec_path == "FULL":
                                try:
                                    from modules.execution_engine import execute as _exec
                                    order = _exec(signal, lab_balance)
                                    if order: trade_id = order.get("trade_id")
                                except Exception as e:
                                    import traceback as _tb
                                    _log_error("FULL_EXEC_ERROR", str(e), level="WARNING", tb=_tb.format_exc())
                                    trade_id = _execute_fallback(params)
                            else:
                                trade_id = _execute_fallback(params)

                            if trade_id: new_ids.append(trade_id)

                        except Exception as e:
                            import traceback as _tb
                            _log_error("SCENARIO_ITER_ERROR", f"{sc.name}: {e}", tb=_tb.format_exc())
                            continue

                if new_ids:
                    st = _read_state()
                    st["active_trade_ids"] = list(set(st.get("active_trade_ids", []) + new_ids))
                    _write_state(st)

                active_positions = _restore_active_positions()
                _process_closes(active_positions, scenario_map, conn)

            except Exception as e:
                import traceback as _tb
                _log_error("LOOP_CRITICAL_ERROR", str(e), level="CRITICAL", tb=_tb.format_exc())
                logger.error(f"[LAB] CRITICAL loop error: {e} — continuing")

            time.sleep(interval)

    finally:
        conn.close()
        _release_lock()
        logger.info(f"[LAB] Process lock released: {LOCK_FILE}")

    logger.info("[LAB] Loop exited cleanly")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="APEX Scenario Lab Runner")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--stop",  action="store_true")
    args = parser.parse_args()
    if args.stop:   cmd_stop()
    elif args.start: cmd_start()
    else:            parser.print_help()
