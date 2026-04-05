import logging
import os
import sqlite3

from telegram import Update
from telegram.ext import ContextTypes

from services.telegram.keyboard import (
    main_menu,
    status_menu,
    scanner_menu,
    scanner_mode_menu,
    scanner_pairs_menu,
    scanner_filters_menu,
    wau_menu,
    settings_menu,
    auto_menu,
    limits_menu,
    exchange_menu,
    strategy_menu,
    confirm_stop_menu,
    confirm_start_menu,
    confirm_reset_menu,
    confirm_exchange_on_menu,
    confirm_exchange_off_menu,
    risk_menu,
)

logger = logging.getLogger("apex.telegram")

DB_PATH = "/root/apex-system/storage/db/sqlite/apex.db"

_SEP = "────────────────"


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def _db_exists() -> bool:
    return os.path.exists(DB_PATH)


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _fmt_dt(value) -> str:
    if not value:
        return "—"
    return str(value).replace("T", " ")[:19]


def _fmt_pnl(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}"


def _fmt_minutes(value) -> str:
    """Форматирует минуты в человекочитаемый вид.
    0/None/пусто -> '—'
    < 60         -> '19м', '45м'
    >= 60        -> '1ч 00м', '1ч 18м', '4ч 55м'
    """
    if value is None or value == "—":
        return "—"
    try:
        m = int(value)
    except (ValueError, TypeError):
        return str(value)
    if m <= 0:
        return "—"
    if m < 60:
        return f"{m}м"
    h = m // 60
    rm = m % 60
    return f"{h}ч {rm:02d}м"


def _row(label: str, value, w: int = 11) -> str:
    """Строка с фиксированной шириной label-колонки для <pre> блока."""
    return f"{label:<{w}} {value}"


def _pre(lines: list[str]) -> str:
    return "<pre>" + "\n".join(lines) + "</pre>"


def _get_live_prices() -> dict[str, float]:
    """Получить текущие цены из runtime_state (обновляются position_monitor).
    Используется ТОЛЬКО для расчёта live PnL открытых позиций.
    Это реальные биржевые цены, не stale scanner data."""
    try:
        from modules.runtime_state import load_runtime_state
        state = load_runtime_state()
        return state.get("live_prices", {})
    except Exception:
        return {}


def _get_test_control() -> dict:
    try:
        from services.test_control import read as tc_read
        return tc_read() or {}
    except Exception:
        return {}


def _write_test_control(payload: dict) -> dict:
    try:
        from services.test_control import write as tc_write
        return tc_write(payload) or {}
    except Exception:
        return {}


