"""
APEX PROTOCOL™ — Test Fill v1
Заполняет все NULL-поля в APEX_MASTER_TRADE для режима test1.
Не меняет структуру таблицы, не удаляет данные.
"""

import sqlite3
import shutil
import random
import math
from datetime import datetime, timedelta

DB_PATH = "/root/apex-system/storage/db/sqlite/apex.db"
BACKUP_PATH = DB_PATH + f".backup_pre_testfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ============================================================
# STEP 0: BACKUP
# ============================================================
shutil.copy2(DB_PATH, BACKUP_PATH)
print(f"[BACKUP] {BACKUP_PATH}")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

total = cur.execute("SELECT COUNT(*) FROM APEX_MASTER_TRADE").fetchone()[0]
print(f"[INFO] Строк в таблице: {total}")

# ============================================================
# STEP 1: ЗАКРЫТЬ ОТКРЫТЫЕ СДЕЛКИ (closed_at IS NULL)
# ============================================================
open_rows = cur.execute("""
    SELECT id, trade_id, symbol, direction, fill_price, sl, tp1, opened_at
    FROM APEX_MASTER_TRADE WHERE closed_at IS NULL
""").fetchall()

print(f"[STEP1] Открытых сделок: {len(open_rows)}")

for row in open_rows:
    fid = row["id"]
    fp = row["fill_price"]
    sl = row["sl"]
    tp1 = row["tp1"]
    direction = row["direction"]
    opened_at = row["opened_at"]

    # Случайный исход: 50% TP1, 30% SL, 20% TIMEOUT
    roll = random.random()
    if roll < 0.5:
        close_reason = "TP1"
        close_price = tp1
    elif roll < 0.8:
        close_reason = "SL"
        close_price = sl
    else:
        close_reason = "TIMEOUT"
        # Закрытие между entry и tp1/sl
        if direction == "long":
            close_price = round(fp + random.uniform(-0.001, 0.001) * fp, 8)
        else:
            close_price = round(fp + random.uniform(-0.001, 0.001) * fp, 8)

    # PNL
    if direction == "long":
        pnl_pct = round((close_price - fp) / fp * 100, 4)
    else:
        pnl_pct = round((fp - close_price) / fp * 100, 4)

    risk_usdt_val = 10.0  # test default
    pnl_usdt = round(pnl_pct * risk_usdt_val / 1.0, 4)

    # Closed_at: opened + random 5-45 min
    try:
        opened_dt = datetime.fromisoformat(opened_at)
    except ValueError:
        opened_dt = datetime.strptime(opened_at[:19], "%Y-%m-%d %H:%M:%S")
    minutes = random.randint(5, 45)
    closed_dt = opened_dt + timedelta(minutes=minutes)
    closed_at = closed_dt.strftime("%Y-%m-%dT%H:%M:%S")
    finalized_at = closed_at

    cur.execute("""
        UPDATE APEX_MASTER_TRADE SET
            closed_at = ?, close_price = ?, close_reason = ?,
            pnl_pct = ?, pnl_usdt = ?, finalized_at = ?
        WHERE id = ?
    """, (closed_at, close_price, close_reason, pnl_pct, pnl_usdt, finalized_at, fid))

conn.commit()
print(f"[STEP1] Закрыто: {len(open_rows)} сделок")

# ============================================================
# STEP 2: ЗАПОЛНИТЬ close_price для MANUAL_STOP строк без него
# ============================================================
manual_no_price = cur.execute("""
    SELECT id, fill_price, direction, sl, tp1
    FROM APEX_MASTER_TRADE WHERE close_reason = 'MANUAL_STOP' AND close_price IS NULL
""").fetchall()

for row in manual_no_price:
    fp = row["fill_price"]
    # Закрытие близко к entry
    cp = round(fp * (1 + random.uniform(-0.002, 0.002)), 8)
    d = row["direction"]
    if d == "long":
        pnl_pct = round((cp - fp) / fp * 100, 4)
    else:
        pnl_pct = round((fp - cp) / fp * 100, 4)
    pnl_usdt = round(pnl_pct * 10.0, 4)

    cur.execute("""
        UPDATE APEX_MASTER_TRADE SET close_price = ?, pnl_pct = COALESCE(pnl_pct, ?)
        WHERE id = ?
    """, (cp, pnl_pct, row["id"]))

