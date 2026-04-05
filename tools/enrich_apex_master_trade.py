"""
APEX PROTOCOL™ — Enrichment Layer for APEX_MASTER_TRADE
Автозаполнение вычисляемых (FORMULA) колонок на основе SOURCE-полей.

Использование:
    python3 tools/enrich_apex_master_trade.py          # enrichment + отчёт
    python3 tools/enrich_apex_master_trade.py --dry-run # только отчёт, без изменений
    python3 tools/enrich_apex_master_trade.py --report  # отчёт до/после

Идемпотентный: обновляет только строки, где целевые поля NULL/пустые.
Не затирает SOURCE-поля.
"""

import sqlite3
import sys
import os

DB_PATH = "/root/apex-system/storage/db/sqlite/apex.db"

# ── Все enrichment UPDATE-блоки ────────────────────────────────────────────
# Каждый блок: (название, SQL UPDATE)
# WHERE-условие гарантирует идемпотентность: обновляем только NULL/пустые

ENRICHMENT_QUERIES = [

    # ═══════════════════════════════════════════════════════════════════════
    # SEC3: SESSION
    # ═══════════════════════════════════════════════════════════════════════

    ("session_group", """
        UPDATE APEX_MASTER_TRADE SET session_group =
            CASE
                WHEN UPPER(COALESCE(session_name,'')) IN ('ASIA','HONG_KONG','TOKYO') THEN 'ASIA'
                WHEN UPPER(COALESCE(session_name,'')) IN ('LONDON','EUROPE') THEN 'EUROPE'
                WHEN UPPER(COALESCE(session_name,'')) IN ('NEW_YORK','US','AMERICA') THEN 'AMERICA'
                ELSE 'OTHER'
            END
        WHERE (session_group IS NULL OR session_group = '')
          AND session_name IS NOT NULL
    """),

    ("sub_session", """
        UPDATE APEX_MASTER_TRADE SET sub_session =
            COALESCE(session_name, 'UNKNOWN')
        WHERE sub_session IS NULL OR sub_session = ''
    """),

    ("overlap_flag", """
        UPDATE APEX_MASTER_TRADE SET overlap_flag =
            CASE
                WHEN UPPER(COALESCE(session_name,'')) LIKE '%OVERLAP%' THEN 1
                ELSE 0
            END
        WHERE overlap_flag IS NULL
    """),

    ("session_date_key", """
        UPDATE APEX_MASTER_TRADE SET session_date_key = date(opened_at)
        WHERE (session_date_key IS NULL OR session_date_key = '')
          AND opened_at IS NOT NULL
    """),

    ("pre_session_flag", """
        UPDATE APEX_MASTER_TRADE SET pre_session_flag =
            CASE
                WHEN UPPER(COALESCE(event_context,'')) LIKE '%PRE%' THEN 1
                ELSE 0
            END
        WHERE pre_session_flag IS NULL
    """),

    # ═══════════════════════════════════════════════════════════════════════
    # SEC4: TIMES
    # ═══════════════════════════════════════════════════════════════════════

    ("created_at", """
        UPDATE APEX_MASTER_TRADE SET created_at = COALESCE(created_at, opened_at)
        WHERE (created_at IS NULL OR created_at = '')
          AND opened_at IS NOT NULL
    """),

    ("opened_date", """
        UPDATE APEX_MASTER_TRADE SET opened_date = date(opened_at)
        WHERE (opened_date IS NULL OR opened_date = '')
          AND opened_at IS NOT NULL
    """),

    ("opened_hour", """
        UPDATE APEX_MASTER_TRADE SET opened_hour = CAST(strftime('%H', opened_at) AS INTEGER)
        WHERE opened_hour IS NULL
          AND opened_at IS NOT NULL
    """),

    ("closed_date", """
        UPDATE APEX_MASTER_TRADE SET closed_date = date(closed_at)
        WHERE (closed_date IS NULL OR closed_date = '')
          AND closed_at IS NOT NULL
    """),

    ("closed_hour", """
        UPDATE APEX_MASTER_TRADE SET closed_hour = CAST(strftime('%H', closed_at) AS INTEGER)
        WHERE closed_hour IS NULL
          AND closed_at IS NOT NULL
    """),

    ("trade_day_of_week", """
        UPDATE APEX_MASTER_TRADE SET trade_day_of_week =
            CASE CAST(strftime('%w', opened_at) AS INTEGER)
                WHEN 0 THEN 'SUN'
                WHEN 1 THEN 'MON'
                WHEN 2 THEN 'TUE'
                WHEN 3 THEN 'WED'
                WHEN 4 THEN 'THU'
                WHEN 5 THEN 'FRI'
                WHEN 6 THEN 'SAT'
            END
        WHERE (trade_day_of_week IS NULL OR trade_day_of_week = '')
          AND opened_at IS NOT NULL
    """),

    # ═══════════════════════════════════════════════════════════════════════
    # SEC5: DURATION
    # ═══════════════════════════════════════════════════════════════════════

    ("duration_minutes (backfill)", """
        UPDATE APEX_MASTER_TRADE SET duration_minutes =
            CAST(ROUND((julianday(COALESCE(closed_at, finalized_at)) - julianday(opened_at)) * 1440) AS INTEGER)
        WHERE duration_minutes IS NULL
          AND opened_at IS NOT NULL
          AND (closed_at IS NOT NULL OR finalized_at IS NOT NULL)
    """),

    ("minutes_to_close (backfill)", """
        UPDATE APEX_MASTER_TRADE SET minutes_to_close =
            CAST(ROUND((julianday(COALESCE(closed_at, finalized_at)) - julianday(opened_at)) * 1440) AS INTEGER)
        WHERE minutes_to_close IS NULL
          AND opened_at IS NOT NULL
          AND (closed_at IS NOT NULL OR finalized_at IS NOT NULL)
    """),

    ("holding_bucket", """
        UPDATE APEX_MASTER_TRADE SET holding_bucket =
            CASE
                WHEN duration_minutes IS NULL THEN NULL
                WHEN duration_minutes < 5 THEN '0-5m'
                WHEN duration_minutes < 15 THEN '5-15m'
                WHEN duration_minutes < 30 THEN '15-30m'
                WHEN duration_minutes < 60 THEN '30-60m'
                WHEN duration_minutes < 120 THEN '60-120m'
                ELSE '120m+'
            END
        WHERE (holding_bucket IS NULL OR holding_bucket = '')
          AND duration_minutes IS NOT NULL
    """),

    # ═══════════════════════════════════════════════════════════════════════
    # SEC8: EXECUTION QUALITY
    # ═══════════════════════════════════════════════════════════════════════

    ("entry_distance_to_sl_pct", """
        UPDATE APEX_MASTER_TRADE SET entry_distance_to_sl_pct =
            ROUND(ABS(entry - sl) / entry * 100, 4)
        WHERE entry_distance_to_sl_pct IS NULL
          AND entry IS NOT NULL AND entry != 0
          AND sl IS NOT NULL AND sl != 0
    """),

    ("entry_distance_to_tp1_pct", """
        UPDATE APEX_MASTER_TRADE SET entry_distance_to_tp1_pct =
            ROUND(ABS(tp1 - entry) / entry * 100, 4)
        WHERE entry_distance_to_tp1_pct IS NULL
          AND entry IS NOT NULL AND entry != 0
          AND tp1 IS NOT NULL AND tp1 != 0
    """),

    ("entry_type", """
        UPDATE APEX_MASTER_TRADE SET entry_type =
            CASE
                WHEN UPPER(COALESCE(mode,'')) IN ('PAPER','SIMULATION') THEN 'SIMULATED'
                WHEN UPPER(COALESCE(mode,'')) = 'LIVE' THEN 'LIVE'
                ELSE NULL
            END
        WHERE (entry_type IS NULL OR entry_type = '')
          AND mode IS NOT NULL
    """),

    # ═══════════════════════════════════════════════════════════════════════
    # SEC9: EXIT
    # ═══════════════════════════════════════════════════════════════════════

    ("exit_reason_code", """
        UPDATE APEX_MASTER_TRADE SET exit_reason_code =
            COALESCE(close_reason, exit_route)
        WHERE (exit_reason_code IS NULL OR exit_reason_code = '')
          AND (close_reason IS NOT NULL OR exit_route IS NOT NULL)
    """),

    ("exit_reason_text", """
        UPDATE APEX_MASTER_TRADE SET exit_reason_text =
            COALESCE(close_reason, exit_route)
        WHERE (exit_reason_text IS NULL OR exit_reason_text = '')
          AND (close_reason IS NOT NULL OR exit_route IS NOT NULL)
    """),

    ("forced_exit_flag", """
        UPDATE APEX_MASTER_TRADE SET forced_exit_flag =
            CASE
                WHEN UPPER(COALESCE(close_reason,'')) IN (
                    'TIMEOUT','MANUAL_STOP','FORCE_CLOSE','EMERGENCY_EXIT',
                    'FORCE_CLOSE_120M','SESSION_END','SESSION_PROFIT_TAKE',
                    'TIMEOUT_PROFIT_60','TIME_EXIT_FORCE','TIME_EXIT_PROFIT'
                ) THEN 1
                ELSE 0
            END
        WHERE forced_exit_flag IS NULL
    """),

    ("manual_intervention_flag", """
        UPDATE APEX_MASTER_TRADE SET manual_intervention_flag =
            CASE
                WHEN UPPER(COALESCE(close_reason,'')) IN ('MANUAL_STOP','MANUAL_CLOSE') THEN 1
                ELSE 0
            END
        WHERE manual_intervention_flag IS NULL
    """),

    ("is_finalized", """
        UPDATE APEX_MASTER_TRADE SET is_finalized =
            CASE WHEN finalized_at IS NOT NULL THEN 1 ELSE 0 END
        WHERE is_finalized IS NULL
    """),

    # ═══════════════════════════════════════════════════════════════════════
    # SEC10: PNL
    # ═══════════════════════════════════════════════════════════════════════

    ("gross_pnl_pct", """
        UPDATE APEX_MASTER_TRADE SET gross_pnl_pct = pnl_pct
        WHERE gross_pnl_pct IS NULL
          AND pnl_pct IS NOT NULL
    """),

    ("net_pnl_pct", """
        UPDATE APEX_MASTER_TRADE SET net_pnl_pct = pnl_pct
        WHERE net_pnl_pct IS NULL
          AND pnl_pct IS NOT NULL
    """),

    ("gross_pnl_usdt", """
        UPDATE APEX_MASTER_TRADE SET gross_pnl_usdt = pnl_usdt
        WHERE gross_pnl_usdt IS NULL
          AND pnl_usdt IS NOT NULL
    """),

    ("net_pnl_usdt", """
        UPDATE APEX_MASTER_TRADE SET net_pnl_usdt = pnl_usdt
        WHERE net_pnl_usdt IS NULL
          AND pnl_usdt IS NOT NULL
    """),

    ("total_fees_usdt", """
        UPDATE APEX_MASTER_TRADE SET total_fees_usdt =
            CASE
                WHEN fees_open_usdt IS NOT NULL OR fees_close_usdt IS NOT NULL
                    THEN COALESCE(fees_open_usdt, 0) + COALESCE(fees_close_usdt, 0)
                WHEN commission IS NOT NULL THEN commission
                ELSE 0
            END
        WHERE total_fees_usdt IS NULL
    """),

    ("net_result_class", """
        UPDATE APEX_MASTER_TRADE SET net_result_class =
            CASE
                WHEN pnl_usdt > 0 THEN 'WIN'
                WHEN pnl_usdt < 0 THEN 'LOSS'
                ELSE 'FLAT'
            END
        WHERE (net_result_class IS NULL OR net_result_class = '')
          AND pnl_usdt IS NOT NULL
    """),

    ("pnl_bucket", """
        UPDATE APEX_MASTER_TRADE SET pnl_bucket =
            CASE
                WHEN pnl_pct IS NULL THEN NULL
                WHEN pnl_pct <= -2 THEN '<=-2%'
                WHEN pnl_pct <= -1 THEN '-2%..-1%'
                WHEN pnl_pct < 0 THEN '-1%..0%'
                WHEN pnl_pct = 0 THEN '0%'
                WHEN pnl_pct < 1 THEN '0%..1%'
                WHEN pnl_pct < 2 THEN '1%..2%'
                ELSE '>=2%'
            END
        WHERE (pnl_bucket IS NULL OR pnl_bucket = '')
          AND pnl_pct IS NOT NULL
    """),

    # ═══════════════════════════════════════════════════════════════════════
    # SEC14: SERVICE
    # ═══════════════════════════════════════════════════════════════════════

    ("data_quality_flag", """
        UPDATE APEX_MASTER_TRADE SET data_quality_flag =
            CASE
                WHEN trade_id IS NULL OR symbol IS NULL OR direction IS NULL
                     OR opened_at IS NULL OR entry IS NULL THEN 'BROKEN'
                WHEN close_reason IS NOT NULL AND close_price IS NULL
                     AND finalized_at IS NOT NULL THEN 'WARN'
                ELSE 'OK'
            END
        WHERE data_quality_flag IS NULL OR data_quality_flag = ''
    """),

    ("analytics_ready_flag", """
        UPDATE APEX_MASTER_TRADE SET analytics_ready_flag =
            CASE
                WHEN trade_id IS NOT NULL
                 AND symbol IS NOT NULL
                 AND direction IS NOT NULL
                 AND opened_at IS NOT NULL
                 AND entry IS NOT NULL
                 AND pnl_usdt IS NOT NULL
                 AND session_name IS NOT NULL
                THEN 1 ELSE 0
            END
        WHERE analytics_ready_flag IS NULL
    """),

    # ═══════════════════════════════════════════════════════════════════════
    # SEC15: DASHBOARD
    # ═══════════════════════════════════════════════════════════════════════

    ("dashboard_group_date", """
        UPDATE APEX_MASTER_TRADE SET dashboard_group_date =
            COALESCE(date(opened_at), date(created_at))
        WHERE (dashboard_group_date IS NULL OR dashboard_group_date = '')
          AND (opened_at IS NOT NULL OR created_at IS NOT NULL)
    """),

    ("dashboard_sort_ts", """
        UPDATE APEX_MASTER_TRADE SET dashboard_sort_ts =
            COALESCE(finalized_at, closed_at, opened_at)
        WHERE (dashboard_sort_ts IS NULL OR dashboard_sort_ts = '')
          AND (finalized_at IS NOT NULL OR closed_at IS NOT NULL OR opened_at IS NOT NULL)
    """),

    ("dashboard_color_flag", """
        UPDATE APEX_MASTER_TRADE SET dashboard_color_flag =
            CASE
                WHEN pnl_usdt > 0 THEN 'GREEN'
                WHEN pnl_usdt < 0 THEN 'RED'
                ELSE 'GRAY'
            END
        WHERE (dashboard_color_flag IS NULL OR dashboard_color_flag = '')
    """),

    ("dashboard_priority", """
        UPDATE APEX_MASTER_TRADE SET dashboard_priority =
            CASE
                WHEN UPPER(COALESCE(close_reason,'')) IN (
                    'MANUAL_STOP','FORCE_CLOSE','EMERGENCY_EXIT','FORCE_CLOSE_120M'
                ) THEN 1
                WHEN ABS(COALESCE(pnl_usdt, 0)) > 100 THEN 2
                ELSE 5
            END
        WHERE dashboard_priority IS NULL
    """),

    ("is_visible_in_dashboard", """
        UPDATE APEX_MASTER_TRADE SET is_visible_in_dashboard =
            CASE
                WHEN row_status IS NULL OR row_status != 'deleted' THEN 1
                ELSE 0
            END
        WHERE is_visible_in_dashboard IS NULL
    """),

    ("dashboard_note", """
        UPDATE APEX_MASTER_TRADE SET dashboard_note =
            symbol || ' | ' || COALESCE(direction, '?') || ' | ' || COALESCE(close_reason, 'OPEN')
        WHERE (dashboard_note IS NULL OR dashboard_note = '')
          AND symbol IS NOT NULL
    """),

]


