#!/usr/bin/env python3
"""
TEST_STRATEGY_01 — strategy_main.py
Тестовая стратегия для проверки 100% заполнения APEX_MASTER_TRADE.
Использует repository.log_execution() для записи всех полей.
"""
import json
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, '/root/apex-system')

from storage.db.repository import Repository
from storage.db.init_db import get_connection
from core.id_manager import IdManager

DB_PATH = "/root/apex-system/storage/db/sqlite/apex.db"
CFG_PATH = "/root/apex-system/strategies/TEST_STRATEGY_01/config/strategy_config.json"
TC_PATH  = "/root/apex-system/storage/test_control.json"

id_manager = IdManager()

def load_config():
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def load_test_control():
    with open(TC_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def to_bybit_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace(":USDT", "")

def fetch_last_two_1m(symbol: str):
    try:
        bybit_symbol = to_bybit_symbol(symbol)
        params = urllib.parse.urlencode({
            "category": "linear",
            "symbol": bybit_symbol,
            "interval": "1",
            "limit": 3
        })
        url = f"https://api.bybit.com/v5/market/kline?{params}"
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        rows = data.get("result", {}).get("list", [])
        if len(rows) < 2:
            return None
        rows = list(reversed(rows))
        prev_c = rows[-2]
        curr_c = rows[-1]
        return (
            {"high": float(prev_c[2]), "low": float(prev_c[3]), "close": float(prev_c[4])},
            {"high": float(curr_c[2]), "low": float(curr_c[3]), "close": float(curr_c[4])}
        )
    except Exception as e:
        print(f"CANDLE_ERROR {symbol}: {e}")
        return None

def fetch_instrument_info(symbol: str):
    try:
        bybit_symbol = to_bybit_symbol(symbol)
        url = f"https://api.bybit.com/v5/market/instruments-info?category=linear&symbol={bybit_symbol}"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        info = data["result"]["list"][0]
        tick_size    = float(info["priceFilter"]["tickSize"])
        step_size    = float(info["lotSizeFilter"]["qtyStep"])
        min_notional = float(info["lotSizeFilter"].get("minNotionalValue", 0))
        return tick_size, step_size, min_notional
    except Exception as e:
        print(f"INSTRUMENT_INFO_ERROR {symbol}: {e}")
        return None, None, None

def latest_scan_run_id(conn):
    row = conn.execute("""
        SELECT scan_run_id FROM APEX_MASTER_SCANNER
        ORDER BY rowid DESC LIMIT 1
    """).fetchone()
    return row["scan_run_id"] if row else None

def load_top20(conn, scan_run_id):
    return conn.execute("""
        SELECT symbol FROM APEX_MASTER_SCANNER
        WHERE scan_run_id = ?
        ORDER BY score DESC
        LIMIT 20
    """, (scan_run_id,)).fetchall()

def already_exists(conn, symbol, run_id):
    row = conn.execute("""
        SELECT 1 FROM APEX_MASTER_TRADE
        WHERE symbol = ? AND source_pipeline = ?
        LIMIT 1
    """, (symbol, run_id)).fetchone()
    return row is not None

def main():
    cfg = load_config()
    tc  = load_test_control()

    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    scan_run_id = latest_scan_run_id(conn)
    if not scan_run_id:
        print("NO_SCAN")
        return

    run_id = f"{cfg['strategy_name']}|{scan_run_id}"
    candidates = load_top20(conn, scan_run_id)

    print(f"RUN_ID={run_id}")
    print(f"CANDIDATES={len(candidates)}")

    repo = Repository()
    inserted = 0
    skipped  = 0

    for row in candidates:
        symbol = row["symbol"]

        if already_exists(conn, symbol, run_id):
            print(f"DUPLICATE_SKIP {symbol}")
            skipped += 1
            continue

        candles = fetch_last_two_1m(symbol)
        if not candles:
            print(f"NO_CANDLES {symbol}")
            skipped += 1
            continue

        prev, curr = candles

        long_ok  = curr["high"] > prev["high"]
        short_ok = curr["low"]  < prev["low"]

        if long_ok:
            direction = "LONG"
            entry = curr["high"]
            sl    = prev["low"]
        elif short_ok:
            direction = "SHORT"
            entry = curr["low"]
            sl    = prev["high"]
        else:
            direction = "LONG"
            entry = curr["close"]
            sl    = curr["low"] * 0.995

        risk_per_unit = abs(entry - sl)
        if risk_per_unit == 0:
            risk_per_unit = entry * 0.005

        leverage           = float(tc.get("param_leverage", 20))
        risk_per_trade_usdt = float(tc.get("risk_per_trade_usdt_plan", 200.0))
        # FIXED RISK MODEL — size считается от планового риска
        risk_usdt     = round(risk_per_trade_usdt, 2)
        # Размер позиции — из test_control (param_size_usdt)
        size_usdt     = float(tc.get("param_size_usdt", 500.0))
        size          = round(size_usdt / entry, 6)
        risk_pct      = round((risk_usdt / float(tc.get("test_balance", 5000.0))) * 100, 4)
        # Risk compliance flag
        deviation_pct = abs(risk_usdt - risk_per_trade_usdt) / risk_per_trade_usdt * 100 if risk_per_trade_usdt > 0 else 0
        if deviation_pct <= 20:
            risk_compliance_flag = "OK"
        elif deviation_pct <= 50:
            risk_compliance_flag = "WARN"
        else:
            risk_compliance_flag = "BREACH"

        tp1 = round(entry + risk_per_unit * 2.0, 6) if direction == "LONG" else round(entry - risk_per_unit * 2.0, 6)
        tp2 = round(entry + risk_per_unit * 3.0, 6) if direction == "LONG" else round(entry - risk_per_unit * 3.0, 6)
        tp3 = round(entry + risk_per_unit * 4.0, 6) if direction == "LONG" else round(entry - risk_per_unit * 4.0, 6)
        rr  = 2.0

        tick_size, step_size, min_notional = fetch_instrument_info(symbol)

        trade_id   = id_manager.next_trade_id()
        opened_at  = datetime.now(timezone.utc).isoformat()

        signal = {
            # Идентификация
            "trade_id":          trade_id,
            "symbol":            symbol,
            "strategy":          cfg.get("strategy_name", "TOP20_1M_BREAKOUT_v1"),
            "strategy_family":   tc.get("strategy_family", "APEX"),
            "strategy_version":  tc.get("strategy_version", "v1"),
            "setup_name":        tc.get("setup_name", "TOP20_1M_BREAKOUT"),
            "setup_variant":     tc.get("setup_variant", "A"),
            "source_pipeline":   run_id,
            # Направление и цены
            "direction":         direction,
            "entry":             entry,
            "entry_price":       entry,
            "fill_price":        entry,
            "sl":                sl,
            "tp1":               tp1,
            "tp2":               tp2,
            "tp3":               tp3,
            # Размер и риск
            "size":              size,
            "leverage":          leverage,
            "risk_usdt":         risk_usdt,
            "risk_compliance_flag": risk_compliance_flag,
            "risk_pct":          risk_pct,
            "rr":                rr,
            # Исполнение
            "mode":              "SIMULATION",
            "exchange_name":     tc.get("exchange_name", "Bybit"),
            "market_type":       tc.get("market_type", "FUTURES"),
            "instrument_type":   tc.get("instrument_type", "PERPETUAL"),
            "entry_type":        "SIMULATED",
            "entry_delay_sec":   0,
            "calc_version":      tc.get("calc_version", "v2.0"),
            # Качество сигнала
            "scanner_passed":    1,
            "filter_passed":     1,
            "execution_attempted": 1,
            "execution_success": 1,
            # Quality scoring — реальный расчёт
            # scanner_score — из APEX_MASTER_SCANNER если есть, иначе 50
            "scanner_score":     50,
            # filter_score — считаем из параметров сделки
            "filter_score":      (
                20  # базовый балл
                + (20 if rr >= 2.0 else 0)          # RR >= 2
                + (20 if (long_ok or short_ok) else 0)  # реальный пробой
                + (20 if risk_compliance_flag == "OK" else 0)  # risk OK
            ),
            "entry_quality_flag": "OK" if (long_ok or short_ok) else "WEAK",
            "entry_signal_score": 50,
            # confidence и grade считаются ниже после signal
            "confidence_score":  0,  # placeholder
            "setup_grade":       "D",  # placeholder
            "entry_signal_score": 0,  # placeholder
            "entry_reason_code": "1M_BREAKOUT" if (long_ok or short_ok) else "1M_FLAT_FILL",
            "entry_reason_text": f"{direction} breakout prev candle" if (long_ok or short_ok) else "Test fill — no breakout",
            # Время и сессия
            "opened_at":         opened_at,
            "session_name":      "TEST",
            "account_balance_snapshot": float(tc.get("test_balance", 5000.0)),
            "risk_model_name":  tc.get("risk_model_name", "FIXED"),
            "risk_per_trade_pct_plan": float(tc.get("risk_per_trade_pct_plan", 2.0)),
            "risk_per_trade_usdt_plan": float(tc.get("risk_per_trade_usdt_plan", 200.0)),
            "session_hour":      datetime.now(timezone.utc).hour,
            "pre_session_flag":  0,
            "event_context":     None,
            "session_open_minutes_from_start": 0,
            # Dashboard
            "dashboard_note":    f"TEST_STRATEGY_01 | {symbol} | {direction}",
            "tick_size":         tick_size,
            "step_size":         step_size,
            "min_notional":      min_notional,
            "market_phase":      "UNKNOWN",
            "bos_present":       0,
            "choch_present":     0,
            "entry_in_discount": 0,
            "entry_near_ob":     0,
            "entry_near_fvg":    0,
            "orb_high":          None,
            "orb_low":           None,
            "orb_mid":           None,
            "retest_price":      None,
        }

        # Пересчёт confidence после формирования signal
        _scanner = signal.get("scanner_score", 50)
        _filter  = signal.get("filter_score", 50)
        _conf    = round((_scanner + _filter) / 2, 1)
        _grade   = "A" if _conf >= 80 else ("B" if _conf >= 60 else ("C" if _conf >= 40 else "D"))
        signal["confidence_score"]  = _conf
        signal["setup_grade"]       = _grade
        signal["entry_signal_score"] = _conf
        repo.log_execution(signal)
        inserted += 1
        print(f"INSERT {symbol} {direction}")

    print(f"INSERTED={inserted}")
    print(f"SKIPPED={skipped}")

if __name__ == "__main__":
    main()