conn.commit()
print(f"[STEP2] MANUAL_STOP без close_price исправлено: {len(manual_no_price)}")

# ============================================================
# STEP 3: ЗАПОЛНИТЬ finalized_at где NULL
# ============================================================
cur.execute("""
    UPDATE APEX_MASTER_TRADE
    SET finalized_at = COALESCE(closed_at, strftime('%Y-%m-%dT%H:%M:%S', 'now'))
    WHERE finalized_at IS NULL
""")
conn.commit()
print(f"[STEP3] finalized_at заполнен")

# ============================================================
# STEP 4: МАССОВОЕ ЗАПОЛНЕНИЕ ВСЕХ NULL-ПОЛЕЙ
# ============================================================

rows = cur.execute("SELECT * FROM APEX_MASTER_TRADE").fetchall()

for row in rows:
    rid = row["id"]
    fp = row["fill_price"] or 1.0
    sl = row["sl"] or fp * 0.99
    tp1 = row["tp1"] or fp * 1.01
    tp2 = row["tp2"]
    tp3 = row["tp3"]
    direction = row["direction"] or "long"
    opened_at = row["opened_at"]
    closed_at = row["closed_at"]
    close_price = row["close_price"] or fp
    close_reason = row["close_reason"] or "TIMEOUT"
    pnl_usdt = row["pnl_usdt"] or 0.0
    pnl_pct = row["pnl_pct"] or 0.0
    commission = row["commission"] or 0.0
    leverage = row["leverage"] or 10
    symbol = row["symbol"] or "TEST/USDT"
    strategy = row["strategy"] or "TOP20_1M_BREAKOUT_v1"
    rr = row["rr"] or 0.0

    try:
        opened_dt = datetime.fromisoformat(opened_at)
    except Exception:
        opened_dt = datetime.strptime(opened_at[:19], "%Y-%m-%d %H:%M:%S")
    try:
        closed_dt = datetime.fromisoformat(closed_at) if closed_at else opened_dt + timedelta(minutes=15)
    except Exception:
        closed_dt = datetime.strptime(closed_at[:19], "%Y-%m-%d %H:%M:%S")

    duration_min = int((closed_dt - opened_dt).total_seconds() / 60)

    # --- SEC2: STRATEGY ---
    strategy_family = strategy.split("_v")[0] if "_v" in strategy else strategy
    strategy_version = strategy.split("_v")[1] if "_v" in strategy else "1"
    setup_name = strategy_family
    setup_variant = "default"

    # --- SEC3: SESSION ---
    hour = opened_dt.hour
    if 0 <= hour < 8:
        session_label = "TOKYO"
        session_group = "ASIA"
    elif 8 <= hour < 13:
        session_label = "LONDON"
        session_group = "EUROPE"
    elif 13 <= hour < 21:
        session_label = "NEW_YORK"
        session_group = "US"
    else:
        session_label = "SYDNEY"
        session_group = "ASIA"

    # session_name уже содержит RUN-..., не трогаем его (upstream fix)
    sub_session = "MAIN"
    pre_session_flag = 0
    overlap_flag = 1 if (13 <= hour <= 16) else 0
    session_open_minutes = (opened_dt.hour * 60 + opened_dt.minute) % 480
    session_date_key = opened_dt.strftime("%Y-%m-%d")

    # --- SEC5: DURATION ---
    if duration_min <= 5:
        holding_bucket = "0-5m"
    elif duration_min <= 15:
        holding_bucket = "5-15m"
    elif duration_min <= 30:
        holding_bucket = "15-30m"
    elif duration_min <= 60:
        holding_bucket = "30-60m"
    else:
        holding_bucket = "60m+"

    # minutes_to_tp1 / minutes_to_sl — если TP/SL достигнут, = duration, иначе NULL→0
    if close_reason in ("TP1", "TP2", "TP3"):
        minutes_to_tp1 = duration_min
        minutes_to_sl = 0
        tp_level_reached = int(close_reason[-1])
    elif close_reason == "SL":
        minutes_to_tp1 = 0
        minutes_to_sl = duration_min
        tp_level_reached = 0
    else:
        minutes_to_tp1 = 0
        minutes_to_sl = 0
        tp_level_reached = 0

    # --- SEC7: RISK ---
    entry_dist_sl = abs(fp - sl) / fp * 100 if fp > 0 else 0
    risk_pct_calc = round(entry_dist_sl * leverage, 4)
    account_bal = 10000.0
    risk_usdt_calc = round(account_bal * risk_pct_calc / 100, 4) if risk_pct_calc > 0 else 10.0
    risk_per_pct_plan = 1.0
    risk_per_usdt_plan = round(account_bal * risk_per_pct_plan / 100, 2)

    # actual_rr = pnl / risk distance
    risk_dist = abs(fp - sl) if abs(fp - sl) > 0 else 0.0001
    actual_rr_val = round(abs(close_price - fp) / risk_dist, 4) if close_price else 0
    if pnl_usdt < 0:
        actual_rr_val = -actual_rr_val
    r_multiple = actual_rr_val
    actual_loss = round(abs(pnl_usdt), 4) if pnl_usdt < 0 else 0.0

    # --- SEC8: EXECUTION QUALITY ---
    entry_type = "MARKET"
    entry_delay_sec = round(random.uniform(0.1, 2.0), 2)
    entry_dist_sl_pct = round(entry_dist_sl, 4)
    entry_dist_tp1_pct = round(abs(fp - tp1) / fp * 100, 4) if fp > 0 else 0

    # MFE / MAE — mock for test
    if direction == "long":
        mfe = round(max(0, (close_price - fp) / fp * 100) + random.uniform(0, 0.5), 4)
        mae = round(random.uniform(0, entry_dist_sl), 4)
    else:
        mfe = round(max(0, (fp - close_price) / fp * 100) + random.uniform(0, 0.5), 4)
        mae = round(random.uniform(0, entry_dist_sl), 4)

    # --- SEC9: EXIT ---
    exit_route_map = {
        "TP1": "TP", "TP2": "TP", "TP3": "TP",
        "SL": "SL", "TIMEOUT": "TIME_EXIT", "MANUAL_STOP": "MANUAL",
        "FORCE_CLOSE": "SYSTEM", "EMERGENCY": "SYSTEM"
    }
    exit_route = exit_route_map.get(close_reason, "UNKNOWN")
    trigger_side_map = {
        "TP1": "TP", "TP2": "TP", "TP3": "TP",
        "SL": "SL", "TIMEOUT": "TIME", "MANUAL_STOP": "MANUAL",
        "FORCE_CLOSE": "SYSTEM", "EMERGENCY": "SYSTEM"
    }
    close_trigger_side = trigger_side_map.get(close_reason, "UNKNOWN")
    exit_reason_code = close_reason
    exit_reason_text = f"Closed by {close_reason}"
    forced_exit = 1 if close_reason in ("FORCE_CLOSE", "EMERGENCY", "SYSTEM_STOP") else 0
    manual_interv = 1 if close_reason == "MANUAL_STOP" else 0
    is_finalized = 1 if (closed_at and close_reason and close_price and pnl_usdt is not None) else 0

    # --- SEC10: PNL ---
    fees_open = round(fp * (row["size"] or 1) * 0.0004, 4)
    fees_close = round(close_price * (row["size"] or 1) * 0.0004, 4)
    total_fees = round(fees_open + fees_close, 4)
    funding = 0.0
    gross_pnl_pct = pnl_pct
    gross_pnl_usdt = pnl_usdt
    net_pnl_pct = round(pnl_pct - (total_fees / account_bal * 100), 4)
    net_pnl_usdt = round(pnl_usdt - total_fees, 4)

    if pnl_usdt > 0:
        result_label = "WIN"
    elif pnl_usdt < 0:
        result_label = "LOSS"
    else:
        result_label = "BE"

    net_result_class = result_label
    if abs(pnl_usdt) < 1:
        pnl_bucket = "MICRO"
    elif abs(pnl_usdt) < 5:
        pnl_bucket = "SMALL"
    elif abs(pnl_usdt) < 20:
        pnl_bucket = "MEDIUM"
    else:
        pnl_bucket = "LARGE"

    # --- SEC11: SIGNAL QUALITY ---
    entry_signal_score = round(random.uniform(50, 95), 1)
    scanner_score = round(random.uniform(60, 100), 1)
    filter_score = round(random.uniform(50, 100), 1)
    confidence_score = round((entry_signal_score + scanner_score + filter_score) / 3, 1)
    if confidence_score >= 80:
        setup_grade = "A"
    elif confidence_score >= 65:
        setup_grade = "B"
    else:
        setup_grade = "C"
    entry_quality_flag = "GOOD" if confidence_score >= 70 else "FAIR"

    # --- SEC12: ENTRY REASONS ---
    entry_reason_code = "BREAKOUT"
    entry_reason_text = "1m breakout confirmed"
    scanner_passed = 1
    filter_passed = 1
    exec_attempted = 1
    exec_success = 1
    reject_reason_stage = "NONE"
    reject_reason_code = "NONE"
    reject_reason_text = "No rejection"

    # --- SEC13: MARKET ---
    exchange_name = "bybit"
    market_type = "swap"
    instrument_type = "linear"
    # Tick/step from symbol
    if "BTC" in symbol:
        tick_size = 0.1
        step_size = 0.001
        min_notional = 5.0
    elif "ETH" in symbol:
        tick_size = 0.01
        step_size = 0.01
        min_notional = 5.0
    else:
        tick_size = 0.0001
        step_size = 0.1
        min_notional = 5.0

    # --- SEC14: SERVICE ---
    calc_version = "test_fill_v1"
    row_status = "FINAL" if is_finalized else "PARTIAL"
    if closed_at and close_price and pnl_usdt is not None and close_reason:
        data_quality_flag = "OK"
    else:
        data_quality_flag = "MISSING_FIELDS"
    analytics_ready = 1 if row_status == "FINAL" else 0

    # --- SEC15: DASHBOARD ---
    dashboard_sort_ts = closed_at if closed_at else opened_at
    dashboard_group_date = closed_dt.strftime("%Y-%m-%d") if closed_at else opened_dt.strftime("%Y-%m-%d")
    if row_status != "FINAL":
        dash_color = "GRAY"
    elif pnl_usdt > 0:
        dash_color = "GREEN"
    elif pnl_usdt < 0:
        dash_color = "RED"
    else:
        dash_color = "YELLOW"
    dash_priority = 1 if row_status == "FINAL" else (2 if row_status == "PARTIAL" else 3)
    dashboard_note = ""

    # --- SEC16: SMC_ORB ---
    market_phase = random.choice(["EXPANSION", "RETRACEMENT", "CONSOLIDATION", "DISTRIBUTION"])
    bos_present = random.randint(0, 1)
    choch_present = random.randint(0, 1)
    entry_in_discount = random.randint(0, 1)
    entry_near_ob = random.randint(0, 1)
    entry_near_fvg = random.randint(0, 1)
    orb_high = round(fp * 1.005, 8)
    orb_low = round(fp * 0.995, 8)
    orb_mid = round(fp, 8)
    retest_price = round(fp * (1 + random.uniform(-0.002, 0.002)), 8)

    # --- source_pipeline ---
    source_pipeline = row["session_name"] if row["session_name"] and row["session_name"].startswith("RUN-") else "RUN-UNKNOWN"

    updated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    cur.execute("""
        UPDATE APEX_MASTER_TRADE SET
            source_pipeline      = COALESCE(source_pipeline, ?),
            strategy_family      = COALESCE(strategy_family, ?),
            strategy_version     = COALESCE(strategy_version, ?),
            setup_name           = COALESCE(setup_name, ?),
            setup_variant        = COALESCE(setup_variant, ?),
            session_group        = COALESCE(session_group, ?),
            sub_session          = COALESCE(sub_session, ?),
            event_context        = COALESCE(event_context, ?),
            pre_session_flag     = COALESCE(pre_session_flag, ?),
            overlap_flag         = COALESCE(overlap_flag, ?),
            session_open_minutes_from_start = COALESCE(session_open_minutes_from_start, ?),
            session_date_key     = COALESCE(session_date_key, ?),
            updated_at           = ?,
            closed_date          = COALESCE(closed_date, DATE(closed_at)),
            closed_hour          = COALESCE(closed_hour, CAST(strftime('%H', closed_at) AS INTEGER)),
            duration_minutes     = COALESCE(duration_minutes, ?),
            minutes_to_close     = COALESCE(minutes_to_close, ?),
            minutes_to_tp1       = COALESCE(minutes_to_tp1, ?),
            minutes_to_sl        = COALESCE(minutes_to_sl, ?),
            holding_bucket       = COALESCE(holding_bucket, ?),
            account_balance_snapshot = COALESCE(account_balance_snapshot, ?),
            risk_model_name      = COALESCE(risk_model_name, ?),
            risk_per_trade_pct_plan = COALESCE(risk_per_trade_pct_plan, ?),
            risk_per_trade_usdt_plan = COALESCE(risk_per_trade_usdt_plan, ?),
            actual_loss_usdt     = COALESCE(actual_loss_usdt, ?),
            actual_rr            = COALESCE(actual_rr, ?),
            r_multiple           = COALESCE(r_multiple, ?),
            entry_type           = COALESCE(entry_type, ?),
            entry_delay_sec      = COALESCE(entry_delay_sec, ?),
            entry_distance_to_sl_pct  = COALESCE(entry_distance_to_sl_pct, ?),
            entry_distance_to_tp1_pct = COALESCE(entry_distance_to_tp1_pct, ?),
            max_favorable_excursion_mfe = COALESCE(max_favorable_excursion_mfe, ?),
            max_adverse_excursion_mae   = COALESCE(max_adverse_excursion_mae, ?),
            close_price          = COALESCE(close_price, ?),
            close_reason         = COALESCE(close_reason, ?),
            exit_route           = COALESCE(exit_route, ?),
            exit_reason_code     = COALESCE(exit_reason_code, ?),
            exit_reason_text     = COALESCE(exit_reason_text, ?),
            close_trigger_side   = COALESCE(close_trigger_side, ?),
            forced_exit_flag     = COALESCE(forced_exit_flag, ?),
            manual_intervention_flag = COALESCE(manual_intervention_flag, ?),
            tp_level_reached_max = COALESCE(tp_level_reached_max, ?),
            is_finalized         = COALESCE(is_finalized, ?),
            fees_open_usdt       = COALESCE(fees_open_usdt, ?),
            fees_close_usdt      = COALESCE(fees_close_usdt, ?),
            total_fees_usdt      = COALESCE(total_fees_usdt, ?),
            funding_usdt         = COALESCE(funding_usdt, ?),
            gross_pnl_pct        = COALESCE(gross_pnl_pct, ?),
            net_pnl_pct          = COALESCE(net_pnl_pct, ?),
            pnl_pct              = COALESCE(pnl_pct, ?),
            gross_pnl_usdt       = COALESCE(gross_pnl_usdt, ?),
            net_pnl_usdt         = COALESCE(net_pnl_usdt, ?),
            pnl_usdt             = COALESCE(pnl_usdt, ?),
            result_label         = COALESCE(result_label, ?),
            net_result_class     = COALESCE(net_result_class, ?),
            pnl_bucket           = COALESCE(pnl_bucket, ?),
            entry_signal_score   = COALESCE(entry_signal_score, ?),
            scanner_score        = COALESCE(scanner_score, ?),
            filter_score         = COALESCE(filter_score, ?),
            confidence_score     = COALESCE(confidence_score, ?),
            setup_grade          = COALESCE(setup_grade, ?),
            entry_quality_flag   = COALESCE(entry_quality_flag, ?),
            entry_reason_code    = COALESCE(entry_reason_code, ?),
            entry_reason_text    = COALESCE(entry_reason_text, ?),
            scanner_passed       = COALESCE(scanner_passed, ?),
            filter_passed        = COALESCE(filter_passed, ?),
            execution_attempted  = COALESCE(execution_attempted, ?),
            execution_success    = COALESCE(execution_success, ?),
            reject_reason_stage  = COALESCE(reject_reason_stage, ?),
            reject_reason_code   = COALESCE(reject_reason_code, ?),
            reject_reason_text   = COALESCE(reject_reason_text, ?),
            exchange_name        = COALESCE(exchange_name, ?),
            market_type          = COALESCE(market_type, ?),
            instrument_type      = COALESCE(instrument_type, ?),
            tick_size            = COALESCE(tick_size, ?),
            step_size            = COALESCE(step_size, ?),
            min_notional         = COALESCE(min_notional, ?),
            calc_version         = ?,
            row_status           = ?,
            data_quality_flag    = ?,
            analytics_ready_flag = ?,
            dashboard_group_date = COALESCE(dashboard_group_date, ?),
            dashboard_sort_ts    = COALESCE(dashboard_sort_ts, ?),
            dashboard_color_flag = COALESCE(dashboard_color_flag, ?),
            dashboard_priority   = COALESCE(dashboard_priority, ?),
            dashboard_note       = COALESCE(dashboard_note, ?),
            is_visible_in_dashboard = COALESCE(is_visible_in_dashboard, 1),
            market_phase         = COALESCE(market_phase, ?),
            bos_present          = COALESCE(bos_present, ?),
            choch_present        = COALESCE(choch_present, ?),
            entry_in_discount    = COALESCE(entry_in_discount, ?),
            entry_near_ob        = COALESCE(entry_near_ob, ?),
            entry_near_fvg       = COALESCE(entry_near_fvg, ?),
            orb_high             = COALESCE(orb_high, ?),
            orb_low              = COALESCE(orb_low, ?),
            orb_mid              = COALESCE(orb_mid, ?),
            retest_price         = COALESCE(retest_price, ?)
        WHERE id = ?
    """, (
        source_pipeline,
        strategy_family, strategy_version, setup_name, setup_variant,
        session_group, sub_session, session_label,
        pre_session_flag, overlap_flag, session_open_minutes, session_date_key,
        updated_at,
        duration_min, duration_min, minutes_to_tp1, minutes_to_sl, holding_bucket,
        account_bal, "fixed_risk_v1", risk_per_pct_plan, risk_per_usdt_plan,
        actual_loss, actual_rr_val, r_multiple,
        entry_type, entry_delay_sec, entry_dist_sl_pct, entry_dist_tp1_pct,
        mfe, mae,
        close_price, close_reason, exit_route,
        exit_reason_code, exit_reason_text, close_trigger_side,
        forced_exit, manual_interv, tp_level_reached, is_finalized,
        fees_open, fees_close, total_fees, funding,
        gross_pnl_pct, net_pnl_pct, pnl_pct,
        gross_pnl_usdt, net_pnl_usdt, pnl_usdt,
        result_label, net_result_class, pnl_bucket,
        entry_signal_score, scanner_score, filter_score, confidence_score,
        setup_grade, entry_quality_flag,
        entry_reason_code, entry_reason_text,
        scanner_passed, filter_passed, exec_attempted, exec_success,
        reject_reason_stage, reject_reason_code, reject_reason_text,
        exchange_name, market_type, instrument_type,
        tick_size, step_size, min_notional,
        calc_version, row_status, data_quality_flag, analytics_ready,
        dashboard_group_date, dashboard_sort_ts, dash_color, dash_priority, dashboard_note,
        market_phase, bos_present, choch_present,
        entry_in_discount, entry_near_ob, entry_near_fvg,
        orb_high, orb_low, orb_mid, retest_price,
        rid
    ))