# ── Колонки для отчёта ────────────────────────────────────────────────────

FORMULA_COLUMNS = [
    "session_group", "sub_session", "overlap_flag", "session_date_key",
    "pre_session_flag", "created_at", "opened_date", "opened_hour",
    "closed_date", "closed_hour", "trade_day_of_week",
    "duration_minutes", "minutes_to_close", "holding_bucket",
    "entry_distance_to_sl_pct", "entry_distance_to_tp1_pct", "entry_type",
    "exit_reason_code", "exit_reason_text", "forced_exit_flag",
    "manual_intervention_flag", "is_finalized",
    "gross_pnl_pct", "net_pnl_pct", "gross_pnl_usdt", "net_pnl_usdt",
    "total_fees_usdt", "net_result_class", "pnl_bucket",
    "data_quality_flag", "analytics_ready_flag",
    "dashboard_group_date", "dashboard_sort_ts", "dashboard_color_flag",
    "dashboard_priority", "is_visible_in_dashboard", "dashboard_note",
]


def get_null_counts(conn):
    """Возвращает dict {column_name: count_of_null_or_empty}."""
    total = conn.execute("SELECT COUNT(*) FROM APEX_MASTER_TRADE").fetchone()[0]
    result = {}
    for col in FORMULA_COLUMNS:
        # Для INTEGER-колонок проверяем только NULL; для TEXT — NULL или ''
        row = conn.execute(f"""
            SELECT COUNT(*) FROM APEX_MASTER_TRADE
            WHERE {col} IS NULL OR CAST({col} AS TEXT) = ''
        """).fetchone()
        result[col] = row[0]
    result["_total"] = total
    return result