def _get_config() -> dict:
    try:
        import json
        with open("/root/apex-system/config.json", "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _get_active_strategy() -> str:
    """config.json -> active_strategy_name, fallback test_control -> active_filter, fallback '—'."""
    cfg = _get_config()
    name = cfg.get("active_strategy_name")
    if name:
        return name
    tc = _get_test_control()
    return tc.get("active_filter", "—")


def _get_scanner_from_db() -> dict:
    """Читает агрегаты сканера из APEX_MASTER_SCANNER_SUMMARY (последний цикл)."""
    result = {
        "total_pairs": 0,
        "after_liquidity": 0,
        "after_volatility": 0,
        "after_structure": 0,
        "candidates": 0,
        "signals": 0,
        "top_score": 0,
        "last_reject_reason": "—",
    }
    if not _db_exists():
        return result
    try:
        conn = _db()
        row = conn.execute(
            """
            SELECT
                total_pairs,
                after_liquidity,
                after_volatility,
                after_structure,
                candidates,
                signals,
                top_score,
                last_reject_reason
            FROM APEX_MASTER_SCANNER_SUMMARY
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if row:
            result["total_pairs"] = _safe_int(row["total_pairs"], 0)
            result["after_liquidity"] = _safe_int(row["after_liquidity"], 0)
            result["after_volatility"] = _safe_int(row["after_volatility"], 0)
            result["after_structure"] = _safe_int(row["after_structure"], 0)
            result["candidates"] = _safe_int(row["candidates"], 0)
            result["signals"] = _safe_int(row["signals"], 0)
            result["top_score"] = _safe_float(row["top_score"], 0)
            result["last_reject_reason"] = row["last_reject_reason"] or "—"
        conn.close()
    except Exception:
        pass
    return result



def _get_exchange_stats() -> dict:
    """Статистика по каждой бирже из APEX_MASTER_TRADE за сегодня."""
    result = {}
    if not _db_exists():
        return result
    try:
        conn = _db()
        trade_ts_expr = "COALESCE(finalized_at, closed_at, opened_at)"
        rows = conn.execute(f"""
            SELECT
                LOWER(COALESCE(exchange_name, 'unknown')) AS exch,
                COUNT(*) AS trades,
                ROUND(COALESCE(SUM(pnl_usdt), 0), 2) AS pnl,
                SUM(CASE WHEN COALESCE(pnl_usdt,0) > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN COALESCE(pnl_usdt,0) < 0 THEN 1 ELSE 0 END) AS losses
            FROM APEX_MASTER_TRADE
            WHERE date({trade_ts_expr}, '+2 hours') = date('now', '+2 hours')
              AND COALESCE(close_reason,'') != 'MANUAL_CLEAR'
              AND row_status != 'active'
            GROUP BY LOWER(COALESCE(exchange_name, 'unknown'))
        """).fetchall()
        for row in rows:
            exch = row["exch"]
            closed = _safe_int(row["wins"],0) + _safe_int(row["losses"],0)
            wr = f"{round((_safe_int(row['wins'],0) / closed)*100,1)}%" if closed > 0 else "0%"
            result[exch] = {
                "trades": _safe_int(row["trades"],0),
                "pnl": _safe_float(row["pnl"],0.0),
                "wins": _safe_int(row["wins"],0),
                "losses": _safe_int(row["losses"],0),
                "wr": wr,
            }
        # активные позиции по биржам
        active_rows = conn.execute("""
            SELECT LOWER(COALESCE(exchange_name,'unknown')) AS exch, COUNT(*) AS cnt
            FROM APEX_MASTER_TRADE WHERE row_status='active'
            GROUP BY LOWER(COALESCE(exchange_name,'unknown'))
        """).fetchall()
        for row in active_rows:
            exch = row["exch"]
            if exch not in result:
                result[exch] = {"trades":0,"pnl":0.0,"wins":0,"losses":0,"wr":"0%"}
            result[exch]["active"] = _safe_int(row["cnt"],0)
        conn.close()
    except Exception as e:
        pass
    return result

def _get_session_info() -> dict:
    """Определяет текущую сессию по UTC эталону."""
    try:
        from datetime import datetime, timezone
        from core.time_manager import time_features_for_dt

        now_utc = datetime.now(timezone.utc)
        tf = time_features_for_dt(now_utc.isoformat())
        session_name = tf.get("session_name", "OFF")
        overlap = tf.get("event_overlap_london_ny", 0)

        utc_min = now_utc.hour * 60 + now_utc.minute
        _UTC_ENDS = {"ASIA": 8 * 60, "LONDON": 13 * 60, "NEW_YORK": 21 * 60}
        end_min = _UTC_ENDS.get(session_name)

        if end_min:
            left = end_min - utc_min
            time_left = _fmt_minutes(left)
            phase = "ВХОД"
            signal_allowed = True
        else:
            time_left = "—"
            phase = "Ожидание"
            signal_allowed = False

        session_display = {
            "ASIA": "Азия",
            "LONDON": "Лондон",
            "NEW_YORK": "Нью-Йорк",
            "OFF": "Закрыто",
            "MANUAL": "Ручной режим",
        }.get(session_name, session_name)

        if overlap:
            session_display += " + Overlap"

        return {
            "name": session_display,
            "phase": phase,
            "time_left": time_left,
            "signal_allowed": signal_allowed,
        }
    except Exception:
        return {
            "name": "—",
            "phase": "—",
            "time_left": "—",
            "signal_allowed": False,
        }


def _get_status_data() -> dict:
    tc = _get_test_control()
    scanner = _get_scanner_from_db()
    session = _get_session_info()

    data = {
        "торговля_вкл": bool(tc.get("trading_enabled", False)),
        "сканер_вкл": bool(tc.get("scanner_enabled", False)),
        "входы_вкл": bool(tc.get("entries_enabled", False)),
        "монитор_вкл": bool(tc.get("monitor_enabled", False)),
        "стратегия": _get_active_strategy(),
        "направление": tc.get("direction", "both"),
        "режим": tc.get("strategy_mode", tc.get("mode", "—")),
        "сессия": session.get("name", "Неизвестно"),
        "фаза": session.get("phase", "—"),
        "до_конца": session.get("time_left", "—"),
        "вход_разрешён": session.get("signal_allowed", False),
        "баланс": _safe_float(tc.get("test_balance", 0), 0.0),
        "пополнение": _safe_float(tc.get("manual_topup_total", 0), 0.0),
        "sl": tc.get("param_sl_pct", "—"),
        "tp1": tc.get("param_tp1_pct", "—"),
        "tp2": tc.get("param_tp2_pct", "—"),
        "tp3": tc.get("param_tp3_pct", "—"),
        "плечо": tc.get("param_leverage", "—"),
        "размер": tc.get("param_size_usdt", "—"),
        "риск": tc.get("param_risk_usdt", "выкл"),
        "лимит_позиций": tc.get("max_positions", 50),
        "режим_сканера": tc.get("scanner_mode_label", "Ручной"),
        "лимит_пар": _safe_int(tc.get("scanner_pairs_limit", 20), 20),
        "всего_пар": _safe_int(scanner.get("total_pairs", 0), 0),
        "после_ликв": _safe_int(scanner.get("after_liquidity", 0), 0),
        "после_вол": _safe_int(scanner.get("after_volatility", 0), 0),
        "после_структ": _safe_int(scanner.get("after_structure", 0), 0),
        "кандидаты": _safe_int(scanner.get("candidates", 0), 0),
        "сигналы": _safe_int(scanner.get("signals", 0), 0),
        "лучший_балл": _safe_float(scanner.get("top_score", 0), 0.0),
        "последний_отказ": scanner.get("last_reject_reason", "—"),
    }

    if not _db_exists():
        data.update({
            "открыто": 0,
            "сделок_сегодня": 0,
            "прибыль_сегодня": 0.0,
            "средства": data["баланс"],
            "последняя_сделка": "—",
            "побед": 0,
            "поражений": 0,
            "безубыток": 0,
            "винрейт": "0%",
            "live_pnl_pct": 0.0, "live_pnl_usdt": 0.0,
            "auto_trades": 0, "auto_pnl": 0.0,
            "auto_wins": 0, "auto_losses": 0, "auto_be": 0, "auto_wr": "0%",
            "manual_trades": 0, "manual_pnl": 0.0,
            "manual_wins": 0, "manual_losses": 0, "manual_be": 0, "manual_wr": "0%",
        })
        return data

    try:
        conn = _db()
        trade_ts_expr = "COALESCE(finalized_at, closed_at, opened_at)"

        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM APEX_MASTER_TRADE
            WHERE row_status = 'active'
              AND mode_layer IN ('AUTO','MANUAL')
            """
        ).fetchone()
        открыто = _safe_int(row["cnt"] if row else 0, 0)

        row_auto = conn.execute(
            f"""
            SELECT
                COUNT(*) AS trades_today,
                ROUND(COALESCE(SUM(pnl_usdt), 0), 4) AS pnl_today,
                SUM(CASE WHEN COALESCE(pnl_usdt, 0) > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN COALESCE(pnl_usdt, 0) < 0 THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN COALESCE(pnl_usdt, 0) = 0 THEN 1 ELSE 0 END) AS be
            FROM APEX_MASTER_TRADE
            WHERE date({trade_ts_expr}, '+2 hours') = date('now', '+2 hours')
              AND COALESCE(close_reason, '') != 'MANUAL_CLEAR'
              AND mode_layer = 'AUTO'
            """
        ).fetchone()

        auto_trades = _safe_int(row_auto["trades_today"] if row_auto else 0, 0)
        auto_pnl = _safe_float(row_auto["pnl_today"] if row_auto else 0.0, 0.0)
        auto_wins = _safe_int(row_auto["wins"] if row_auto else 0, 0)
        auto_losses = _safe_int(row_auto["losses"] if row_auto else 0, 0)
        auto_be = _safe_int(row_auto["be"] if row_auto else 0, 0)
        auto_closed = auto_wins + auto_losses
        auto_wr = f"{round((auto_wins / auto_closed) * 100, 1)}%" if auto_closed > 0 else "0%"

        row_manual = conn.execute(
            f"""
            SELECT
                COUNT(*) AS trades_today,
                ROUND(COALESCE(SUM(pnl_usdt), 0), 4) AS pnl_today,
                SUM(CASE WHEN COALESCE(pnl_usdt, 0) > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN COALESCE(pnl_usdt, 0) < 0 THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN COALESCE(pnl_usdt, 0) = 0 THEN 1 ELSE 0 END) AS be
            FROM APEX_MASTER_TRADE
            WHERE date({trade_ts_expr}, '+2 hours') = date('now', '+2 hours')
              AND COALESCE(close_reason, '') != 'MANUAL_CLEAR'
              AND mode_layer = 'MANUAL'
            """
        ).fetchone()

        manual_trades = _safe_int(row_manual["trades_today"] if row_manual else 0, 0)
        manual_pnl = _safe_float(row_manual["pnl_today"] if row_manual else 0.0, 0.0)
        manual_wins = _safe_int(row_manual["wins"] if row_manual else 0, 0)
        manual_losses = _safe_int(row_manual["losses"] if row_manual else 0, 0)
        manual_be = _safe_int(row_manual["be"] if row_manual else 0, 0)
        manual_closed = manual_wins + manual_losses
        manual_wr = f"{round((manual_wins / manual_closed) * 100, 1)}%" if manual_closed > 0 else "0%"

        сделок_сегодня = auto_trades + manual_trades
        прибыль_сегодня = round(auto_pnl + manual_pnl, 4)
        побед = auto_wins + manual_wins
        поражений = auto_losses + manual_losses
        безубыток = auto_be + manual_be

        closed_non_be = побед + поражений
        винрейт = f"{round((побед / closed_non_be) * 100, 1)}%" if closed_non_be > 0 else "0%"

        row = conn.execute(
            f"""
            SELECT {trade_ts_expr} AS ts
            FROM APEX_MASTER_TRADE
            WHERE mode_layer IN ('AUTO','MANUAL')
            ORDER BY {trade_ts_expr} DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        последняя_сделка = _fmt_dt(row["ts"] if row else None)

        row = conn.execute(
            """
            SELECT ROUND(COALESCE(SUM(pnl_usdt), 0), 4) AS total_realized
            FROM APEX_MASTER_TRADE
            WHERE closed_at IS NOT NULL
              AND COALESCE(close_reason, '') != 'MANUAL_CLEAR'
              AND mode_layer IN ('AUTO','MANUAL')
            """
        ).fetchone()
        total_realized = _safe_float(row["total_realized"] if row else 0.0, 0.0)
        средства = round(data["баланс"] + total_realized, 4)

        # --- LIVE PnL ---
        live_rows = conn.execute(
            """
            SELECT symbol, direction, entry, size
            FROM APEX_MASTER_TRADE
            WHERE row_status = 'active'
              AND mode_layer IN ('AUTO','MANUAL')
            """
        ).fetchall()

        live_pnl_pct_total = 0.0
        live_pnl_usdt_total = 0.0
        live_count = 0

        if live_rows:
            prices = _get_live_prices()

            for r in live_rows:
                entry = _safe_float(r["entry"])
                if entry <= 0:
                    continue
                current = _safe_float(prices.get(r["symbol"]))
                if current <= 0:
                    continue

                direction = str(r["direction"]).upper()
                if direction == "LONG":
                    pnl_pct = (current - entry) / entry * 100
                else:
                    pnl_pct = (entry - current) / entry * 100

                size = _safe_float(r["size"])
                pnl_usdt = size * pnl_pct / 100 if size > 0 else 0.0

                live_pnl_pct_total += pnl_pct
                live_pnl_usdt_total += pnl_usdt
                live_count += 1

        live_pnl_pct_avg = round(live_pnl_pct_total / live_count, 2) if live_count > 0 else 0.0
        live_pnl_usdt = round(live_pnl_usdt_total, 2)

        conn.close()

        data.update({
            "открыто": открыто,
            "сделок_сегодня": сделок_сегодня,
            "прибыль_сегодня": прибыль_сегодня,
            "средства": средства,
            "последняя_сделка": последняя_сделка,
            "побед": побед,
            "поражений": поражений,
            "безубыток": безубыток,
            "винрейт": винрейт,
            "live_pnl_pct": live_pnl_pct_avg,
            "live_pnl_usdt": live_pnl_usdt,
            "auto_trades": auto_trades,
            "auto_pnl": auto_pnl,
            "auto_wins": auto_wins,
            "auto_losses": auto_losses,
            "auto_be": auto_be,
            "auto_wr": auto_wr,
            "manual_trades": manual_trades,
            "manual_pnl": manual_pnl,
            "manual_wins": manual_wins,
            "manual_losses": manual_losses,
            "manual_be": manual_be,
            "manual_wr": manual_wr,
        })
        return data

    except Exception:
        data.update({
            "открыто": 0,
            "сделок_сегодня": 0,
            "прибыль_сегодня": 0.0,
            "средства": data["баланс"],
            "последняя_сделка": "—",
            "побед": 0,
            "поражений": 0,
            "безубыток": 0,
            "винрейт": "0%",
            "live_pnl_pct": 0.0, "live_pnl_usdt": 0.0,
            "auto_trades": 0, "auto_pnl": 0.0,
            "auto_wins": 0, "auto_losses": 0, "auto_be": 0, "auto_wr": "0%",
            "manual_trades": 0, "manual_pnl": 0.0,
            "manual_wins": 0, "manual_losses": 0, "manual_be": 0, "manual_wr": "0%",
        })
        return data


# ============================================================
# МЕНЮ / НАВИГАЦИЯ
# ============================================================

def _set_menu(context: ContextTypes.DEFAULT_TYPE, menu_name: str):
    context.user_data["menu"] = menu_name


def _parent_menu(menu_name: str) -> str:
    mapping = {
        "status": "main",
        "scanner": "status",
        "scanner_mode": "scanner",
        "scanner_pairs": "scanner",
        "scanner_filters": "scanner",
        "wau": "main",
        "settings": "main",
        "auto": "settings",
        "limits": "settings",
        "exchange": "settings",
        "risk": "settings",
        "strategy": "main",
        "confirm_stop": "main",
        "confirm_start": "main",
        "confirm_reset": "main",
    }
    return mapping.get(menu_name, "main")


def _menu_markup(menu_name: str):
    if menu_name == "main":
        return main_menu()
    if menu_name == "status":
        return status_menu()
    if menu_name == "scanner":
        return scanner_menu()
    if menu_name == "scanner_mode":
        return scanner_mode_menu()
    if menu_name == "scanner_pairs":
        return scanner_pairs_menu()
    if menu_name == "scanner_filters":
        return scanner_filters_menu()
    if menu_name == "wau":
        return wau_menu()
    if menu_name == "settings":
        return settings_menu()
    if menu_name == "auto":
        return auto_menu()
    if menu_name == "limits":
        return limits_menu()
    if menu_name == "risk":
        return risk_menu()
    if menu_name == "exchange":
        return exchange_menu()
    if menu_name == "strategy":
        return strategy_menu()
    if menu_name == "confirm_stop":
        return confirm_stop_menu()
    if menu_name == "confirm_start":
        return confirm_start_menu()
    if menu_name == "confirm_reset":
        return confirm_reset_menu()
    return main_menu()


# ============================================================
# ТЕКСТЫ КАРТОЧЕК
# ============================================================

def _build_system_text() -> str:
    d = _get_status_data()
    W = 11

    direction_map = {
        "both": "LONG+SHORT",
        "long": "LONG",
        "short": "SHORT",
    }
    mode_map = {
        "RUN_MODE": "Рабочий",
        "ON": "Вкл",
        "OFF": "Выкл",
    }

    lines = [
        "🛠 СОСТОЯНИЕ",
        _SEP,
        _row("Торговля", "✅" if d["торговля_вкл"] else "❌", W),
        _row("Сканер", "✅" if d["сканер_вкл"] else "❌", W),
        _row("Входы", "✅" if d["входы_вкл"] else "❌", W),
        _row("Монитор", "✅" if d["монитор_вкл"] else "❌", W),
        "",
        _row("Стратегия", d["стратегия"], W),
        _row("Направл.", direction_map.get(str(d["направление"]).lower(), str(d["направление"])), W),
        _row("Режим", mode_map.get(str(d["режим"]), str(d["режим"])), W),
        "",
        _row("Сессия", d["сессия"], W),
        _row("Фаза", d["фаза"], W),
        _row("До конца", d["до_конца"], W),
        _row("Вход", "Да" if d["вход_разрешён"] else "Нет", W),
    ]
    return _pre(lines)


def _build_trading_text() -> str:
    d = _get_status_data()
    tc = _get_test_control()
    ex = _get_exchange_stats()
    active_exchanges = tc.get("active_exchanges", ["bybit"])
    W = 11

    # Pipeline статус
    try:
        import subprocess, json as _json
        result = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=5)
        procs = _json.loads(result.stdout)
        pipeline = next((p for p in procs if p.get("name") == "apex-pipeline"), None)
        pipeline_status = "🟢 Online" if pipeline and pipeline.get("pm2_env", {}).get("status") == "online" else "🔴 Stopped"
    except Exception:
        pipeline_status = "❓ Ошибка"

    lines = [
        "💰 ТОРГОВЛЯ",
        _SEP,
        _row("Pipeline", pipeline_status, W),
        _row("Режим", tc.get("strategy_mode", "—"), W),
        _row("PnL live", f"{_fmt_pnl(d['live_pnl_pct'])}%", W),
        _row("PnL $", f"{_fmt_pnl(d['live_pnl_usdt'])}", W),
    ]

    exchange_labels = {"bybit": "✅ Bybit", "binance": "✅ Binance"}
    for exch in active_exchanges:
        key = exch.lower()
        e = ex.get(key, {})
        label = exchange_labels.get(key, f"✅ {exch.capitalize()}")
        trades = e.get("trades", 0)
        pnl = e.get("pnl", 0.0)
        wins = e.get("wins", 0)
        losses = e.get("losses", 0)
        wr = e.get("wr", "0%")
        active_pos = e.get("active", 0)

        try:
            conn = _db()
            row = conn.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN pnl_usdt>0 THEN pnl_usdt ELSE 0 END),0) AS gp,
                    COALESCE(SUM(CASE WHEN pnl_usdt<0 THEN ABS(pnl_usdt) ELSE 0 END),0) AS gl
                FROM APEX_MASTER_TRADE
                WHERE LOWER(COALESCE(exchange_name,''))=?
                  AND date(COALESCE(closed_at,opened_at),'+2 hours')=date('now','+2 hours')
                  AND row_status!='active'
            """, (key,)).fetchone()
            gp = _safe_float(row["gp"] if row else 0)
            gl = _safe_float(row["gl"] if row else 0)
            pf = round(gp/gl, 2) if gl > 0 else 0.0
            row2 = conn.execute("""
                SELECT COALESCE(closed_at, opened_at) AS ts
                FROM APEX_MASTER_TRADE
                WHERE LOWER(COALESCE(exchange_name,''))=?
                  AND row_status!='active'
                ORDER BY id DESC LIMIT 1
            """, (key,)).fetchone()
            last_trade = str(row2["ts"])[11:19] if row2 and row2["ts"] else "—"
            conn.close()
        except Exception:
            pf = 0.0
            last_trade = "—"

        # Баланс с биржи
        balance_live = "—"
        try:
            from modules.exchange_client import ExchangeClient
            cl = ExchangeClient()
            if key == "bybit":
                bal = cl.get_balance_bybit()
            elif key == "binance":
                bal = cl.get_balance_binance()
            else:
                bal = 0.0
            balance_live = f"{round(bal, 2)} $" if bal > 0 else "—"
        except Exception:
            pass

        lines.extend([
            "",
            label,
            _row("Баланс", balance_live, W),
            _row("Открыто", active_pos, W),
            _row("Сделок", trades, W),
            _row("PnL", f"{_fmt_pnl(pnl)} $", W),
            _row("W/L/BE", f"{wins}/{losses}", W),
            _row("WinRate", wr, W),
            _row("PF", pf, W),
            _row("Посл.сдел", last_trade, W),
            _row("SL/TP", f"{tc.get('param_sl_pct','—')}%/{tc.get('param_tp1_pct','—')}/{tc.get('param_tp2_pct','—')}/{tc.get('param_tp3_pct','—')}%", W),
            _row("Плечо", f"x{tc.get('param_leverage','—')}", W),
        ])

    lines.extend([
        "",
        "💰 Капитал",
        _row("Виртуал.", f"{d['баланс']} $", W),
        _row("Средства", f"{d['средства']} $", W),
        _row("PnL день", f"{d['прибыль_сегодня']} $", W),
    ])

    return _pre(lines)
def _build_scanner_text() -> str:
    tc = _get_test_control()
    active_exchanges = tc.get("active_exchanges", ["bybit"])
    W = 11

    # Pipeline статус
    try:
        import subprocess, json as _json
        result = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=5)
        procs = _json.loads(result.stdout)
        pipeline = next((p for p in procs if p.get("name") == "apex-pipeline"), None)
        if pipeline:
            status = pipeline.get("pm2_env", {}).get("status", "unknown")
            restarts = pipeline.get("pm2_env", {}).get("restart_time", 0)
            memory = pipeline.get("monit", {}).get("memory", 0)
            memory_mb = round(memory / 1024 / 1024, 1)
            pipeline_status = "🟢 Online" if status == "online" else "🔴 Stopped"
        else:
            pipeline_status = "❓ Не найден"
            restarts = 0
            memory_mb = 0
    except Exception:
        pipeline_status = "❓ Ошибка"
        restarts = 0
        memory_mb = 0

    scanner_on = tc.get("scanner_enabled", False)

    # Данные сканера из БД (Bybit)
    try:
        conn = _db()
        row = conn.execute("""
            SELECT total_pairs, after_liquidity, after_volatility,
                   after_structure, candidates, signals, top_score,
                   last_reject_reason, created_at
            FROM APEX_MASTER_SCANNER_SUMMARY
            ORDER BY id DESC LIMIT 1
        """).fetchone()
        if row:
            bybit_data = {
                "total": _safe_int(row["total_pairs"], 0),
                "liquidity": _safe_int(row["after_liquidity"], 0),
                "volatility": _safe_int(row["after_volatility"], 0),
                "structure": _safe_int(row["after_structure"], 0),
                "candidates": _safe_int(row["candidates"], 0),
                "signals": _safe_int(row["signals"], 0),
                "top_score": _safe_float(row["top_score"], 0.0),
                "reject": row["last_reject_reason"] or "—",
                "last_cycle": str(row["created_at"] or "—")[:19],
            }
        else:
            bybit_data = {"total":0,"liquidity":0,"volatility":0,"structure":0,
                         "candidates":0,"signals":0,"top_score":0.0,"reject":"—","last_cycle":"—"}
        conn.close()
    except Exception:
        bybit_data = {"total":0,"liquidity":0,"volatility":0,"structure":0,
                     "candidates":0,"signals":0,"top_score":0.0,"reject":"—","last_cycle":"—"}

    lines = [
        "🔭 СКАНЕР",
        _SEP,
        _row("Pipeline", pipeline_status, W),
        _row("Память", f"{memory_mb} MB", W),
        _row("Рестарты", restarts, W),
        _row("Сканер", "✅ ВКЛ" if scanner_on else "❌ ВЫКЛ", W),
        _row("Цикл", bybit_data["last_cycle"][11:] if bybit_data["last_cycle"] != "—" else "—", W),
    ]

    exchange_labels = {"bybit": "✅ Bybit", "binance": "✅ Binance"}
    for exch in active_exchanges:
        key = exch.lower()
        label = exchange_labels.get(key, f"✅ {exch.capitalize()}")

        if key == "bybit":
            d = bybit_data
        else:
            # Binance — пока нет данных
            d = {"total":0,"liquidity":0,"volatility":0,"structure":0,
                 "candidates":0,"signals":0,"top_score":0.0,"reject":"нет данных"}

        lines.extend([
            "",
            label,
            _row("Всего пар", d["total"], W),
            _row("Ликв.", d["liquidity"], W),
            _row("Волат.", d["volatility"], W),
            _row("Структ.", d["structure"], W),
            _row("Кандид.", d["candidates"], W),
            _row("Сигналы", d["signals"], W),
            _row("Топ балл", d["top_score"], W),
            _row("Отказ", d["reject"], W),
        ])

    return _pre(lines)