conn.commit()
print(f"[STEP4] Все {total} строк обработаны")

# ============================================================
# VERIFY
# ============================================================
cols = cur.execute("PRAGMA table_info(APEX_MASTER_TRADE)").fetchall()
real_cols = [c["name"] for c in cols if not c["name"].startswith("_SEC")]

total_cells = 0
null_cells = 0
print("\n" + "=" * 60)
print(f"{'COLUMN':<35} {'FILLED':>6} {'NULL':>6} {'%':>7}")
print("=" * 60)

for col in real_cols:
    r = cur.execute(f"""
        SELECT COUNT(*) as t,
               SUM(CASE WHEN [{col}] IS NULL THEN 1 ELSE 0 END) as n
        FROM APEX_MASTER_TRADE
    """).fetchone()
    t, n = r["t"], r["n"]
    filled = t - n
    pct = round((filled / t) * 100, 1) if t > 0 else 0
    total_cells += t
    null_cells += n
    marker = "" if pct >= 100 else " <<<" if pct < 99 else ""
    print(f"  {col:<33} {filled:>6} {n:>6} {pct:>6.1f}%{marker}")

print("=" * 60)
filled_total = total_cells - null_cells
pct_total = round((filled_total / total_cells) * 100, 2) if total_cells > 0 else 0
print(f"  TOTAL CELLS: {total_cells}")
print(f"  FILLED:      {filled_total}")
print(f"  NULL:        {null_cells}")
print(f"  FILL RATE:   {pct_total}%")
print("=" * 60)

conn.close()
print("[DONE]")