def print_report(before, after):
    """Печатает отчёт до/после."""
    total = before["_total"]
    print(f"\n{'='*72}")
    print(f"  ENRICHMENT REPORT — APEX_MASTER_TRADE ({total} rows)")
    print(f"{'='*72}")
    print(f"{'COLUMN':<35} {'BEFORE':>8} {'AFTER':>8} {'FILLED':>8}")
    print(f"{'-'*35} {'-'*8} {'-'*8} {'-'*8}")

    total_filled = 0
    for col in FORMULA_COLUMNS:
        b = before.get(col, 0)
        a = after.get(col, 0)
        filled = b - a
        total_filled += max(0, filled)
        marker = ""
        if filled > 0:
            marker = f"  +{filled}"
        elif a > 0:
            marker = "  (still NULL)"
        print(f"{col:<35} {b:>8} {a:>8} {marker}")

    print(f"{'-'*35} {'-'*8} {'-'*8} {'-'*8}")
    print(f"{'TOTAL CELLS FILLED':<35} {'':>8} {'':>8} {total_filled:>8}")
    print(f"{'='*72}\n")


def main():
    dry_run = "--dry-run" in sys.argv
    report_only = "--report" in sys.argv

    if not os.path.exists(DB_PATH):
        print(f"ERROR: DB not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Снимок ДО
    before = get_null_counts(conn)

    if report_only:
        print_report(before, before)
        conn.close()
        return

    if dry_run:
        print("[DRY RUN] No changes will be made.\n")
        print_report(before, before)
        conn.close()
        return

    # Выполняем enrichment
    print(f"Running enrichment on {DB_PATH}...")
    for name, sql in ENRICHMENT_QUERIES:
        try:
            cursor = conn.execute(sql)
            affected = cursor.rowcount
            if affected > 0:
                print(f"  {name:<35} → {affected} rows updated")
        except Exception as e:
            print(f"  {name:<35} → ERROR: {e}")

    conn.commit()

    # Снимок ПОСЛЕ
    after = get_null_counts(conn)

    print_report(before, after)

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
