
import sqlite3,sys,os
DB_PATH="/root/apex-system/storage/db/sqlite/apex.db"
TRIGGER_INSERT="""
CREATE TRIGGER IF NOT EXISTS trg_apex_calc_insert
AFTER INSERT ON APEX_MASTER_TRADE FOR EACH ROW
BEGIN
  UPDATE APEX_MASTER_TRADE SET
    base_asset=CASE WHEN INSTR(NEW.symbol,'/')>0 THEN SUBSTR(NEW.symbol,1,INSTR(NEW.symbol,'/')-1) WHEN INSTR(NEW.symbol,':')>0 THEN SUBSTR(NEW.symbol,1,INSTR(NEW.symbol,':')-1) ELSE NEW.symbol END,
    quote_asset='USDT',
    opened_date=DATE(NEW.opened_at),
    opened_hour=CAST(strftime('%H',NEW.opened_at)AS INTEGER),
    closed_date=DATE(NEW.closed_at),
    closed_hour=CAST(strftime('%H',NEW.closed_at)AS INTEGER),
    trade_day_of_week=CASE strftime('%w',NEW.opened_at) WHEN '0' THEN 'SUN' WHEN '1' THEN 'MON' WHEN '2' THEN 'TUE' WHEN '3' THEN 'WED' WHEN '4' THEN 'THU' WHEN '5' THEN 'FRI' WHEN '6' THEN 'SAT' END,
    duration_minutes=CASE WHEN NEW.closed_at IS NOT NULL AND NEW.opened_at IS NOT NULL THEN CAST((JULIANDAY(NEW.closed_at)-JULIANDAY(NEW.opened_at))*1440 AS INTEGER) ELSE NULL END,
    exit_route=CASE NEW.close_reason WHEN 'TP1' THEN 'TP' WHEN 'TP2' THEN 'TP' WHEN 'TP3' THEN 'TP' WHEN 'SL' THEN 'SL' WHEN 'TIMEOUT' THEN 'TIME_EXIT' WHEN 'MANUAL_STOP' THEN 'MANUAL' ELSE 'UNKNOWN' END,
    result_label=CASE WHEN NEW.pnl_usdt>0 THEN 'WIN' WHEN NEW.pnl_usdt<0 THEN 'LOSS' ELSE 'BE' END,
    row_status=COALESCE(NEW.row_status,'RAW'),
    updated_at=datetime('now'),
    is_visible_in_dashboard=COALESCE(NEW.is_visible_in_dashboard,1)
  WHERE id=NEW.id;
END;
"""
TRIGGER_UPDATE="""
CREATE TRIGGER IF NOT EXISTS trg_apex_calc_update
AFTER UPDATE ON APEX_MASTER_TRADE FOR EACH ROW
WHEN OLD.row_status IS NOT 'LOCKED'
BEGIN
  UPDATE APEX_MASTER_TRADE SET
    base_asset=CASE WHEN INSTR(NEW.symbol,'/')>0 THEN SUBSTR(NEW.symbol,1,INSTR(NEW.symbol,'/')-1) WHEN INSTR(NEW.symbol,':')>0 THEN SUBSTR(NEW.symbol,1,INSTR(NEW.symbol,':')-1) ELSE NEW.symbol END,
    quote_asset='USDT',
    opened_date=DATE(NEW.opened_at),
    opened_hour=CAST(strftime('%H',NEW.opened_at)AS INTEGER),
    closed_date=DATE(NEW.closed_at),
    closed_hour=CAST(strftime('%H',NEW.closed_at)AS INTEGER),
    trade_day_of_week=CASE strftime('%w',NEW.opened_at) WHEN '0' THEN 'SUN' WHEN '1' THEN 'MON' WHEN '2' THEN 'TUE' WHEN '3' THEN 'WED' WHEN '4' THEN 'THU' WHEN '5' THEN 'FRI' WHEN '6' THEN 'SAT' END,
    duration_minutes=CASE WHEN NEW.closed_at IS NOT NULL AND NEW.opened_at IS NOT NULL THEN CAST((JULIANDAY(NEW.closed_at)-JULIANDAY(NEW.opened_at))*1440 AS INTEGER) ELSE NULL END,
    exit_route=CASE NEW.close_reason WHEN 'TP1' THEN 'TP' WHEN 'TP2' THEN 'TP' WHEN 'TP3' THEN 'TP' WHEN 'SL' THEN 'SL' WHEN 'TIMEOUT' THEN 'TIME_EXIT' WHEN 'MANUAL_STOP' THEN 'MANUAL' ELSE 'UNKNOWN' END,
    result_label=CASE WHEN NEW.pnl_usdt>0 THEN 'WIN' WHEN NEW.pnl_usdt<0 THEN 'LOSS' ELSE 'BE' END,
    row_status=COALESCE(NEW.row_status,'RAW'),
    updated_at=datetime('now'),
    is_visible_in_dashboard=COALESCE(NEW.is_visible_in_dashboard,1)
  WHERE id=NEW.id;
END;
"""
conn=sqlite3.connect(DB_PATH)
c=conn.cursor()
c.execute("DROP TRIGGER IF EXISTS trg_apex_calc_insert")
c.execute("DROP TRIGGER IF EXISTS trg_apex_calc_update")
conn.commit()
c.executescript(TRIGGER_INSERT)
print("[OK] INSERT триггер создан")
c.executescript(TRIGGER_UPDATE)
print("[OK] UPDATE триггер создан")
conn.commit()
c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='APEX_MASTER_TRADE'")
print("[CHECK]",[ r[0] for r in c.fetchall()])
conn.close()
print("[DONE] OK")