def _build_positions_text() -> str:
    if not _db_exists():
        return _pre(["📍 ПОЗИЦИИ", "", "База не найдена."])

    try:
        conn = _db()
        rows = conn.execute(
            """
            SELECT
                symbol,
                direction,
                entry,
                sl,
                tp1,
                tp2,
                tp3,
                size,
                leverage,
                opened_at
            FROM APEX_MASTER_TRADE
            WHERE row_status = 'active'
              AND mode_layer IN ('AUTO','MANUAL')
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()

        cnt_row = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM APEX_MASTER_TRADE
            WHERE row_status = 'active'
              AND mode_layer IN ('AUTO','MANUAL')
            """
        ).fetchone()
        total_open = _safe_int(cnt_row["cnt"] if cnt_row else 0, 0)
        conn.close()

        if not rows:
            return _pre(["📍 ПОЗИЦИИ", "", "Открытых позиций нет."])

        prices = _get_live_prices()
        W = 11

        lines = [
            "📍 ПОЗИЦИИ",
            _SEP,
            _row("Открыто", total_open, W),
            _row("Показано", len(rows), W),
        ]

        for i, row in enumerate(rows, start=1):
            direction = "L" if str(row["direction"]).lower() == "long" else "S"
            entry = _safe_float(row["entry"])
            current = _safe_float(prices.get(row["symbol"]))

            if entry > 0 and current > 0:
                if str(row["direction"]).upper() == "LONG":
                    pos_pnl = (current - entry) / entry * 100
                else:
                    pos_pnl = (entry - current) / entry * 100
                pnl_str = f"{_fmt_pnl(round(pos_pnl, 2))}%"
            else:
                pnl_str = "—"

            sym = row["symbol"].replace("/USDT:USDT", "")
            lines.extend([
                "",
                f"{i}. {sym} [{direction}]",
                _row("Вход", row["entry"], W),
                _row("PnL", pnl_str, W),
                _row("SL", row["sl"], W),
                _row("TP", f"{row['tp1']}/{row['tp2']}/{row['tp3']}", W),
                _row("Размер", f"{row['size']} x{row['leverage']}", W),
                _row("Открыта", _fmt_dt(row["opened_at"]), W),
            ])

        if total_open > len(rows):
            lines.extend(["", _row("Ещё", total_open - len(rows), W)])

        return _pre(lines)

    except Exception as e:
        return _pre(["📍 ПОЗИЦИИ", "", f"Ошибка чтения: {e}"])



