
import sqlite3, sys, os

DB_PATH = "/root/apex-system/storage/db/sqlite/apex.db"

CREATE_NEW = """
CREATE TABLE IF NOT EXISTS APEX_MASTER_TRADE_NEW (
    _SEC1_IDENTIFIERS TEXT,
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT, symbol TEXT, base_asset TEXT, quote_asset TEXT, source_pipeline TEXT,
    _SEC2_STRATEGY TEXT,
    direction TEXT, strategy TEXT, strategy_family TEXT, strategy_version TEXT,
    setup_name TEXT, setup_variant TEXT, mode TEXT,
    _SEC3_SESSION TEXT,
    session_name TEXT, session_group TEXT, sub_session TEXT, session_hour INTEGER,
    event_context TEXT, pre_session_flag INTEGER, overlap_flag INTEGER,
    session_open_minutes_from_start INTEGER, session_date_key TEXT,
    _SEC4_TIMES TEXT,
    opened_at TEXT, closed_at TEXT, finalized_at TEXT, created_at TEXT, updated_at TEXT,
    opened_date TEXT, opened_hour INTEGER, closed_date TEXT, closed_hour INTEGER,
    trade_day_of_week TEXT,
    _SEC5_DURATION TEXT,
    duration_minutes INTEGER, minutes_to_close INTEGER, minutes_to_tp1 INTEGER,
    minutes_to_sl INTEGER, holding_bucket TEXT,
    _SEC6_ENTRY TEXT,
    entry REAL, sl REAL, tp1 REAL, tp2 REAL, tp3 REAL,
    size REAL, leverage INTEGER, fill_price REAL,
    _SEC7_RISK TEXT,
    risk_pct REAL, risk_usdt REAL, rr REAL, account_balance_snapshot REAL,
    risk_model_name TEXT, risk_per_trade_pct_plan REAL, risk_per_trade_usdt_plan REAL,
    actual_loss_usdt REAL, actual_rr REAL, r_multiple REAL,
    _SEC8_EXECUTION_QUALITY TEXT,
    slippage REAL, entry_type TEXT, entry_delay_sec REAL,
    entry_distance_to_sl_pct REAL, entry_distance_to_tp1_pct REAL,
    max_favorable_excursion_mfe REAL, max_adverse_excursion_mae REAL,
    _SEC9_EXIT TEXT,
    close_price REAL, close_reason TEXT, exit_route TEXT, exit_reason_code TEXT,
    exit_reason_text TEXT, close_trigger_side TEXT, forced_exit_flag INTEGER,
    manual_intervention_flag INTEGER, tp_level_reached_max INTEGER, is_finalized INTEGER,
    _SEC10_PNL TEXT,
    commission REAL, fees_open_usdt REAL, fees_close_usdt REAL, total_fees_usdt REAL,
    funding_usdt REAL, gross_pnl_pct REAL, net_pnl_pct REAL, pnl_pct REAL,
    gross_pnl_usdt REAL, net_pnl_usdt REAL, pnl_usdt REAL,
    result_label TEXT, net_result_class TEXT, pnl_bucket TEXT,
    _SEC11_SIGNAL_QUALITY TEXT,
    entry_signal_score REAL, scanner_score REAL, filter_score REAL,
    confidence_score REAL, setup_grade TEXT, entry_quality_flag TEXT,
    _SEC12_ENTRY_REASONS TEXT,
    entry_reason_code TEXT, entry_reason_text TEXT, scanner_passed INTEGER,
    filter_passed INTEGER, execution_attempted INTEGER, execution_success INTEGER,
    reject_reason_stage TEXT, reject_reason_code TEXT, reject_reason_text TEXT,
    _SEC13_MARKET TEXT,
    exchange_name TEXT, market_type TEXT, instrument_type TEXT,
    tick_size REAL, step_size REAL, min_notional REAL,
    _SEC14_SERVICE TEXT,
    calc_version TEXT, row_status TEXT, data_quality_flag TEXT, analytics_ready_flag INTEGER,
    _SEC15_DASHBOARD TEXT,
    dashboard_group_date TEXT, dashboard_sort_ts TEXT, dashboard_color_flag TEXT,
    dashboard_priority INTEGER, dashboard_note TEXT, is_visible_in_dashboard INTEGER,
    _SEC16_SMC_ORB TEXT,
    market_phase TEXT, bos_present INTEGER, choch_present INTEGER,
    entry_in_discount INTEGER, entry_near_ob INTEGER, entry_near_fvg INTEGER,
    orb_high REAL, orb_low REAL, orb_mid REAL, retest_price REAL
);
"""

