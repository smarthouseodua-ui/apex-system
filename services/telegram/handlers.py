import logging
import os
import sqlite3
import subprocess
from datetime import datetime
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger("apex.telegram")

from .auth import is_allowed
from .keyboard import get_main_keyboard, get_vau_keyboard, get_sltp_keyboard


DB_PATH      = "/root/apex-system/storage/db/sqlite/apex.db"
DB_DATA_PATH = "/root/data.db"
SYSTEM_YAML_PATH = "/root/apex-system/config/system.yaml"

ENGINE_TABLES = [
    "SKL01_T01_scanner_log",
    "SKL01_T02_strategy_log",
    "SKL01_T03_signal_gate_log",
    "SKL01_T04_risk_manager_log",
    "SKL01_T05_execution_log",
    "SKL01_T06_position_manager_log",
    "SKL01_T07_final_trade_results",
    "SKL01_T08_system_events_log",
    "scanner_log",
    "strategy_log",
    "signal_gate_log",
    "risk_manager_log",
    "execution_log",
    "position_manager_log",
    "final_trade_results",
    "system_events_log",
]

EXPORT_SCRIPT = "/root/export_final_trades.sh"

SESSION_RU = {
    "ASIA":      "Азия",
    "HONG_KONG": "Гонконг",
    "LONDON":    "Лондон",
    "NEW_YORK":  "Нью-Йорк",
    "OFF":       "Закрыто",
    "UNKNOWN":   "Неизвестно",
}

DIRECTION_RU = {
    "buy":     "покупка",
    "sell":    "продажа",
    "both":    "оба направления",
    "none":    "нет",
    "unknown": "неизвестно",
}

MODE_RU = {
    "OFF":              "выкл",
    "TEST":             "тест",
    "HOURLY_TEST":      "часовой тест",
    "NY_5M_OPEN":       "NY 5M RUNNING",
    "FIRST_5M_SESSION": "5M SESSION",
    "RUN":              "запущен",
}

PARAM_LABELS = {
    "sl_pct":    "SL %",
    "tp1_pct":   "TP1 %",
    "tp2_pct":   "TP2 %",
    "tp3_pct":   "TP3 %",
    "leverage":  "Плечо",
    "size_usdt": "Размер позиции (USDT)",
}


# ── DB helpers ────────────────────────────────────────────────────────────────

def db_exists() -> bool:
    return os.path.exists(DB_PATH)


def get_db_connection():
    return sqlite3.connect(DB_PATH)


def safe_format_dt(value: Any) -> str:
    if value is None:
        return "—"
    return str(value).replace("T", " ")[:16]


# ── Data helpers ──────────────────────────────────────────────────────────────

