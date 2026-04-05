#!/usr/bin/env python3
"""
APEX PROTOCOL™ — APEX_SCENARIO_LAB
lab_inspector.py — отчёты по данным лаборатории. Только SELECT.
"""
import sys, sqlite3, argparse

DB_PATH = "/root/apex-system/storage/db/sqlite/apex.db"
WHERE   = "WHERE mode='SCENARIO_LAB' AND strategy='APEX_SCENARIO_LAB'"

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def report_coverage():
    conn = _conn()
    row = conn.execute(f"""
        SELECT COUNT(*) as total,
          ROUND(COUNT(trade_id)*100.0/COUNT(*),1) as trade_id_pct,
          ROUND(COUNT(entry)*100.0/COUNT(*),1)    as entry_pct,
          ROUND(COUNT(sl)*100.0/COUNT(*),1)       as sl_pct,
          ROUND(COUNT(tp1)*100.0/COUNT(*),1)      as tp1_pct,
          ROUND(COUNT(close_price)*100.0/COUNT(*),1) as close_price_pct,
          ROUND(COUNT(pnl_usdt)*100.0/COUNT(*),1)    as pnl_usdt_pct,
          ROUND(COUNT(pnl_pct)*100.0/COUNT(*),1)     as pnl_pct_pct,
          ROUND(COUNT(close_reason)*100.0/COUNT(*),1)  as close_reason_pct,
          ROUND(COUNT(event_context)*100.0/COUNT(*),1) as event_context_pct,
          ROUND(COUNT(result_label)*100.0/COUNT(*),1)  as result_label_pct,
          ROUND(COUNT(risk_usdt)*100.0/COUNT(*),1)     as risk_usdt_pct,
          ROUND(COUNT(rr)*100.0/COUNT(*),1)            as rr_pct,
          ROUND(COUNT(market_phase)*100.0/COUNT(*),1)  as market_phase_pct,
          ROUND(COUNT(bos_present)*100.0/COUNT(*),1)   as bos_pct
        FROM APEX_MASTER_TRADE {WHERE}
    """).fetchone()
    if not row or row["total"] == 0:
        print("  No LAB data found."); conn.close(); return
    print(f"\n{'='*50}\n  COVERAGE REPORT — {row['total']} rows\n{'='*50}")
    for f in ["trade_id","entry","sl","tp1","close_price","pnl_usdt","pnl_pct",
              "close_reason","event_context","result_label","risk_usdt","rr","market_phase","bos"]:
        key = f"{f}_pct"
        val = row[key] if key in row.keys() else "—"
        icon = "✅" if val == 100.0 else ("⚠️" if val and val > 0 else "🔴")
        print(f"  {f:<22} {str(val):>6}%  {icon}")
    conn.close()

def report_lifecycle():
    conn = _conn()
    print(f"\n{'='*50}\n  LIFECYCLE REPORT\n{'='*50}")
    for title, sql in [
        ("close_reason", f"SELECT close_reason, COUNT(*) as cnt FROM APEX_MASTER_TRADE {WHERE} GROUP BY close_reason ORDER BY cnt DESC"),
        ("row_status/finalized", f"SELECT row_status, is_finalized, COUNT(*) as cnt FROM APEX_MASTER_TRADE {WHERE} GROUP BY row_status, is_finalized"),
        ("event_context", f"SELECT event_context, COUNT(*) as cnt FROM APEX_MASTER_TRADE {WHERE} GROUP BY event_context ORDER BY cnt DESC"),
    ]:
        print(f"\n  {title}:")
        for r in conn.execute(sql).fetchall():
            print("   ", dict(r))
    conn.close()

def report_anomalies():
    conn = _conn()
    row = conn.execute(f"""
        SELECT
          SUM(CASE WHEN closed_at IS NOT NULL AND close_price IS NULL  THEN 1 ELSE 0 END) as no_close_price,
          SUM(CASE WHEN closed_at IS NOT NULL AND pnl_usdt IS NULL     THEN 1 ELSE 0 END) as no_pnl_usdt,
          SUM(CASE WHEN closed_at IS NOT NULL AND event_context IS NULL THEN 1 ELSE 0 END) as no_event_ctx,
          SUM(CASE WHEN closed_at IS NOT NULL AND close_reason IS NULL  THEN 1 ELSE 0 END) as no_close_reason,
          SUM(CASE WHEN row_status='active' AND closed_at IS NOT NULL   THEN 1 ELSE 0 END) as status_inconsistent,
          SUM(CASE WHEN entry IS NULL OR sl IS NULL OR tp1 IS NULL       THEN 1 ELSE 0 END) as price_defects
        FROM APEX_MASTER_TRADE {WHERE}
    """).fetchone()
    print(f"\n{'='*50}\n  ANOMALIES REPORT\n{'='*50}")
    for label, key in [
        ("closed without close_price","no_close_price"),
        ("closed without pnl_usdt","no_pnl_usdt"),
        ("closed without event_context","no_event_ctx"),
        ("closed without close_reason","no_close_reason"),
        ("status inconsistent","status_inconsistent"),
        ("price defects","price_defects"),
    ]:
        val = row[key] if row else "—"
        print(f"  {label:<35} {str(val):>4}  {'✅' if val == 0 else '🔴'}")
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", choices=["coverage","lifecycle","anomalies"], required=True)
    args = parser.parse_args()
    {"coverage":report_coverage,"lifecycle":report_lifecycle,"anomalies":report_anomalies}[args.report]()
    print()