def _build_slice_text() -> str:
    """Статистика от последнего сброса (session_start_ts)."""
    tc = _get_test_control()
    session_start_ts = tc.get("session_start_ts")
    W = 11

    if not _db_exists() or not session_start_ts:
        return _pre(["✂️ СРЕЗ", "", "Нет данных. Нажмите ♻️ Сброс."])

    try:
        conn = _db()
        ex = _get_exchange_stats()
        active_exchanges = tc.get("active_exchanges", ["bybit"])

        # Сделки после session_start_ts
        row = conn.execute("""
            SELECT
                COUNT(*) AS trades,
                ROUND(COALESCE(SUM(pnl_usdt),0),2) AS pnl,
                SUM(CASE WHEN COALESCE(pnl_usdt,0)>0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN COALESCE(pnl_usdt,0)<0 THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN COALESCE(pnl_usdt,0)=0 THEN 1 ELSE 0 END) AS be
            FROM APEX_MASTER_TRADE
            WHERE opened_at >= ?
              AND COALESCE(close_reason,'') != 'MANUAL_CLEAR'
              AND row_status != 'active'
        """, (session_start_ts,)).fetchone()

        trades = _safe_int(row["trades"] if row else 0, 0)
        pnl = _safe_float(row["pnl"] if row else 0.0, 0.0)
        wins = _safe_int(row["wins"] if row else 0, 0)
        losses = _safe_int(row["losses"] if row else 0, 0)
        be = _safe_int(row["be"] if row else 0, 0)
        closed = wins + losses
        wr = f"{round((wins/closed)*100,1)}%" if closed > 0 else "0%"

        # Активные позиции сейчас
        active_row = conn.execute("""
            SELECT COUNT(*) AS cnt FROM APEX_MASTER_TRADE
            WHERE row_status='active'
        """).fetchone()
        active = _safe_int(active_row["cnt"] if active_row else 0, 0)

        # По биржам от session_start_ts
        exch_rows = conn.execute("""
            SELECT
                LOWER(COALESCE(exchange_name,'unknown')) AS exch,
                COUNT(*) AS trades,
                ROUND(COALESCE(SUM(pnl_usdt),0),2) AS pnl,
                SUM(CASE WHEN COALESCE(pnl_usdt,0)>0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN COALESCE(pnl_usdt,0)<0 THEN 1 ELSE 0 END) AS losses
            FROM APEX_MASTER_TRADE
            WHERE opened_at >= ?
              AND COALESCE(close_reason,'') != 'MANUAL_CLEAR'
              AND row_status != 'active'
            GROUP BY LOWER(COALESCE(exchange_name,'unknown'))
        """, (session_start_ts,)).fetchall()

        exch_data = {}
        for r in exch_rows:
            cl = _safe_int(r["wins"],0) + _safe_int(r["losses"],0)
            exch_data[r["exch"]] = {
                "trades": _safe_int(r["trades"],0),
                "pnl": _safe_float(r["pnl"],0.0),
                "wins": _safe_int(r["wins"],0),
                "losses": _safe_int(r["losses"],0),
                "wr": f"{round((_safe_int(r['wins'],0)/cl)*100,1)}%" if cl>0 else "0%",
            }

        conn.close()

        ts_display = str(session_start_ts)[:19].replace("T", " ")
        lines = [
            "✂️ СРЕЗ",
            _SEP,
            _row("От", ts_display, W),
            "",
            _row("Сделки", trades, W),
            _row("PnL", f"{_fmt_pnl(pnl)} $", W),
            _row("W/L/BE", f"{wins}/{losses}/{be}", W),
            _row("WinRate", wr, W),
            _row("Открыто", active, W),
        ]

        exchange_labels = {"bybit": "✅ Bybit", "binance": "✅ Binance"}
        for exch in active_exchanges:
            key = exch.lower()
            e = exch_data.get(key, {})
            label = exchange_labels.get(key, f"✅ {exch.capitalize()}")
            lines.extend([
                "",
                label,
                _row("Сделки", e.get("trades",0), W),
                _row("PnL", f"{_fmt_pnl(e.get('pnl',0.0))} $", W),
                _row("W/L", f"{e.get('wins',0)}/{e.get('losses',0)}", W),
                _row("WinRate", e.get("wr","0%"), W),
            ])

        return _pre(lines)

    except Exception as e:
        return _pre(["✂️ СРЕЗ", "", f"Ошибка: {e}"])