def get_session_info() -> dict:
    try:
        import yaml
        from core.time_manager import TimeManager, SESSIONS

        with open(SYSTEM_YAML_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        tm = TimeManager(config)
        info = tm.get_session_info()
        session = info["session"]
        hour = info["hour"]

        session_times = SESSIONS.get(session, {})
        end_hour = session_times.get("end", hour)
        minutes_left = (end_hour - hour) * 60 - datetime.now().minute

        if session == "OFF":
            status = "не активна"
            time_left = "—"
        elif minutes_left <= 0:
            status = "завершена"
            time_left = "0 мин"
        else:
            status = "активна"
            h, m = divmod(minutes_left, 60)
            time_left = f"{h} ч {m} мин" if h else f"{m} мин"

        return {
            "session":    SESSION_RU.get(session, session),
            "direction":  DIRECTION_RU.get(info["direction"], info["direction"]),
            "status":     status,
            "time_left":  time_left,
            "is_trading": info["is_trading"],
        }
    except Exception:
        return {
            "session":    "—",
            "direction":  "—",
            "status":     "—",
            "time_left":  "—",
            "is_trading": False,
        }


def get_pnl_today() -> float:
    if not db_exists():
        return 0.0
    try:
        conn = get_db_connection()
        row = conn.execute(
            "SELECT SUM(pnl_usdt) FROM SKL01_T07_final_trade_results "
            "WHERE close_reason NOT IN ('MANUAL_CLEAR') "
            "AND date(closed_at) = date('now')"
        ).fetchone()
        conn.close()
        return float(row[0]) if row and row[0] is not None else 0.0
    except Exception:
        return 0.0


def get_floating_pnl() -> tuple[float, int]:
    """Суммарный floating PnL по всем открытым позициям (T05 × T06)."""
    if not db_exists():
        return 0.0, 0
    try:
        conn = get_db_connection()
        rows = conn.execute("""
            SELECT
                t5.direction,
                t5.fill_price,
                t5.size,
                COALESCE(t6.current_price, t5.fill_price) AS current_price
            FROM SKL01_T05_execution_log t5
            LEFT JOIN (
                SELECT trade_id, current_price
                FROM SKL01_T06_position_manager_log
                WHERE id IN (
                    SELECT MAX(id) FROM SKL01_T06_position_manager_log
                    WHERE trade_id IS NOT NULL
                    GROUP BY trade_id
                )
            ) t6 ON t5.trade_id = t6.trade_id
            WHERE t5.status = 'open'
        """).fetchall()
        conn.close()
        total = 0.0
        for direction, fill_price, size, current_price in rows:
            if fill_price and size and current_price:
                if direction == "long":
                    total += (current_price - fill_price) * size
                else:
                    total += (fill_price - current_price) * size
        return round(total, 2), len(rows)
    except Exception:
        return 0.0, 0


def get_trades_count() -> int:
    if not db_exists():
        return 0
    try:
        conn = get_db_connection()
        row = conn.execute(
            "SELECT COUNT(*) FROM SKL01_T07_final_trade_results "
            "WHERE close_reason NOT IN ('MANUAL_CLEAR') "
            "AND date(closed_at) = date('now')"
        ).fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def get_last_activity() -> str:
    if not db_exists():
        return "—"
    try:
        conn = get_db_connection()
        row = conn.execute(
            "SELECT finalized_at FROM SKL01_T07_final_trade_results "
            "WHERE close_reason NOT IN ('MANUAL_CLEAR') "
            "ORDER BY finalized_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return safe_format_dt(row[0]) if row and row[0] else "—"
    except Exception:
        return "—"


def get_last_trades(limit: int = 10) -> list:
    if not db_exists():
        return []
    try:
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT symbol, direction, close_reason, pnl_usdt, finalized_at
            FROM SKL01_T07_final_trade_results
            WHERE close_reason NOT IN ('MANUAL_CLEAR')
            AND date(closed_at) = date('now')
            ORDER BY finalized_at DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def get_open_positions() -> list:
    if not db_exists():
        return []
    try:
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT symbol, direction, fill_price, size_usdt, opened_at,
                   sl, tp1, tp2, tp3
            FROM SKL01_T05_execution_log
            WHERE status = 'open'
            AND date(opened_at) = date('now')
            ORDER BY opened_at DESC
            """
        ).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def get_open_positions_count() -> int:
    if not db_exists():
        return 0
    try:
        conn = get_db_connection()
        row = conn.execute(
            "SELECT COUNT(*) FROM SKL01_T05_execution_log WHERE status='open'"
        ).fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def do_reset_engine() -> dict:
    """DELETE всех данных из ENGINE таблиц + VACUUM."""
    counts = {}
    conn = sqlite3.connect(DB_PATH)
    try:
        for table in ENGINE_TABLES:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                counts[table] = int(row[0]) if row else 0
                conn.execute(f"DELETE FROM {table}")
            except Exception:
                counts[table] = -1
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    return counts


def do_reset_data_core() -> dict:
    """DELETE из DATA CORE локального data.db + VACUUM + sync удалённого через export."""
    counts = {}

    if not os.path.exists(DB_DATA_PATH):
        counts["local_error"] = "data.db не найдена"
    else:
        conn = sqlite3.connect(DB_DATA_PATH)
        try:
            for table in ("final_trade_results",):
                try:
                    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    counts[f"local_{table}"] = int(row[0]) if row else 0
                    conn.execute(f"DELETE FROM {table}")
                except Exception:
                    counts[f"local_{table}"] = -1
            conn.commit()
            conn.execute("VACUUM")
        finally:
            conn.close()

    if os.path.exists(EXPORT_SCRIPT):
        try:
            result = subprocess.run(
                ["bash", EXPORT_SCRIPT],
                capture_output=True, text=True, timeout=60
            )
            counts["remote_sync"] = "ok" if result.returncode == 0 else f"err:{result.returncode}"
        except subprocess.TimeoutExpired:
            counts["remote_sync"] = "timeout"
        except Exception as e:
            counts["remote_sync"] = f"err:{e}"
    else:
        counts["remote_sync"] = "script not found"

    # ── Очистка таблиц на Core 03 ────────────────────────────────────────────
    try:
        result = subprocess.run(
            [
                "ssh", "root@104.248.206.152",
                "sqlite3 /root/apex-core03/db/apex_data.db "
                "'DELETE FROM T07_FINAL_TRADE_RESULTS; DELETE FROM T_OPEN_POSITIONS;'"
            ],
            capture_output=True, text=True, timeout=30
        )
        counts["core03_reset"] = "ok" if result.returncode == 0 else f"err:{result.returncode}:{result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        counts["core03_reset"] = "timeout"
    except Exception as e:
        counts["core03_reset"] = f"err:{e}"

    return counts


# ── Entry points ──────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ запрещён")
        return

    await update.message.reply_text(
        "🚀 <b>APEX PROTOCOL — бот запущен</b>\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_allowed(update.effective_user.id):
        logger.warning("handle_text: unauthorized user_id=%s", getattr(update.effective_user, "id", None))
        if update.message:
            await update.message.reply_text("⛔ Доступ запрещён")
        return

    if not update.message or not update.message.text:
        return

    text = update.message.text
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    logger.info("handle_text: user=%s text=%r", update.effective_user.id, text)
    try:
        await _handle_text_inner(update, context, text, now_str)
    except Exception as exc:
        logger.exception("handle_text: unhandled exception for text=%r: %s", text, exc)
        try:
            await update.message.reply_text(
                "⚠️ Внутренняя ошибка бота. Попробуй ещё раз или нажми /start.",
                reply_markup=get_main_keyboard(),
            )
        except Exception:
            pass


async def _handle_text_inner(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, now_str: str):

    from services.test_control import read as tc_read, write as tc_write

    # ── Перехват ввода суммы депозита (➕ / ➖) ───────────────────────────────
    tc = tc_read()
    if tc.get("awaiting_deposit_input"):
        cleaned = text.strip().replace(",", ".")
        action = tc.get("deposit_action", "add")
        try:
            amount = float(cleaned)
            if amount <= 0:
                raise ValueError("non-positive")
            old_balance = float(tc.get("test_balance", 1000.0))
            if action == "subtract":
                new_balance = round(old_balance - amount, 2)
                change_str  = f"-{amount:.2f}"
            else:
                new_balance = round(old_balance + amount, 2)
                change_str  = f"+{amount:.2f}"
            tc_write({
                "test_balance":          new_balance,
                "awaiting_deposit_input": False,
                "deposit_action":         None,
            })
            msg = (
                "✅ <b>Депозит обновлён</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"💰 Было              : <b>{old_balance:.2f} USDT</b>\n"
                f"📐 Изменение         : <b>{change_str} USDT</b>\n"
                f"💳 Стало             : <b>{new_balance:.2f} USDT</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🔵 Режим             : simulation\n"
                f"🕐 Обновлено         : {now_str}"
            )
        except (ValueError, TypeError):
            tc_write({"awaiting_deposit_input": False, "deposit_action": None})
            msg = (
                "❌ <b>Ввод отменён</b>\n\n"
                "Некорректная сумма. Введите положительное число.\n"
                "Пример: <code>500</code>"
            )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── Перехват ввода суммы пополнения ───────────────────────────────────────
    tc = tc_read()
    if tc.get("awaiting_topup_input"):
        cleaned = text.strip().replace(",", ".")
        try:
            amount = float(cleaned)
            if amount == 0:
                raise ValueError("zero")
            old_balance = float(tc.get("test_balance", 1000.0))
            new_balance  = round(old_balance + amount, 2)
            if new_balance < 0:
                tc_write({"awaiting_topup_input": False})
                msg = (
                    "❌ <b>Операция отклонена</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"💰 Текущий баланс    : <b>{old_balance:.2f} USDT</b>\n"
                    f"➖ Запрошено         : <b>{amount:.2f} USDT</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "⚠️ Баланс не может быть ниже 0."
                )
                await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
                return
            old_topup = float(tc.get("manual_topup_total", 0.0))
            new_topup = round(old_topup + amount, 2)
            state = tc_write({
                "test_balance":         new_balance,
                "manual_topup_total":   new_topup,
                "awaiting_topup_input": False,
            })
            change_str = f"+{amount:.2f}" if amount > 0 else f"{amount:.2f}"
            msg = (
                "✅ <b>Депозит изменён</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"💰 Старый баланс     : <b>{old_balance:.2f} USDT</b>\n"
                f"📐 Изменение         : <b>{change_str} USDT</b>\n"
                f"💳 Новый баланс      : <b>{new_balance:.2f} USDT</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🔵 Режим             : simulation\n"
                f"🕐 Обновлено         : {state.get('updated_at', 'n/a')}"
            )
        except (ValueError, TypeError):
            tc_write({"awaiting_topup_input": False})
            msg = (
                "❌ <b>Ввод отменён</b>\n\n"
                "Некорректная сумма. Введите число, например:\n"
                "<code>100</code> — добавить\n"
                "<code>-50</code> — убрать"
            )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── Перехват ввода параметра позиции ──────────────────────────────────────
    if tc.get("awaiting_param_input"):
        param = tc["awaiting_param_input"]
        if "Назад" in text:
            tc_write({"awaiting_param_input": None})
            await update.message.reply_text("↩️ Ввод отменён.", reply_markup=get_main_keyboard())
            return
        cleaned = text.strip().replace(",", ".")
        try:
            value = float(cleaned)
            if value <= 0:
                raise ValueError("non-positive")
            state = tc_write({
                f"param_{param}": value,
                "awaiting_param_input": None,
            })
            label = PARAM_LABELS.get(param, param)
            display = f"x{int(value)}" if param == "leverage" else f"{value}"
            msg = (
                f"✅ <b>{label} обновлён</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"📐 Новое значение    : <b>{display}</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "Применяется к новым сделкам.\n"
                f"🕐 Обновлено         : {state.get('updated_at', 'n/a')}"
            )
        except (ValueError, TypeError):
            tc_write({"awaiting_param_input": None})
            msg = (
                "❌ <b>Ввод отменён</b>\n\n"
                "Некорректное значение. Введите положительное число."
            )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── НАЗАД ─────────────────────────────────────────────────────────────────

    if "Назад" in text:
        await update.message.reply_text(
            "↩️ Главное меню", reply_markup=get_main_keyboard()
        )
        return

    # ── NY 5M START ───────────────────────────────────────────────────────────

    if text.strip() == "▶️ NY 5M START":
        started_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        state = tc_write({
            "strategy_mode":       "NY_5M_OPEN",
            "ny_5m_active":        True,
            "ny_5m_started_at":    started_at,
            "test_enabled":        True,
            "hourly_test_enabled": False,
            "scanner_enabled":     True,
            "entries_enabled":     True,
            "monitor_enabled":     True,
            "mode":                "NY_5M_OPEN",
        })
        msg = (
            "▶️ <b>NY 5M OPEN — запущен</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📌 Стратегия     : <b>NY_5M_OPEN</b>\n"
            "🔭 Сканер        : ✅ вкл\n"
            "🎯 Входы         : ✅ вкл\n"
            "🛡 Монитор       : ✅ вкл\n"
            "⏱ Ограничение   : 15 минут\n"
            "🔵 Исполнение    : simulation\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🕐 Старт         : {started_at}\n"
            f"🕐 Обновлено     : {state.get('updated_at', 'n/a')}"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── 5M СТАРТ (FIRST_5M_SESSION) ──────────────────────────────────────────

    if text.strip() == "🚀 5M СТАРТ":
        try:
            started_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            state = tc_write({
                "mode":                   "FIRST_5M_SESSION",
                "first_5m_session_start": started_at,
                "first_5m_fired":         False,
                "scanner_enabled":        True,
                "entries_enabled":        True,
                "monitor_enabled":        True,
            })
            msg = (
                "🚀 <b>FIRST 5M SESSION — запущен</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📌 Стратегия     : <b>FIRST_5M_SESSION</b>\n"
                "📋 Логика        : close 5m &gt; prev high → LONG\n"
                "                   close 5m &lt; prev low  → SHORT\n"
                "🔭 Сканер        : ✅ вкл\n"
                "🎯 Входы         : ✅ вкл\n"
                "🛡 Монитор       : ✅ вкл\n"
                "📊 Сигналов      : 1 (одноразовый)\n"
                "🔵 Исполнение    : simulation\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🕐 Старт         : {started_at}\n"
                f"🕐 Обновлено     : {state.get('updated_at', 'n/a')}"
            )
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        except Exception as e:
            logger.error(f"5M START ERROR: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ Ошибка запуска 5M стратегии",
                reply_markup=get_main_keyboard(),
            )
        return

    # ── СТАРТ ─────────────────────────────────────────────────────────────────

    if "Старт" in text:
        state = tc_write({
            "test_enabled":        True,
            "hourly_test_enabled": True,
            "manual_hour_enabled": False,
            "scanner_enabled":     True,
            "entries_enabled":     True,
            "monitor_enabled":     True,
            "active_filter":       "PREV_CANDLE_BREAKOUT",
            "mode":                "HOURLY_TEST",
        })
        msg = (
            "🟢 <b>Торговый режим включён</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔄 Режим         : <b>HOURLY_TEST</b>\n"
            "📌 Фильтр        : <b>PREV_CANDLE_BREAKOUT</b>\n"
            "🔭 Сканер        : ✅ вкл\n"
            "🎯 Входы         : ✅ вкл\n"
            "🛡 Монитор       : ✅ вкл\n"
            "⏰ Ограничения   : нет (24/7)\n"
            "🔵 Исполнение    : simulation\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🕐 Обновлено     : {state.get('updated_at', 'n/a')}"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── СТОП ──────────────────────────────────────────────────────────────────

    if "Стоп" in text:
        state = tc_write({
            "test_enabled":        False,
            "hourly_test_enabled": False,
            "manual_hour_enabled": False,
            "scanner_enabled":     False,
            "entries_enabled":     False,
            "monitor_enabled":     False,
            "mode":                "OFF",
        })
        msg = (
            "🔴 <b>Торговый режим остановлен</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔄 Режим         : <b>OFF</b>\n"
            "🔭 Сканер        : ❌ выкл\n"
            "🎯 Входы         : ❌ выкл\n"
            "🛡 Монитор       : ❌ выкл\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🕐 Обновлено     : {state.get('updated_at', 'n/a')}"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── СБРОС ─────────────────────────────────────────────────────────────────

    if "Сброс" in text:
        tc_write({
            "reset_pending":       True,
            "scanner_enabled":     False,
            "entries_enabled":     False,
            "monitor_enabled":     False,
            "test_enabled":        False,
            "hourly_test_enabled": False,
            "mode":                "OFF",
        })
        msg = (
            "♻️ <b>Сброс базы данных</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <b>ВНИМАНИЕ!</b> Будут удалены все данные:\n\n"
            "🗄 ENGINE (apex.db):\n"
            "   — T01 scanner_log\n"
            "   — T02 strategy_log\n"
            "   — T03 signal_gate_log\n"
            "   — T04 risk_manager_log\n"
            "   — T05 execution_log\n"
            "   — T06 position_manager_log\n"
            "   — T07 final_trade_results\n"
            "   — T08 system_events_log\n\n"
            "🗄 DATA CORE (data.db):\n"
            "   — final_trade_results\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔴 Торговля остановлена.\n\n"
            "Нажми <b>✅ Подтвердить</b> для выполнения сброса\n"
            "или любую другую кнопку для отмены."
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── ПОДТВЕРДИТЬ ───────────────────────────────────────────────────────────

    if "Подтвердить" in text:
        tc_now = tc_read()
        if not tc_now.get("reset_pending"):
            msg = (
                "✅ <b>Подтверждение</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "Нет активного запроса на сброс.\n"
                "Сначала нажми <b>♻️ Сброс</b>."
            )
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
            return

        engine_counts   = do_reset_engine()
        datacore_counts = do_reset_data_core()

        tc_write({
            "reset_pending":       False,
            "scanner_enabled":     False,
            "entries_enabled":     False,
            "monitor_enabled":     False,
            "test_enabled":        False,
            "hourly_test_enabled": False,
            "mode":                "OFF",
        })

        engine_total = sum(v for v in engine_counts.values() if isinstance(v, int) and v >= 0)

        lines = [
            "✅ <b>Сброс выполнен</b>",
            "━━━━━━━━━━━━━━━━━━",
            "🗄 <b>ENGINE (apex.db)</b>",
        ]
        for table, cnt in engine_counts.items():
            short = table.replace("SKL01_", "")
            mark  = "✅" if isinstance(cnt, int) and cnt >= 0 else "❌"
            lines.append(f"   {mark} {short}: {cnt if isinstance(cnt, int) else cnt}")

        lines.append(f"   Итого удалено: <b>{engine_total}</b> строк")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("🗄 <b>DATA CORE (data.db)</b>")

        local_err = datacore_counts.get("local_error")
        if local_err:
            lines.append(f"   ❌ локальный: {local_err}")
        else:
            local_cnt = datacore_counts.get("local_final_trade_results", 0)
            mark = "✅" if isinstance(local_cnt, int) and local_cnt >= 0 else "❌"
            lines.append(f"   {mark} local final_trade_results: удалено {local_cnt} строк")

        remote_sync = datacore_counts.get("remote_sync", "—")
        sync_mark = "✅" if remote_sync == "ok" else "⚠️"
        lines.append(f"   {sync_mark} remote sync (104.248.206.152): {remote_sync}")

        core03 = datacore_counts.get("core03_reset", "—")
        c03_mark = "✅" if core03 == "ok" else "⚠️"
        lines.append(f"   {c03_mark} Core 03 reset (T07+T_OPEN): {core03}")

        lines += [
            "━━━━━━━━━━━━━━━━━━",
            "🔴 Режим         : OFF",
            "🔭 Сканер        : ❌ выкл",
            "🎯 Входы         : ❌ выкл",
            f"🕐 Обновлено     : {now_str}",
        ]
        await update.message.reply_text(
            "\n".join(lines), parse_mode="HTML", reply_markup=get_main_keyboard()
        )
        return

    # ── ВАУ+ ──────────────────────────────────────────────────────────────────

    if "ВАУ+" in text:
        tc_now    = tc_read()
        info      = get_session_info()
        pnl       = get_pnl_today()
        float_pnl, open_cnt = get_floating_pnl()
        sign      = "+" if pnl >= 0 else ""
        float_sign = "+" if float_pnl >= 0 else ""
        mode_label   = MODE_RU.get(tc_now.get("mode", "OFF"), tc_now.get("mode", "OFF"))
        scanner_icon = "✅" if tc_now.get("scanner_enabled") else "❌"
        entries_icon = "✅" if tc_now.get("entries_enabled") else "❌"

        sl_val   = tc_now.get("param_sl_pct")
        tp1_val  = tc_now.get("param_tp1_pct")
        lev_val  = tc_now.get("param_leverage")
        size_val = tc_now.get("param_size_usdt")

        sl_str   = f"{sl_val}%" if sl_val is not None else "авто"
        tp1_str  = f"{tp1_val}%" if tp1_val is not None else "авто"
        lev_str  = f"x{int(lev_val)}" if lev_val is not None else "x10 (конфиг)"
        size_str = f"{size_val} USDT" if size_val is not None else "авто (1% баланса)"

        msg = (
            "⚡ <b>ВАУ+</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🕒 Сессия        : <b>{info['session']}</b>\n"
            f"📌 Состояние     : <b>{info['status']}</b>\n"
            f"⏳ До конца      : <b>{info['time_left']}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🔄 Режим         : <b>{mode_label}</b>\n"
            f"🔭 Сканер        : {scanner_icon}\n"
            f"🎯 Входы         : {entries_icon}\n"
            "🛡 Монитор       : ✅\n"
            "🔵 Исполнение    : simulation\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📋 Позиции       : <b>{open_cnt}</b>\n"
            f"📊 PnL за день   : <b>{sign}{pnl:.2f} USDT</b>\n"
            f"📉 Floating PnL  : <b>{float_sign}{float_pnl:.2f} USDT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🎯 SL / TP1      : <b>{sl_str} / {tp1_str}</b>\n"
            f"⚡ Плечо         : <b>{lev_str}</b>\n"
            f"📦 Размер        : <b>{size_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🕐 Обновлено     : {now_str}"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_vau_keyboard())
        return

    # ── SL/TP подменю ─────────────────────────────────────────────────────────

    if "SL/TP" in text:
        tc_now = tc_read()
        sl_val  = tc_now.get("param_sl_pct")
        tp1_val = tc_now.get("param_tp1_pct")
        tp2_val = tc_now.get("param_tp2_pct")
        tp3_val = tc_now.get("param_tp3_pct")

        def _fmt(v):
            return f"<b>{v}%</b>" if v is not None else "<i>авто</i>"

        msg = (
            "🎯 <b>SL / TP</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"SL   : {_fmt(sl_val)}\n"
            f"TP1  : {_fmt(tp1_val)}\n"
            f"TP2  : {_fmt(tp2_val)}\n"
            f"TP3  : {_fmt(tp3_val)}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Авто — рассчитывается стратегией.\n"
            "Выбери параметр для изменения:"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_sltp_keyboard())
        return

    # ── Отдельные SL / TP1 / TP2 / TP3 ───────────────────────────────────────

    if text.strip() == "🎯 SL":
        tc_now = tc_read()
        current = tc_now.get("param_sl_pct")
        cur_str = f"{current}%" if current is not None else "авто (стратегия)"
        tc_write({"awaiting_param_input": "sl_pct"})
        msg = (
            "🎯 <b>Изменить SL %</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Текущий SL       : <b>{cur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите SL в % от цены входа.\n"
            "Пример: <code>0.4</code> — это 0.4%"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    if text.strip() == "🎯 TP1":
        tc_now = tc_read()
        current = tc_now.get("param_tp1_pct")
        cur_str = f"{current}%" if current is not None else "авто (стратегия)"
        tc_write({"awaiting_param_input": "tp1_pct"})
        msg = (
            "🎯 <b>Изменить TP1 %</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Текущий TP1      : <b>{cur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите TP1 в % от цены входа.\n"
            "Пример: <code>0.4</code> — это 0.4%"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    if text.strip() == "🎯 TP2":
        tc_now = tc_read()
        current = tc_now.get("param_tp2_pct")
        cur_str = f"{current}%" if current is not None else "авто (стратегия)"
        tc_write({"awaiting_param_input": "tp2_pct"})
        msg = (
            "🎯 <b>Изменить TP2 %</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Текущий TP2      : <b>{cur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите TP2 в % от цены входа.\n"
            "Пример: <code>0.8</code> — это 0.8%"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    if text.strip() == "🎯 TP3":
        tc_now = tc_read()
        current = tc_now.get("param_tp3_pct")
        cur_str = f"{current}%" if current is not None else "авто (стратегия)"
        tc_write({"awaiting_param_input": "tp3_pct"})
        msg = (
            "🎯 <b>Изменить TP3 %</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Текущий TP3      : <b>{cur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите TP3 в % от цены входа.\n"
            "Пример: <code>1.2</code> — это 1.2%"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── ПЛЕЧО ─────────────────────────────────────────────────────────────────

    if "Плечо" in text:
        tc_now = tc_read()
        current = tc_now.get("param_leverage")
        cur_str = f"x{int(current)}" if current is not None else "x10 (из конфига)"
        tc_write({"awaiting_param_input": "leverage"})
        msg = (
            "⚡ <b>Изменить плечо</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Текущее плечо    : <b>{cur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите новое плечо.\n"
            "Пример: <code>10</code>"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── ПОЗИЦИЯ (размер) ──────────────────────────────────────────────────────

    if "Позиция" in text:
        tc_now = tc_read()
        current = tc_now.get("param_size_usdt")
        cur_str = f"{current} USDT" if current is not None else "авто (1% от баланса)"
        tc_write({"awaiting_param_input": "size_usdt"})
        msg = (
            "📦 <b>Изменить размер позиции</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Текущий размер   : <b>{cur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите фиксированный размер позиции в USDT.\n"
            "Пример: <code>50</code>"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── СТАТУС ────────────────────────────────────────────────────────────────

    if "Статус" in text:
        tc_now           = tc_read()
        info             = get_session_info()
        trades           = get_trades_count()
        float_pnl, open_cnt = get_floating_pnl()
        last_activity    = get_last_activity()
        pnl              = get_pnl_today()
        balance          = float(tc_now.get("test_balance", 1000.0))
        current_bal      = round(balance + pnl, 2)
        sign             = "+" if pnl >= 0 else ""
        float_sign       = "+" if float_pnl >= 0 else ""
        db_status        = "✅ доступна" if db_exists() else "❌ недоступна"
        mode_label       = MODE_RU.get(tc_now.get("mode", "OFF"), tc_now.get("mode", "OFF"))
        scanner_icon     = "✅" if tc_now.get("scanner_enabled") else "❌"
        entries_icon     = "✅" if tc_now.get("entries_enabled") else "❌"

        msg = (
            "📊 <b>Статус системы</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🔄 Режим         : <b>{mode_label}</b>\n"
            f"🔭 Сканер        : {scanner_icon}\n"
            f"🎯 Входы         : {entries_icon}\n"
            "🛡 Монитор       : ✅\n"
            f"🗄 База данных   : {db_status}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🕒 Сессия        : <b>{info['session']}</b>\n"
            f"⏳ До конца      : <b>{info['time_left']}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"💰 Баланс        : <b>{balance:.2f} USDT</b>\n"
            f"📊 PnL за день   : <b>{sign}{pnl:.2f} USDT</b>\n"
            f"📉 Floating PnL  : <b>{float_sign}{float_pnl:.2f} USDT</b>\n"
            f"💳 Текущий       : <b>{current_bal:.2f} USDT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📋 Позиций       : <b>{open_cnt}</b>\n"
            f"🗂 Сделок сегодня: <b>{trades}</b>\n"
            f"🕐 Посл. сделка  : {last_activity}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🕐 Обновлено     : {now_str}"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── ПОЗИЦИИ ───────────────────────────────────────────────────────────────

    if "Позиции" in text:
        rows  = get_open_positions()
        count = len(rows)
        if not rows:
            msg = (
                "📍 <b>Позиции</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📋 Открытых позиций: <b>0</b>\n\n"
                "Активных позиций нет."
            )
        else:
            lines = [
                f"📍 <b>Открытые позиции — {count} шт.</b>",
                "━━━━━━━━━━━━━━━━━━",
            ]
            for symbol, direction, fill_price, size, opened_at, sl, tp1, tp2, tp3 in rows:
                arrow        = "📈" if direction == "long" else "📉"
                symbol_short = str(symbol).replace(":USDT", "")
                dir_ru       = "лонг" if direction == "long" else "шорт"
                sl_str  = f"{sl}" if sl else "—"
                tp1_str = f"{tp1}" if tp1 else "—"
                tp2_str = f"{tp2}" if tp2 else "—"
                tp3_str = f"{tp3}" if tp3 else "—"
                lines.append(
                    f"{arrow} <b>{symbol_short}</b>  {dir_ru}  вход: {fill_price}  объём: {size}\n"
                    f"     🛡 SL: {sl_str}  🎯 TP1: {tp1_str}\n"
                    f"     🎯 TP2: {tp2_str}  🎯 TP3: {tp3_str}\n"
                    f"     🕐 {safe_format_dt(opened_at)}"
                )
                lines.append("─────────────────")
            lines.append(f"━━━━━━━━━━━━━━━━━━\n📋 Итого открытых: <b>{count}</b>")
            msg = "\n".join(lines)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── ➕ ДЕПОЗИТ (добавить) ─────────────────────────────────────────────────

    if text.strip() == "➕ Депозит":
        tc_now  = tc_read()
        balance = float(tc_now.get("test_balance", 1000.0))
        tc_write({"awaiting_deposit_input": True, "deposit_action": "add"})
        msg = (
            "➕ <b>Пополнение депозита</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"💰 Текущий баланс    : <b>{balance:.2f} USDT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите сумму пополнения в USDT.\n"
            "Пример: <code>500</code>"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── ➖ СНЯТЬ (уменьшить) ──────────────────────────────────────────────────

    if text.strip() == "➖ Снять":
        tc_now  = tc_read()
        balance = float(tc_now.get("test_balance", 1000.0))
        tc_write({"awaiting_deposit_input": True, "deposit_action": "subtract"})
        msg = (
            "➖ <b>Списание с депозита</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"💰 Текущий баланс    : <b>{balance:.2f} USDT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите сумму списания в USDT.\n"
            "Пример: <code>200</code>"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── ДЕПОЗИТ (инфо) ────────────────────────────────────────────────────────

    if "Депозит" in text:
        tc_now  = tc_read()
        balance = float(tc_now.get("test_balance", 1000.0))
        topup   = float(tc_now.get("manual_topup_total", 0.0))
        pnl     = get_pnl_today()
        current = round(balance + pnl, 2)
        sign    = "+" if pnl >= 0 else ""

        msg = (
            "💵 <b>Тестовый депозит</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"💰 Начальный баланс  : <b>{balance:.2f} USDT</b>\n"
            f"📊 PnL за день       : <b>{sign}{pnl:.2f} USDT</b>\n"
            f"💳 Текущий баланс    : <b>{current:.2f} USDT</b>\n"
            f"➕ Пополнено вручную : <b>{topup:.2f} USDT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔵 Режим             : simulation\n"
            f"🕐 Обновлено         : {now_str}"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── ДОБАВИТЬ ──────────────────────────────────────────────────────────────

    if "Добавить" in text:
        tc_write({"awaiting_topup_input": True})
        tc_now  = tc_read()
        balance = float(tc_now.get("test_balance", 1000.0))
        msg = (
            "💵 <b>Изменение тестового депозита</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"💰 Текущий баланс    : <b>{balance:.2f} USDT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите сумму изменения в USDT:\n"
            "<code>100</code> или <code>+100</code> — добавить\n"
            "<code>-100</code> — убрать\n\n"
            "🔵 Режим: simulation"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # Любая другая кнопка/текст — сбрасываем reset_pending если был
    tc_now = tc_read()
    if tc_now.get("reset_pending"):
        tc_write({"reset_pending": False})

    await update.message.reply_text(
        "Команда не распознана.",
        reply_markup=get_main_keyboard()
    )