INSERT_SQL = """
INSERT INTO APEX_MASTER_TRADE_NEW (
    trade_id, symbol, base_asset, quote_asset,
    direction, strategy, mode,
    session_name, session_hour,
    opened_at, closed_at, finalized_at, created_at,
    opened_date, opened_hour, closed_date, closed_hour, trade_day_of_week,
    duration_minutes,
    entry, sl, tp1, tp2, tp3, size, leverage, fill_price,
    risk_pct, risk_usdt, rr,
    slippage,
    close_price, close_reason, exit_route, tp_level_reached_max,
    commission, pnl_pct, pnl_usdt, result_label,
    row_status, is_visible_in_dashboard
)
SELECT
    trade_id, symbol,
    CASE WHEN INSTR(symbol,\'/')>0 THEN SUBSTR(symbol,1,INSTR(symbol,\'/\')-1)
         WHEN INSTR(symbol,\':\')<>0 THEN SUBSTR(symbol,1,INSTR(symbol,\':')-1)
         ELSE symbol END,
    \'USDT\',
    direction, strategy, mode,
    session_name, session_hour,
    opened_at, closed_at, finalized_at, created_at,
    DATE(opened_at),
    CAST(strftime(\'%H\',opened_at) AS INTEGER),
    DATE(closed_at),
    CAST(strftime(\'%H\',closed_at) AS INTEGER),
    CASE strftime(\'%w\',opened_at)
        WHEN \'0\' THEN \'SUN\' WHEN \'1\' THEN \'MON\' WHEN \'2\' THEN \'TUE\'
        WHEN \'3\' THEN \'WED\' WHEN \'4\' THEN \'THU\' WHEN \'5\' THEN \'FRI\' WHEN \'6\' THEN \'SAT\' END,
    CASE WHEN closed_at IS NOT NULL AND opened_at IS NOT NULL
        THEN CAST((JULIANDAY(closed_at)-JULIANDAY(opened_at))*1440 AS INTEGER) ELSE NULL END,
    entry, sl, tp1, tp2, tp3, size, leverage, fill_price,
    risk_pct, risk_usdt, rr,
    slippage,
    close_price, close_reason,
    CASE close_reason WHEN \'TP1\' THEN \'TP\' WHEN \'TP2\' THEN \'TP\' WHEN \'TP3\' THEN \'TP\'
        WHEN \'SL\' THEN \'SL\' WHEN \'TIMEOUT\' THEN \'TIME_EXIT\'
        WHEN \'MANUAL_STOP\' THEN \'MANUAL\' ELSE \'UNKNOWN\' END,
    tp_level_reached_max,
    commission, pnl_pct, pnl_usdt,
    CASE WHEN pnl_usdt>0 THEN \'WIN\' WHEN pnl_usdt<0 THEN \'LOSS\' ELSE \'BE\' END,
    \'RAW\', 1
FROM APEX_MASTER_TRADE;
"""

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("SELECT COUNT(*) FROM APEX_MASTER_TRADE")
src = c.fetchone()[0]
print(f"[INFO] Исходных строк: {src}")

c.execute("DROP TABLE IF EXISTS APEX_MASTER_TRADE_NEW")
conn.commit()

c.executescript(CREATE_NEW)
conn.commit()
print("[OK] APEX_MASTER_TRADE_NEW создана")

c.executescript(INSERT_SQL)
conn.commit()

c.execute("SELECT COUNT(*) FROM APEX_MASTER_TRADE_NEW")
new = c.fetchone()[0]
print(f"[OK] Перелито строк: {new}")

if new != src:
    print(f"[ERROR] Несоответствие: {src} vs {new}")
    conn.close(); sys.exit(1)

c.execute("DROP TABLE IF EXISTS APEX_MASTER_TRADE_OLD")
c.execute("ALTER TABLE APEX_MASTER_TRADE RENAME TO APEX_MASTER_TRADE_OLD")
c.execute("ALTER TABLE APEX_MASTER_TRADE_NEW RENAME TO APEX_MASTER_TRADE")
conn.commit()

c.execute("SELECT COUNT(*) FROM APEX_MASTER_TRADE")
final = c.fetchone()[0]
print(f"[DONE] APEX_MASTER_TRADE готова. Строк: {final}")
conn.close()