def _build_analytics_text() -> str:
    """Аналитика — эффективность системы за последний час и день."""
    W = 13
    try:
        conn = _db()
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        hour_ago = (now - timedelta(hours=1)).isoformat()

        # За последний час
        row = conn.execute("""
            SELECT
                COUNT(*) AS trades,
                ROUND(COALESCE(SUM(pnl_usdt),0),2) AS pnl,
                SUM(CASE WHEN row_status='active' THEN 1 ELSE 0 END) AS active
            FROM APEX_MASTER_TRADE
            WHERE opened_at >= ?
        """, (hour_ago,)).fetchone()
        hr_trades = _safe_int(row["trades"] if row else 0)
        hr_pnl = _safe_float(row["pnl"] if row else 0.0)
        hr_active = _safe_int(row["active"] if row else 0)

        # Топ 3 пары сегодня
        top_rows = conn.execute("""
            SELECT symbol, pnl_usdt, close_reason
            FROM APEX_MASTER_TRADE
            WHERE date(COALESCE(closed_at,opened_at),'+2 hours')=date('now','+2 hours')
              AND row_status != 'active'
            ORDER BY ABS(pnl_usdt) DESC
            LIMIT 3
        """).fetchall()

        # Цикличность
        cycle_row = conn.execute("""
            SELECT COUNT(*) AS cycles
            FROM APEX_MASTER_SCANNER_SUMMARY
            WHERE created_at >= ?
        """, (hour_ago,)).fetchone()
        cycles_hr = _safe_int(cycle_row["cycles"] if cycle_row else 0)

        signal_row = conn.execute("""
            SELECT COUNT(*) AS sigs
            FROM APEX_MASTER_SCANNER_SUMMARY
            WHERE created_at >= ?
              AND signals > 0
        """, (hour_ago,)).fetchone()
        signals_hr = _safe_int(signal_row["sigs"] if signal_row else 0)
        conversion = round((signals_hr / cycles_hr * 100), 1) if cycles_hr > 0 else 0.0

        # Средняя длительность сделки
        dur_row = conn.execute("""
            SELECT AVG(duration_minutes) AS avg_dur
            FROM APEX_MASTER_TRADE
            WHERE date(COALESCE(closed_at,opened_at),'+2 hours')=date('now','+2 hours')
              AND row_status != 'active'
              AND duration_minutes IS NOT NULL
        """).fetchone()
        avg_dur = round(_safe_float(dur_row["avg_dur"] if dur_row else 0), 1)

        # Лучший выход
        exit_row = conn.execute("""
            SELECT close_reason, COUNT(*) AS cnt
            FROM APEX_MASTER_TRADE
            WHERE date(COALESCE(closed_at,opened_at),'+2 hours')=date('now','+2 hours')
              AND row_status != 'active'
              AND close_reason IS NOT NULL
              AND close_reason NOT IN ('MANUAL_STOP','MANUAL_CLEAR','MANUAL_CLOSE')
            GROUP BY close_reason
            ORDER BY cnt DESC
            LIMIT 1
        """).fetchone()
        best_exit = exit_row["close_reason"] if exit_row else "—"

        # Скорость API — время цикла / кол-во пар из сканера
        try:
            speed_rows = conn.execute("""
                SELECT total_pairs, created_at
                FROM APEX_MASTER_SCANNER_SUMMARY
                ORDER BY id DESC LIMIT 2
            """).fetchall()
            if len(speed_rows) >= 2:
                from datetime import datetime as _dt
                t1 = _dt.fromisoformat(str(speed_rows[0]["created_at"])[:19])
                t2 = _dt.fromisoformat(str(speed_rows[1]["created_at"])[:19])
                cycle_sec = abs((t1 - t2).total_seconds())
                pairs = _safe_int(speed_rows[0]["total_pairs"], 1)
                bybit_speed = round(cycle_sec / pairs, 3) if pairs > 0 else 0.0
            else:
                bybit_speed = 0.0
        except Exception:
            bybit_speed = 0.0
        binance_speed = 0.0  # пока Binance не сканируется

        # Кол-во пар по биржам из последнего цикла сканера
        try:
            scan_row = conn.execute("""
                SELECT total_pairs FROM APEX_MASTER_SCANNER_SUMMARY
                ORDER BY id DESC LIMIT 1
            """).fetchone()
            hr_bybit_pairs = _safe_int(scan_row["total_pairs"] if scan_row else 0)
        except Exception:
            hr_bybit_pairs = 0
        hr_binance_pairs = 0  # пока Binance не сканируется

        conn.close()

        lines = [
            "📈 АНАЛИТИКА",
            _SEP,
            "⏱ За последний час",
            _row("Сделок", hr_trades, W),
            _row("PnL", f"{_fmt_pnl(hr_pnl)} $", W),
            _row("Открыто", hr_active, W),
            "",
            "📊 Топ пары сегодня",
        ]

        for i, row in enumerate(top_rows, 1):
            sym = row["symbol"].replace("/USDT:USDT", "")
            pnl = _safe_float(row["pnl_usdt"])
            reason = row["close_reason"] or "—"
            lines.append(f"{i}. {sym}  {_fmt_pnl(round(pnl,2))}$  {reason}")

        if not top_rows:
            lines.append("нет данных")

        lines.extend([
            "",
            "🔄 Цикличность",
            _row("Циклов/час", cycles_hr, W),
            _row("Сигналов", signals_hr, W),
            _row("Конверсия", f"{conversion}%", W),
            "",
            "⚡ Скорость API (сек/пара)",
            _row("Bybit", f"{bybit_speed} сек", W),
            _row("Bybit цикл", f"{round(bybit_speed * hr_bybit_pairs / 60, 1)} мин" if bybit_speed > 0 else "—", W),
            _row("Binance", f"{binance_speed} сек", W),
            _row("Binance цикл", f"{round(binance_speed * hr_binance_pairs / 60, 1)} мин" if binance_speed > 0 else "—", W),
            "",
            "⚡ Скорость сделок",
            _row("Ср.длит.", f"{avg_dur} мин", W),
            _row("Топ выход", best_exit, W),
        ])

        return _pre(lines)

    except Exception as e:
        return _pre(["📈 АНАЛИТИКА", "", f"Ошибка: {e}"])

def _build_diagnostics_text() -> str:
    """Диагностика системы — 5 ключевых вопросов."""
    W = 14
    try:
        # Pipeline статус
        import subprocess, json as _json
        result = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=5)
        procs = _json.loads(result.stdout)
        pipeline = next((p for p in procs if p.get("name") == "apex-pipeline"), None)
        if pipeline:
            status = pipeline.get("pm2_env", {}).get("status", "unknown")
            restarts = pipeline.get("pm2_env", {}).get("restart_time", 0)
            pipeline_ok = status == "online"
        else:
            pipeline_ok = False
            restarts = 0
    except Exception:
        pipeline_ok = False
        restarts = 0

    try:
        conn = _db()
        from datetime import datetime, timezone, timedelta

        # Последний цикл сканера
        row = conn.execute("""
            SELECT created_at FROM APEX_MASTER_SCANNER_SUMMARY
            ORDER BY id DESC LIMIT 1
        """).fetchone()
        if row and row["created_at"]:
            last_cycle_str = str(row["created_at"])[:19]
            try:
                last_cycle_dt = datetime.fromisoformat(last_cycle_str)
                now = datetime.utcnow()
                diff = int((now - last_cycle_dt).total_seconds() / 60)
                cycle_ago = f"{diff}м назад" if diff < 60 else f"{diff//60}ч назад"
            except Exception:
                cycle_ago = "—"
        else:
            last_cycle_str = "—"
            cycle_ago = "—"

        # Последняя сделка
        row = conn.execute("""
            SELECT COALESCE(closed_at, opened_at) AS ts
            FROM APEX_MASTER_TRADE
            WHERE row_status != 'active'
            ORDER BY id DESC LIMIT 1
        """).fetchone()
        if row and row["ts"]:
            last_trade_str = str(row["ts"])[:19]
            try:
                last_trade_dt = datetime.fromisoformat(last_trade_str)
                diff2 = int((datetime.utcnow() - last_trade_dt).total_seconds() / 60)
                trade_ago = f"{diff2}м назад" if diff2 < 60 else f"{diff2//60}ч назад"
            except Exception:
                trade_ago = "—"
        else:
            last_trade_str = "—"
            trade_ago = "—"

        # Profit Factor по биржам
        pf_data = {}
        for exch in ["bybit", "binance"]:
            row = conn.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN pnl_usdt > 0 THEN pnl_usdt ELSE 0 END), 0) AS gross_profit,
                    COALESCE(SUM(CASE WHEN pnl_usdt < 0 THEN ABS(pnl_usdt) ELSE 0 END), 0) AS gross_loss
                FROM APEX_MASTER_TRADE
                WHERE LOWER(COALESCE(exchange_name,'')) = ?
                  AND date(COALESCE(closed_at, opened_at), '+2 hours') = date('now', '+2 hours')
                  AND row_status != 'active'
            """, (exch,)).fetchone()
            gp = _safe_float(row["gross_profit"] if row else 0)
            gl = _safe_float(row["gross_loss"] if row else 0)
            pf_data[exch] = round(gp / gl, 2) if gl > 0 else 0.0

        # Макс просадка
        row = conn.execute("""
            SELECT MIN(pnl_usdt) AS max_loss
            FROM APEX_MASTER_TRADE
            WHERE date(COALESCE(closed_at, opened_at), '+2 hours') = date('now', '+2 hours')
              AND row_status != 'active'
        """).fetchone()
        max_loss = _safe_float(row["max_loss"] if row else 0)

        # Ошибки за последний час
        row = conn.execute("""
            SELECT COUNT(*) AS cnt FROM APEX_MASTER_ERRORS
            WHERE created_at >= datetime('now', '-1 hour')
        """).fetchone()
        errors = _safe_int(row["cnt"] if row else 0)

        conn.close()

        pipeline_icon = "✅" if pipeline_ok else "❌"

        lines = [
            "🔍 ДИАГНОСТИКА",
            _SEP,
            "⏱ Активность",
            _row("Цикл", last_cycle_str[11:] if last_cycle_str != "—" else "—", W),
            _row("Последний", cycle_ago, W),
            "",
            "📊 Торговля",
            _row("Посл.сдел", last_trade_str[11:] if last_trade_str != "—" else "—", W),
            _row("Пауза", trade_ago, W),
            "",
            "💹 Эффективность",
            _row("PF Bybit", pf_data.get("bybit", 0.0), W),
            _row("PF Binance", pf_data.get("binance", 0.0), W),
            "",
            "🛡 Риск",
            _row("Макс.лосс", f"{max_loss:.2f} $", W),
            "",
            "🖥 Система",
            _row("Ошибки/час", errors, W),
            _row("Рестарты", restarts, W),
            _row("Pipeline", f"{pipeline_icon} {'Online' if pipeline_ok else 'Stopped'}", W),
        ]
        return _pre(lines)

    except Exception as e:
        return _pre(["🔍 ДИАГНОСТИКА", "", f"Ошибка: {e}"])

def _build_market_now_text() -> str:
    d = _get_status_data()
    W = 11

    lines = [
        "📈 РЫНОК СЕЙЧАС",
        _SEP,
        _row("Сессия", d["сессия"], W),
        _row("Фаза", d["фаза"], W),
        _row("До конца", d["до_конца"], W),
        "",
        _row("Всего", d["всего_пар"], W),
        _row("Ликв.", d["после_ликв"], W),
        _row("Волат.", d["после_вол"], W),
        _row("Структ.", d["после_структ"], W),
        "",
        _row("Кандид.", d["кандидаты"], W),
        _row("Сигналы", d["сигналы"], W),
        _row("Топ балл", d["лучший_балл"], W),
    ]
    return _pre(lines)


def _build_results_text() -> str:
    d = _get_status_data()
    W = 11

    lines = [
        "💼 ИТОГИ ДНЯ",
        _SEP,
        "🤖 Авто",
        _row("Сделки", d["auto_trades"], W),
        _row("PnL", f"{d['auto_pnl']} $", W),
        _row("W/L/BE", f"{d['auto_wins']}/{d['auto_losses']}/{d['auto_be']}", W),
        _row("WinRate", d["auto_wr"], W),
        "",
        "✋ Ручной",
        _row("Сделки", d["manual_trades"], W),
        _row("PnL", f"{d['manual_pnl']} $", W),
        _row("W/L/BE", f"{d['manual_wins']}/{d['manual_losses']}/{d['manual_be']}", W),
        _row("WinRate", d["manual_wr"], W),
        "",
        "💵 Итого",
        _row("Баланс", f"{d['баланс']} $", W),
        _row("Средства", f"{d['средства']} $", W),
        _row("PnL день", f"{d['прибыль_сегодня']} $", W),
        _row("Позиции", d["открыто"], W),
        _row("Посл.сдел", d["последняя_сделка"], W),
    ]
    return _pre(lines)


def _build_session_text() -> str:
    d = _get_status_data()
    ex = _get_exchange_stats()
    W = 11

    tc = _get_test_control()
    active_exchanges = tc.get("active_exchanges", ["bybit"])

    lines = [
        "📊 СЕССИЯ",
        _SEP,
        _row("Сессия", d["сессия"], W),
        _row("Фаза", d["фаза"], W),
        _row("До конца", d["до_конца"], W),
        _row("Вход", "Да" if d["вход_разрешён"] else "Нет", W),
        "",
        _row("Кандид.", d["кандидаты"], W),
        _row("Сигналы", d["сигналы"], W),
        _row("Позиции", d["открыто"], W),
    ]

    # Блок по каждой активной бирже
    exchange_labels = {"bybit": "✅ Bybit", "binance": "✅ Binance"}
    for exch in active_exchanges:
        key = exch.lower()
        e = ex.get(key, {})
        label = exchange_labels.get(key, f"✅ {exch.capitalize()}")
        trades = e.get("trades", 0)
        pnl = e.get("pnl", 0.0)
        wins = e.get("wins", 0)
        losses = e.get("losses", 0)
        wr = e.get("wr", "0%")
        active = e.get("active", 0)
        lines.extend([
            "",
            label,
            _row("Сделки", trades, W),
            _row("PnL", f"{_fmt_pnl(pnl)} $", W),
            _row("W/L", f"{wins}/{losses}", W),
            _row("WinRate", wr, W),
            _row("Открыто", active, W),
        ])

    lines.extend([
        "",
        "🤖 Авто",
        _row("Сделки", d["auto_trades"], W),
        _row("PnL", f"{d['auto_pnl']} $", W),
        "",
        "✋ Ручной",
        _row("Сделки", d["manual_trades"], W),
        _row("PnL", f"{d['manual_pnl']} $", W),
    ])
    return _pre(lines)


def _build_settings_text() -> str:
    d = _get_status_data()
    W = 11

    lines = [
        "⚙️ НАСТРОЙКИ",
        _SEP,
        _row("Стратегия", d["стратегия"], W),
        _row("Направл.", d["направление"], W),
        "",
        _row("SL", f"{d['sl']}%", W),
        _row("TP1", f"{d['tp1']}%", W),
        _row("TP2", f"{d['tp2']}%", W),
        _row("TP3", f"{d['tp3']}%", W),
        _row("Плечо", f"x{d['плечо']}", W),
        _row("Размер", f"{d['размер']} $", W),
        _row("Риск", f"{d['риск']} $" if d["риск"] != "выкл" else "выкл", W),
        _row("Лимит", d["лимит_позиций"], W),
    ]
    return _pre(lines)


# ============================================================
# START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _set_menu(context, "main")
    await update.message.reply_text(
        "⚡ <b>APEX PROTOCOL™</b>\nСистема готова.",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


# ============================================================
# ГЛАВНЫЙ ОБРАБОТЧИК
# ============================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    logger.info("telegram text=%r", text)

    if text == "◀️ Назад":
        current = context.user_data.get("menu", "main")
        parent = _parent_menu(current)
        _set_menu(context, parent)

        title = {
            "main": "Главное меню",
            "status": "Раздел статуса",
            "scanner": "Раздел сканера",
            "scanner_mode": "Выбор пресета сканера",
            "scanner_pairs": "Лимит пар сканера",
            "scanner_filters": "Фильтры сканера",
            "wau": "Аналитика",
            "settings": "Настройка бота",
            "auto": "Авторежим",
            "limits": "Лимиты",
            "exchange": "Биржи",
            "strategy": "Выбор стратегии",
            "confirm_stop": "Подтверждение остановки",
            "confirm_start": "Подтверждение запуска",
            "confirm_reset": "Подтверждение сброса",
        }.get(parent, "Главное меню")

        await update.message.reply_text(
            f"◀️ <b>{title}</b>",
            parse_mode="HTML",
            reply_markup=_menu_markup(parent),
        )
        return

    if text == "📊 Статус":
        _set_menu(context, "status")
        await update.message.reply_text(
            "📊 <b>РАЗДЕЛ СТАТУСА</b>\nВыбери подраздел:",
            parse_mode="HTML",
            reply_markup=status_menu(),
        )
        return

    if text == "💰 Торговля":
        _set_menu(context, "status")
        await update.message.reply_text(
            _build_trading_text(),
            parse_mode="HTML",
            reply_markup=status_menu(),
        )
        return

    if text == "🛠 Состояние":
        _set_menu(context, "status")
        await update.message.reply_text(
            _build_system_text(),
            parse_mode="HTML",
            reply_markup=status_menu(),
        )
        return

    if text == "🔭 Сканер":
        _set_menu(context, "status")
        await update.message.reply_text(
            _build_scanner_text(),
            parse_mode="HTML",
            reply_markup=status_menu(),
        )
        return

    if text == "📡 Статус сканера":
        _set_menu(context, "scanner")
        await update.message.reply_text(
            _build_scanner_text(),
            parse_mode="HTML",
            reply_markup=scanner_menu(),
        )
        return

    if text == "⚙️ Пресеты":
        _set_menu(context, "scanner_mode")
        await update.message.reply_text(
            "⚙️ <b>ВЫБОР ПРЕСЕТА СКАНЕРА</b>",
            parse_mode="HTML",
            reply_markup=scanner_mode_menu(),
        )
        return

    if text == "🔢 Лимит пар":
        _set_menu(context, "scanner_pairs")
        await update.message.reply_text(
            "🔢 <b>ВЫБЕРИ ЛИМИТ ПАР</b>",
            parse_mode="HTML",
            reply_markup=scanner_pairs_menu(),
        )
        return

    if text == "🧩 Фильтры":
        _set_menu(context, "scanner_filters")
        await update.message.reply_text(
            "🧩 <b>ФИЛЬТРЫ СКАНЕРА</b>",
            parse_mode="HTML",
            reply_markup=scanner_filters_menu(),
        )
        return

    if text == "🟢 Пресет А":
        _write_test_control({
            "scanner_mode_label": "Пресет А",
            "scanner_pairs_limit": 20,
        })
        _set_menu(context, "scanner_mode")
        await update.message.reply_text(
            "🟢 <b>Выбран Пресет А</b>\nЛимит пар: <b>20</b>",
            parse_mode="HTML",
            reply_markup=scanner_mode_menu(),
        )
        return

    if text == "🟡 Пресет Б":
        _write_test_control({
            "scanner_mode_label": "Пресет Б",
            "scanner_pairs_limit": 100,
        })
        _set_menu(context, "scanner_mode")
        await update.message.reply_text(
            "🟡 <b>Выбран Пресет Б</b>\nЛимит пар: <b>100</b>",
            parse_mode="HTML",
            reply_markup=scanner_mode_menu(),
        )
        return

    if text == "🔴 Пресет В":
        _write_test_control({
            "scanner_mode_label": "Пресет В",
            "scanner_pairs_limit": 500,
        })
        _set_menu(context, "scanner_mode")
        await update.message.reply_text(
            "🔴 <b>Выбран Пресет В</b>\nЛимит пар: <b>500</b>",
            parse_mode="HTML",
            reply_markup=scanner_mode_menu(),
        )
        return

    if text == "✍️ Ручной режим":
        _write_test_control({
            "scanner_mode_label": "Ручной",
        })
        _set_menu(context, "scanner_pairs")
        await update.message.reply_text(
            "✍️ <b>Ручной режим</b>\nТеперь выбери лимит пар.",
            parse_mode="HTML",
            reply_markup=scanner_pairs_menu(),
        )
        return

    if text in {"10 пар", "20 пар", "100 пар", "500 пар"}:
        limit = int(text.split()[0])
        _write_test_control({
            "scanner_pairs_limit": limit,
            "scanner_mode_label": "Ручной",
        })
        _set_menu(context, "scanner_pairs")
        await update.message.reply_text(
            f"🔢 <b>Лимит пар установлен: {limit}</b>",
            parse_mode="HTML",
            reply_markup=scanner_pairs_menu(),
        )
        return

    if text in {"Фильтр ликв.", "Фильтр волат.", "Фильтр структуры", "Фильтр объёма"}:
        _set_menu(context, "scanner_filters")
        await update.message.reply_text(
            f"🧩 <b>{text}</b>\nПока не подключено.",
            parse_mode="HTML",
            reply_markup=scanner_filters_menu(),
        )
        return

    if text == "⚡ ВАУ+":
        _set_menu(context, "wau")
        await update.message.reply_text(
            "⚡ <b>АНАЛИТИКА</b>",
            parse_mode="HTML",
            reply_markup=wau_menu(),
        )
        return

    if text == "📈 Аналитика":
        _set_menu(context, "status")
        await update.message.reply_text(
            _build_analytics_text(),
            parse_mode="HTML",
            reply_markup=status_menu(),
        )
        return

    if text == "🔍 Диагностика":
        _set_menu(context, "status")
        await update.message.reply_text(
            _build_diagnostics_text(),
            parse_mode="HTML",
            reply_markup=status_menu(),
        )
        return

    if text == "✂️ Срез":
        _set_menu(context, "wau")
        await update.message.reply_text(
            _build_slice_text(),
            parse_mode="HTML",
            reply_markup=wau_menu(),
        )
        return

    if text == "📈 Рынок сейчас":
        _set_menu(context, "wau")
        await update.message.reply_text(
            _build_market_now_text(),
            parse_mode="HTML",
            reply_markup=wau_menu(),
        )
        return

    if text == "📊 Сессия":
        _set_menu(context, "wau")
        await update.message.reply_text(
            _build_session_text(),
            parse_mode="HTML",
            reply_markup=wau_menu(),
        )
        return

    if text == "💼 Итоги дня":
        _set_menu(context, "wau")
        await update.message.reply_text(
            _build_results_text(),
            parse_mode="HTML",
            reply_markup=wau_menu(),
        )
        return

    if text == "🧠 AI (скоро)":
        _set_menu(context, "wau")
        await update.message.reply_text(
            "🧠 <b>Модуль AI пока не подключён</b>\nПозже здесь будет анализ рынка.",
            parse_mode="HTML",
            reply_markup=wau_menu(),
        )
        return

    # ── СТАРТ: шаг 1 — выбор стратегии ──
    if text == "🟢 Старт":
        _set_menu(context, "strategy")
        await update.message.reply_text(
            "🟢 <b>ВЫБОР СТРАТЕГИИ</b>",
            parse_mode="HTML",
            reply_markup=strategy_menu(),
        )
        return

    # ── СТАРТ: шаг 2 — выбрана стратегия, запрос подтверждения ──
    if text == "TOP20 1M BREAKOUT":
        context.user_data["pending_strategy"] = "TOP20_1M_BREAKOUT_v1"
        _set_menu(context, "confirm_start")
        await update.message.reply_text(
            "🟢 <b>Подтвердить запуск?</b>\n"
            "Стратегия: <b>TOP20 1M BREAKOUT</b>",
            parse_mode="HTML",
            reply_markup=confirm_start_menu(),
        )
        return

    # ── СТАРТ: шаг 3 — подтверждение ──
    if text == "✅ Да, запустить":
        strategy_key = context.user_data.pop("pending_strategy", "TOP20_1M_BREAKOUT_v1")
        state = _write_test_control({
            "trading_enabled": True,
            "scanner_enabled": True,
            "entries_enabled": True,
            "monitor_enabled": True,
            "manual_entry_enabled": True,
            "active_filter": strategy_key,
            "strategy_mode": "RUN_MODE",
            "mode": "RUN",
        })
        try:
            import subprocess
            subprocess.run(["pm2", "start", "apex-pipeline"],
                timeout=10, capture_output=True)
        except Exception:
            pass
        _set_menu(context, "main")
        strategy_name = state.get("active_filter", strategy_key)
        await update.message.reply_text(
            "🟢 <b>СТРАТЕГИЯ ЗАПУЩЕНА</b>\n"
            f"Стратегия: <b>{strategy_name}</b>\n"
            f"Обновлено: <b>{state.get('updated_at', 'n/a')}</b>",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        return

    if text == "(будущая стратегия)":
        _set_menu(context, "strategy")
        await update.message.reply_text(
            "🧠 <b>Будущая стратегия</b>\nПока не подключено.",
            parse_mode="HTML",
            reply_markup=strategy_menu(),
        )
        return

    # ── СТОП: шаг 1 — запрос подтверждения (НЕ ТРОГАЕМ) ──
    if text == "🔴 Стоп":
        _set_menu(context, "confirm_stop")
        await update.message.reply_text(
            "🔴 <b>Подтверди остановку торговли</b>",
            parse_mode="HTML",
            reply_markup=confirm_stop_menu(),
        )
        return

    # ── СТОП: шаг 2 — подтверждение (НЕ ТРОГАЕМ) ──
    if text == "✅ Да, остановить":
        state = _write_test_control({
            "trading_enabled": False,
            "scanner_enabled": False,
            "entries_enabled": False,
            "monitor_enabled": False,
            "manual_entry_enabled": False,
            "mode": "STOP",
        })
        # Фоновая остановка: ждём 90 сек пока pipeline закроет позиции, потом pm2 stop
        try:
            import subprocess
            subprocess.Popen([
                "bash", "-c",
                "sleep 90 && pm2 stop apex-pipeline"
            ])
        except Exception:
            pass
        _set_menu(context, "main")
        await update.message.reply_text(
            "🔴 <b>ОСТАНОВКА ЗАПУЩЕНА</b>\n"
            "⏳ Pipeline закрывает позиции...\n"
            "Через 90 сек pipeline остановится.\n"
            "Используй это время для Сброса статистики.\n"
            f"Обновлено: <b>{state.get('updated_at', 'n/a')}</b>",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        return

    # ── ОБЩАЯ ОТМЕНА (для стоп / старт / сброс) ──
    if text == "❌ Отмена":
        context.user_data.pop("pending_strategy", None)
        _set_menu(context, "main")
        await update.message.reply_text(
            "❌ <b>Отмена</b>",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        return

    if text == "📍 Позиции":
        _set_menu(context, "status")
        await update.message.reply_text(
            _build_positions_text(),
            parse_mode="HTML",
            reply_markup=status_menu(),
        )
        return

    # ── СБРОС: шаг 1 — запрос подтверждения ──
    if text == "♻️ Сброс":
        _set_menu(context, "confirm_reset")
        await update.message.reply_text(
            "♻️ <b>Подтвердить сброс?</b>\n"
            "Будет сброшено состояние Telegram и test_control.\n"
            "Торговые таблицы не затрагиваются.",
            parse_mode="HTML",
            reply_markup=confirm_reset_menu(),
        )
        return

    # ── СБРОС: шаг 2 — подтверждение ──
    if text == "✅ Да, сбросить":
        from datetime import datetime, timezone
        now_ts = datetime.now(timezone.utc).isoformat()
        _write_test_control({
            "manual_topup_total": 0.0,
            "awaiting_param_input": None,
            "awaiting_reset_confirm": False,
            "awaiting_stop_confirm": False,
            "session_start_ts": now_ts,
        })
        _set_menu(context, "main")
        await update.message.reply_text(
            "♻️ <b>СБРОС ВЫПОЛНЕН</b>\n"
            f"Сессия начата: <b>{now_ts[:19].replace('T',' ')}</b>\n"
            "Статистика бота сброшена.\n"
            "Торговые таблицы не затронуты.",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        return

    if text == "⚙️ Настройка бота":
        _set_menu(context, "settings")
        await update.message.reply_text(
            _build_settings_text(),
            parse_mode="HTML",
            reply_markup=settings_menu(),
        )
        return

    if text == "🎯 Риск-менеджер":
        tc = _get_test_control()
        _set_menu(context, "risk")
        await update.message.reply_text(
            f"🎯 <b>РИСК-МЕНЕДЖЕР</b>\n"
            f"SL:  <b>{tc.get('param_sl_pct','—')}%</b>\n"
            f"TP1: <b>{tc.get('param_tp1_pct','—')}%</b>\n"
            f"TP2: <b>{tc.get('param_tp2_pct','—')}%</b>\n"
            f"TP3: <b>{tc.get('param_tp3_pct','—')}%</b>\n\n"
            f"Выбери параметр:",
            parse_mode="HTML", reply_markup=risk_menu())
        return

    if text == "🛑 SL":
        tc = _get_test_control()
        context.user_data["awaiting_param"] = "param_sl_pct"
        _set_menu(context, "risk")
        await update.message.reply_text(
            f"🛑 <b>Stop Loss</b>\nТекущее: <b>{tc.get('param_sl_pct','—')}%</b>\n\nВведи новое значение в %:",
            parse_mode="HTML", reply_markup=risk_menu())
        return

    if text == "🎯 TP1":
        tc = _get_test_control()
        context.user_data["awaiting_param"] = "param_tp1_pct"
        _set_menu(context, "risk")
        await update.message.reply_text(
            f"🎯 <b>TP1</b>\nТекущее: <b>{tc.get('param_tp1_pct','—')}%</b>\n\nВведи новое значение в %:",
            parse_mode="HTML", reply_markup=risk_menu())
        return

    if text == "🎯 TP2":
        tc = _get_test_control()
        context.user_data["awaiting_param"] = "param_tp2_pct"
        _set_menu(context, "risk")
        await update.message.reply_text(
            f"🎯 <b>TP2</b>\nТекущее: <b>{tc.get('param_tp2_pct','—')}%</b>\n\nВведи новое значение в %:",
            parse_mode="HTML", reply_markup=risk_menu())
        return

    if text == "🎯 TP3":
        tc = _get_test_control()
        context.user_data["awaiting_param"] = "param_tp3_pct"
        _set_menu(context, "risk")
        await update.message.reply_text(
            f"🎯 <b>TP3</b>\nТекущее: <b>{tc.get('param_tp3_pct','—')}%</b>\n\nВведи новое значение в %:",
            parse_mode="HTML", reply_markup=risk_menu())
        return

    if text == "⚡ Плечо":
        tc = _get_test_control()
        context.user_data["awaiting_param"] = "param_leverage"
        _set_menu(context, "settings")
        await update.message.reply_text(
            f"⚡ <b>Плечо</b>\nТекущее: <b>{tc.get('param_leverage','—')}x</b>\n\nВведи новое значение:",
            parse_mode="HTML", reply_markup=settings_menu())
        return

    if text == "💵 Позиция":
        tc = _get_test_control()
        context.user_data["awaiting_param"] = "param_size_usdt"
        _set_menu(context, "settings")
        await update.message.reply_text(
            f"💵 <b>Размер позиции</b>\nТекущее: <b>{tc.get('param_size_usdt','—')} USDT</b>\n\nВведи новую сумму в USDT:",
            parse_mode="HTML", reply_markup=settings_menu())
        return

    if text == "🧠 Авторежим":
        _set_menu(context, "auto")
        await update.message.reply_text("🧠 <b>АВТОРЕЖИМ</b>", parse_mode="HTML", reply_markup=auto_menu())
        return

    if text in {"Защита 1", "Защита 2", "Защита 3", "Трейлинг", "Выход по времени"}:
        _set_menu(context, "auto")
        await update.message.reply_text(f"🧠 <b>{text}</b>\nПока не подключено.", parse_mode="HTML", reply_markup=auto_menu())
        return

    if text == "📉 Лимиты":
        _set_menu(context, "limits")
        await update.message.reply_text("📉 <b>ЛИМИТЫ</b>", parse_mode="HTML", reply_markup=limits_menu())
        return

    if text in {"Макс. позиций", "Кулдаун", "Макс. сделок / сессия"}:
        _set_menu(context, "limits")
        await update.message.reply_text(f"📉 <b>{text}</b>\nПока не подключено.", parse_mode="HTML", reply_markup=limits_menu())
        return

    if text == "💰 Биржи":
        _set_menu(context, "exchange")
        await update.message.reply_text("💰 <b>БИРЖИ / ЖИВЫЕ ДЕНЬГИ</b>", parse_mode="HTML", reply_markup=exchange_menu())
        return

    if text in {"Binance", "Bybit", "✅ Binance", "❌ Binance", "✅ Bybit", "❌ Bybit"}:
        text = text.replace("✅ ", "").replace("❌ ", "")
        tc = _get_test_control()
        active = list(tc.get("active_exchanges", []))
        key = text.lower()
        context.user_data["pending_exchange"] = key
        context.user_data["pending_exchange_label"] = text
        if key in active:
            context.user_data["pending_exchange_action"] = "off"
            bybit_icon = "✅" if "bybit" in active else "❌"
            binance_icon = "✅" if "binance" in active else "❌"
            _set_menu(context, "exchange")
            await update.message.reply_text(
                f"💰 <b>БИРЖИ</b>\n"
                f"Bybit: {bybit_icon}\n"
                f"Binance: {binance_icon}\n\n"
                f"Отключить <b>{text}</b>?",
                parse_mode="HTML",
                reply_markup=confirm_exchange_off_menu(),
            )
        else:
            context.user_data["pending_exchange_action"] = "on"
            bybit_icon = "✅" if "bybit" in active else "❌"
            binance_icon = "✅" if "binance" in active else "❌"
            _set_menu(context, "exchange")
            await update.message.reply_text(
                f"💰 <b>БИРЖИ</b>\n"
                f"Bybit: {bybit_icon}\n"
                f"Binance: {binance_icon}\n\n"
                f"Включить <b>{text}</b>?",
                parse_mode="HTML",
                reply_markup=confirm_exchange_on_menu(),
            )
        return

    if text == "OKX":
        _set_menu(context, "exchange")
        await update.message.reply_text(
            "💰 <b>OKX</b>\nПока не подключено.",
            parse_mode="HTML",
            reply_markup=exchange_menu(),
        )
        return

    if text == "✅ Да, включить":
        key = context.user_data.pop("pending_exchange", None)
        label = context.user_data.pop("pending_exchange_label", "")
        context.user_data.pop("pending_exchange_action", None)
        if key:
            tc = _get_test_control()
            active = list(tc.get("active_exchanges", []))
            if key not in active:
                active.append(key)
            _write_test_control({"active_exchanges": active})
            bybit_icon = "✅" if "bybit" in active else "❌"
            binance_icon = "✅" if "binance" in active else "❌"
            active_str = ", ".join(active)
            _set_menu(context, "exchange")
            await update.message.reply_text(
                f"✅ <b>{label}: ВКЛЮЧЕНА</b>\n"
                f"Bybit: {bybit_icon}\n"
                f"Binance: {binance_icon}\n"
                f"Активные биржи: {active_str}",
                parse_mode="HTML",
                reply_markup=exchange_menu(),
            )
        return

    if text == "✅ Да, отключить":
        key = context.user_data.pop("pending_exchange", None)
        label = context.user_data.pop("pending_exchange_label", "")
        context.user_data.pop("pending_exchange_action", None)
        if key:
            tc = _get_test_control()
            active = list(tc.get("active_exchanges", []))
            if key in active:
                active.remove(key)
            _write_test_control({"active_exchanges": active})
            bybit_icon = "✅" if "bybit" in active else "❌"
            binance_icon = "✅" if "binance" in active else "❌"
            active_str = ", ".join(active) if active else "нет"
            _set_menu(context, "exchange")
            await update.message.reply_text(
                f"❌ <b>{label}: ОТКЛЮЧЕНА</b>\n"
                f"Bybit: {bybit_icon}\n"
                f"Binance: {binance_icon}\n"
                f"Активные биржи: {active_str}",
                parse_mode="HTML",
                reply_markup=exchange_menu(),
            )
        return

    if text == "🔌 Подключить":
        _set_menu(context, "exchange")
        await update.message.reply_text("🔌 <b>Подключение API</b>\nПока не подключено.", parse_mode="HTML", reply_markup=exchange_menu())
        return

    if text == "📊 Статус бирж":
        tc = _get_test_control()
        active = list(tc.get("active_exchanges", []))
        bybit_status = "✅ ВКЛ" if "bybit" in active else "❌ ВЫКЛ"
        binance_status = "✅ ВКЛ" if "binance" in active else "❌ ВЫКЛ"
        _set_menu(context, "exchange")
        await update.message.reply_text(
            f"📊 <b>СТАТУС БИРЖ</b>\n"
            f"BYBIT: {bybit_status}\n"
            f"BINANCE: {binance_status}",
            parse_mode="HTML",
            reply_markup=exchange_menu(),
        )
        return

    awaiting = context.user_data.get("awaiting_param")
    if awaiting:
        try:
            value = float(text.replace(",", "."))
            _write_test_control({awaiting: value})
            context.user_data.pop("awaiting_param", None)
            labels = {
                "param_sl_pct": "SL",
                "param_tp1_pct": "TP1",
                "param_tp2_pct": "TP2",
                "param_tp3_pct": "TP3",
                "param_leverage": "Плечо",
                "param_size_usdt": "Позиция",
            }
            label = labels.get(awaiting, awaiting)
            tc = _get_test_control()
            # Автопоказ текущих настроек после изменения
            summary = (
                f"✅ <b>{label} установлен: {value}</b>\n\n"
                f"⚙️ <b>ТЕКУЩИЕ НАСТРОЙКИ</b>\n"
                f"SL:      <b>{tc.get('param_sl_pct','—')}%</b>\n"
                f"TP1:     <b>{tc.get('param_tp1_pct','—')}%</b>\n"
                f"TP2:     <b>{tc.get('param_tp2_pct','—')}%</b>\n"
                f"TP3:     <b>{tc.get('param_tp3_pct','—')}%</b>\n"
                f"Плечо:   <b>x{tc.get('param_leverage','—')}</b>\n"
                f"Позиция: <b>{tc.get('param_size_usdt','—')} USDT</b>"
            )
            # Определяем в каком меню остаться
            current_menu = context.user_data.get("menu", "settings")
            markup = risk_menu() if current_menu == "risk" else settings_menu()
            # Если это позиция или плечо — остаёмся в режиме ввода
            if awaiting in ("param_size_usdt", "param_leverage",
                           "param_sl_pct", "param_tp1_pct",
                           "param_tp2_pct", "param_tp3_pct"):
                context.user_data["awaiting_param"] = awaiting
            await update.message.reply_text(
                summary + "\n\n<i>Введи новое значение или нажми кнопку меню</i>",
                parse_mode="HTML",
                reply_markup=markup)
            return
        except ValueError:
            await update.message.reply_text(
                "❌ Введи число. Например: 1.5",
                parse_mode="HTML", reply_markup=settings_menu())
            return

    _set_menu(context, "main")
    await update.message.reply_text(
        "Не понял команду.\nНажми /start",
        reply_markup=main_menu(),
    )
