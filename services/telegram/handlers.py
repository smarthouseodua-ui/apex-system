from modules.runtime_state import load_runtime_state as _load_runtime_state

def _get_scanner_state():
    try:
        return _load_runtime_state().get("scanner", {})
    except:
        return {}
scanner_state = type("_SS", (), {"get": lambda self, k, d=0: _get_scanner_state().get(k, d)})()
import logging
import os
import sqlite3
import subprocess
from datetime import datetime
from typing import Any

import aiohttp

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger("apex.telegram")

from .auth import is_allowed
from .keyboard import get_main_keyboard, get_vau_keyboard, get_settings_keyboard, get_reset_keyboard


STRATEGY_API = "http://104.248.206.152:8095"

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
    "ASIA+HK":   "Азия + Гонконг",
    "HONG_KONG": "Гонконг",
    "LONDON":    "Лондон",
    "LONDON+NY": "Лондон + Нью-Йорк",
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
    "ON":               "вкл",
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
        from core.session_engine import get_active_session, get_all_sessions

        active = get_active_session()
        if not active:
            return {
                "session":    "—",
                "фаза":       "ОЖИДАНИЕ",
                "status":     "не активна",
                "time_left":  "—",
                "подсказка":  "Все сессии закрыты",
                "is_trading": False,
                "сигнал_разрешён": False,
            }

        return {
            "session":    active["сессия"],
            "фаза":       active["фаза"],
            "status":     active["фаза"],
            "time_left":  active.get("до_закрытия_мин", active.get("до_конца_входа_мин", active.get("до_60_мин", "—"))),
            "подсказка":  active["подсказка"],
            "is_trading": active["фаза"] not in ("ОЖИДАНИЕ", "СЕССИЯ ЗАКРЫТА"),
            "сигнал_разрешён": active["сигнал_разрешён"],
        }
    except Exception:
        return {
            "session":    "—",
            "фаза":       "—",
            "status":     "—",
            "time_left":  "—",
            "подсказка":  "—",
            "is_trading": False,
            "сигнал_разрешён": False,
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
            ORDER BY rowid DESC
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

async def turn_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ запрещён")
        return
    try:
        from services.test_control import read as tc_read, write as tc_write
        tc_write({"trading_enabled": True})
        await update.message.reply_text("🟢 Trading ENABLED")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")


async def turn_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ запрещён")
        return
    try:
        from services.test_control import read as tc_read, write as tc_write
        tc_write({"trading_enabled": False})
        await update.message.reply_text("🔴 Trading DISABLED")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ запрещён")
        return

    try:
        from storage.db.repository import Repository
        from services.test_control import read as tc_read

        repo = Repository()
        tc = tc_read()
        open_positions = repo.get_open_positions()
        session_trades = repo.get_session_trade_count()
        trading_enabled = tc.get("trading_enabled", False)
        mode = tc.get("mode", "OFF")

        msg = (
            f"⚡ <b>APEX STATUS</b>\n\n"
            f"Trading: <b>{'LIVE' if trading_enabled else 'DISABLED'}</b>\n"
            f"Mode: <b>{mode}</b>\n"
            f"Open positions: <b>{len(open_positions)}</b>\n"
            f"Trades today: <b>{session_trades}</b>\n"
        )
    except Exception as e:
        msg = f"⚠️ Status error: {e}"

    await update.message.reply_text(msg, parse_mode="HTML")


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

    tc = tc_read()

    # ── Сброс awaiting-состояний при нажатии кнопки главного меню ─────────────
    MAIN_MENU_BUTTONS = [
        "📊 Статус", "⚡ ВАУ+", "🟢 Старт", "🔴 Стоп",
        "📍 Позиции", "♻️ Сброс", "⚙️ Настройка бота"
    ]
    if text.strip() in MAIN_MENU_BUTTONS:
        tc_write({
            "awaiting_strategy_apply": False,
            "awaiting_param_input": None,
            "awaiting_reset_confirm": False,
            "strategy_list": None,
        })

    # ── Перехват ввода параметра (SL / Плечо / Позиция±) ─────────────────────
    if tc.get("awaiting_param_input"):
        param = tc["awaiting_param_input"]
        if "Назад" in text or "Отмена" in text:
            tc_write({"awaiting_param_input": None})
            await update.message.reply_text("↩️ Ввод отменён.", reply_markup=get_settings_keyboard())
            return
        cleaned = text.strip().replace(",", ".")
        try:
            value = float(cleaned)
            if value <= 0:
                raise ValueError("non-positive")

            if param == "size_add":
                current = float(tc.get("param_size_usdt") or 0)
                new_val = round(current + value, 2)
                state = tc_write({"param_size_usdt": new_val, "awaiting_param_input": None})
                msg = (
                    "✅ <b>Размер позиции увеличен</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"Было             : <b>{current} USDT</b>\n"
                    f"Добавлено        : <b>+{value} USDT</b>\n"
                    f"Стало            : <b>{new_val} USDT</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"🕐 Обновлено         : {state.get('updated_at', 'n/a')}"
                )
            elif param == "size_sub":
                current = float(tc.get("param_size_usdt") or 0)
                new_val = round(current - value, 2)
                if new_val < 10:
                    tc_write({"awaiting_param_input": None})
                    msg = (
                        "❌ <b>Операция отклонена</b>\n"
                        "━━━━━━━━━━━━━━━━━━\n"
                        f"Текущий размер   : <b>{current} USDT</b>\n"
                        f"Убрать           : <b>{value} USDT</b>\n"
                        f"Результат        : <b>{new_val} USDT</b>\n"
                        "━━━━━━━━━━━━━━━━━━\n"
                        "⚠️ Минимальный размер позиции: 10 USDT"
                    )
                    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_settings_keyboard())
                    return
                state = tc_write({"param_size_usdt": new_val, "awaiting_param_input": None})
                msg = (
                    "✅ <b>Размер позиции уменьшен</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"Было             : <b>{current} USDT</b>\n"
                    f"Убрано           : <b>{value} USDT</b>\n"
                    f"Стало            : <b>{new_val} USDT</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"🕐 Обновлено         : {state.get('updated_at', 'n/a')}"
                )
            else:
                state = tc_write({f"param_{param}": value, "awaiting_param_input": None})
                label = PARAM_LABELS.get(param, param)
                display = f"x{int(value)}" if param == "leverage" else f"{value}%"
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
            msg = "❌ <b>Ввод отменён</b>\n\nНекорректное значение. Введите положительное число."
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_settings_keyboard())
        return

    # ── Перехват выбора стратегии для Старт ──────────────────────────────────
    if tc.get("awaiting_strategy_apply"):
        if "Назад" in text:
            tc_write({"awaiting_strategy_apply": False, "strategy_list": None})
            await update.message.reply_text("↩️ Выбор отменён.", reply_markup=get_main_keyboard())
            return
        try:
            idx = int(text.strip()) - 1
            strategy_list = tc.get("strategy_list", [])
            if idx < 0 or idx >= len(strategy_list):
                raise ValueError("out of range")
            filename = strategy_list[idx]
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{STRATEGY_API}/strategies/apply",
                    params={"filename": filename},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(f"API {resp.status}: {body}")
            strategy_name = filename.replace(".docx", "").replace(".pdf", "")
            state = tc_write({
                "awaiting_strategy_apply": False,
                "strategy_list":           None,
                "test_enabled":            True,
                "scanner_enabled":         True,
                "entries_enabled":         True,
                "monitor_enabled":         True,
                "mode":                    "ON",
                "active_filter":           strategy_name,
                "stop_pending":            False,
            })
            msg = (
                "✅ <b>Запущено!</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"📄 Стратегия      : <b>{strategy_name}</b>\n"
                "🔭 Сканер         : ✅ вкл\n"
                "🎯 Входы          : ✅ вкл\n"
                "🛡 Монитор        : ✅ вкл\n"
                "🔵 Исполнение     : simulation\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🕐 Обновлено      : {now_str}"
            )
        except (ValueError, IndexError):
            msg = "❌ Некорректный номер. Отправь число из списка."
        except Exception as e:
            logger.error(f"Strategy apply error: {e}", exc_info=True)
            tc_write({"awaiting_strategy_apply": False, "strategy_list": None})
            msg = f"❌ Ошибка применения стратегии: {e}"
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ══════════════════════════════════════════════════════════════════════════
    #  КНОПКИ
    # ══════════════════════════════════════════════════════════════════════════

    # ── НАСТРОЙКА БОТА ────────────────────────────────────────────────────────

    if "Настройка бота" in text:
        tc_write({"current_menu": "settings"})
        tc_now = tc_read()
        sl_val   = tc_now.get("param_sl_pct")
        tp1_val  = tc_now.get("param_tp1_pct")
        tp2_val  = tc_now.get("param_tp2_pct")
        tp3_val  = tc_now.get("param_tp3_pct")
        lev_val  = tc_now.get("param_leverage")
        size_val = tc_now.get("param_size_usdt")
        sl_str   = f"{sl_val}%" if sl_val is not None else "авто"
        tp1_str  = f"{tp1_val}%" if tp1_val is not None else "авто"
        tp2_str  = f"{tp2_val}%" if tp2_val is not None else "авто"
        tp3_str  = f"{tp3_val}%" if tp3_val is not None else "авто"
        lev_str  = f"x{int(lev_val)}" if lev_val is not None else "x10 (конфиг)"
        size_str = f"{size_val} USDT" if size_val is not None else "авто"
        msg = (
            "⚙️ <b>Настройка бота</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🎯 Стоп-лосс     : <b>{sl_str}</b>\n"
            f"🎯 ТП1           : <b>{tp1_str}</b>\n"
            f"🎯 ТП2           : <b>{tp2_str}</b>\n"
            f"🎯 ТП3           : <b>{tp3_str}</b>\n"
            f"⚡ Плечо          : <b>{lev_str}</b>\n"
            f"📦 Позиция        : <b>{size_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Выбери параметр для изменения:"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_settings_keyboard())
        return

    # ── НАЗАД / ОТМЕНА ────────────────────────────────────────────────────────

    if "Назад" in text or "Отмена" in text:
        tc_write({"current_menu": "main", "reset_pending": False})
        await update.message.reply_text("↩️ Главное меню", reply_markup=get_main_keyboard())
        return

    # ── СТОП-ЛОСС ────────────────────────────────────────────────────────────

    if "Стоп-лосс" in text:
        tc_now = tc_read()
        current = tc_now.get("param_sl_pct")
        cur_str = f"{current}%" if current is not None else "авто (стратегия)"
        tc_write({"awaiting_param_input": "sl_pct"})
        msg = (
            "🎯 <b>Изменить стоп-лосс</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Текущий SL       : <b>{cur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите SL в % от цены входа.\n"
            "Пример: <code>1.5</code> — это 1.5%"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_settings_keyboard())
        return

    # ── ТП1 / ТП2 / ТП3 ─────────────────────────────────────────────────────

    if text.strip() == "🎯 ТП1":
        tc_now = tc_read()
        current = tc_now.get("param_tp1_pct")
        cur_str = f"{current}%" if current is not None else "авто (стратегия)"
        tc_write({"awaiting_param_input": "tp1_pct"})
        msg = (
            "🎯 <b>Изменить ТП1</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Текущий TP1      : <b>{cur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите TP1 в % от цены входа.\n"
            "Пример: <code>1.5</code> — это 1.5%"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_settings_keyboard())
        return

    if text.strip() == "🎯 ТП2":
        tc_now = tc_read()
        current = tc_now.get("param_tp2_pct")
        cur_str = f"{current}%" if current is not None else "авто (стратегия)"
        tc_write({"awaiting_param_input": "tp2_pct"})
        msg = (
            "🎯 <b>Изменить ТП2</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Текущий TP2      : <b>{cur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите TP2 в % от цены входа.\n"
            "Пример: <code>3.0</code> — это 3.0%"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_settings_keyboard())
        return

    if text.strip() == "🎯 ТП3":
        tc_now = tc_read()
        current = tc_now.get("param_tp3_pct")
        cur_str = f"{current}%" if current is not None else "авто (стратегия)"
        tc_write({"awaiting_param_input": "tp3_pct"})
        msg = (
            "🎯 <b>Изменить ТП3</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Текущий TP3      : <b>{cur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите TP3 в % от цены входа.\n"
            "Пример: <code>4.5</code> — это 4.5%"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_settings_keyboard())
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
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_settings_keyboard())
        return

    # ── ПОЗИЦИЯ+ ──────────────────────────────────────────────────────────────

    if text.strip() == "➕ Позиция+":
        tc_now = tc_read()
        current = tc_now.get("param_size_usdt")
        cur_str = f"{current} USDT" if current is not None else "авто (1% от баланса)"
        tc_write({"awaiting_param_input": "size_add"})
        msg = (
            "➕ <b>Увеличить размер позиции</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Текущий размер   : <b>{cur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите сумму для добавления в USDT.\n"
            "Пример: <code>10</code>"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_settings_keyboard())
        return

    # ── ПОЗИЦИЯ- ──────────────────────────────────────────────────────────────

    if text.strip() == "➖ Позиция-":
        tc_now = tc_read()
        current = tc_now.get("param_size_usdt")
        cur_str = f"{current} USDT" if current is not None else "авто (1% от баланса)"
        tc_write({"awaiting_param_input": "size_sub"})
        msg = (
            "➖ <b>Уменьшить размер позиции</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Текущий размер   : <b>{cur_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Введите сумму для уменьшения в USDT.\n"
            "Минимальный размер: 10 USDT"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_settings_keyboard())
        return

    # ── СТАРТ (выбор стратегии) ───────────────────────────────────────────────

    if "Старт" in text:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{STRATEGY_API}/strategies", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
            strategies = data if isinstance(data, list) else data.get("strategies", [])
            if not strategies:
                await update.message.reply_text(
                    "❌ Нет доступных стратегий.", reply_markup=get_main_keyboard()
                )
                return
            lines = ["🟢 <b>Выберите стратегию для запуска:</b>\n"]
            for i, s in enumerate(strategies, 1):
                name = s if isinstance(s, str) else s.get("filename", s.get("name", str(s)))
                lines.append(f"{i}. <code>{name}</code>")
            lines.append("\nОтправь номер стратегии чтобы запустить.")
            tc_write({
                "awaiting_strategy_apply": True,
                "strategy_list": [s if isinstance(s, str) else s.get("filename", s.get("name", str(s))) for s in strategies],
                "stop_pending": False,
            })
            await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=get_main_keyboard())
        except Exception as e:
            logger.error(f"СТАРТ strategies error: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ Ошибка получения списка стратегий.", reply_markup=get_main_keyboard()
            )
        return

    # ── СТОП (с подтверждением) ───────────────────────────────────────────────

    if "Стоп" in text:
        tc_now = tc_read()
        if tc_now.get("stop_pending"):
            # При остановке — сброс параметров на базовые значения.
            # При следующем Старт стратегия загрузит свои параметры.
            state = tc_write({
                "test_enabled":        False,
                "hourly_test_enabled": False,
                "manual_hour_enabled": False,
                "scanner_enabled":     False,
                "entries_enabled":     False,
                "monitor_enabled":     False,
                "mode":                "OFF",
                "stop_pending":        False,
                "active_filter":       None,
                "strategy_direction":  None,
                "strategy_timeframe":  None,
                "param_sl_pct":        1.0,
                "param_tp1_pct":       1.5,
                "param_tp2_pct":       2.5,
                "param_tp3_pct":       3.5,
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
        else:
            tc_write({"stop_pending": True})
            msg = (
                "⚠️ <b>Вы уверены что хотите остановить бота?</b>\n\n"
                "Нажмите 🔴 <b>Стоп</b> ещё раз для подтверждения."
            )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── СБРОС (двойное подтверждение) ─────────────────────────────────────────

    if "Сброс" in text:
        tc_now = tc_read()
        if tc_now.get("reset_pending"):
            # Второе нажатие — выполняем сброс
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
                "active_filter":       None,
                "strategy_direction":  None,
                "strategy_timeframe":  None,
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
                f"🕐 Обновлено     : {now_str}",
            ]
            await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=get_main_keyboard())
        else:
            # Первое нажатие — предупреждение
            tc_write({
                "reset_pending":       True,
                "scanner_enabled":     False,
                "entries_enabled":     False,
                "monitor_enabled":     False,
                "test_enabled":        False,
                "hourly_test_enabled": False,
                "mode":                "OFF",
                "active_filter":       None,
                "strategy_direction":  None,
                "strategy_timeframe":  None,
            })
            msg = (
                "⚠️ <b>Подтверждение сброса</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "Будут удалены ВСЕ данные торговли.\n"
                "🔴 Торговля остановлена.\n\n"
                "Нажми <b>♻️ Сброс</b> ещё раз для подтверждения\n"
                "или <b>◀️ Отмена</b> для отмены."
            )
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_reset_keyboard())
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
        monitor_icon = "✅" if tc_now.get("monitor_enabled") else "❌"
        active_filter = tc_now.get("active_filter") or "—"
        sl_val   = tc_now.get("param_sl_pct")
        tp1_val  = tc_now.get("param_tp1_pct")
        tp2_val  = tc_now.get("param_tp2_pct")
        tp3_val  = tc_now.get("param_tp3_pct")
        lev_val  = tc_now.get("param_leverage")
        size_val = tc_now.get("param_size_usdt")
        sl_str   = f"{sl_val}%" if sl_val is not None else "авто"
        tp1_str  = f"{tp1_val}%" if tp1_val is not None else "авто"
        tp2_str  = f"{tp2_val}%" if tp2_val is not None else "авто"
        tp3_str  = f"{tp3_val}%" if tp3_val is not None else "авто"
        lev_str  = f"x{int(lev_val)}" if lev_val is not None else "x10 (конфиг)"
        size_str = f"{size_val} USDT" if size_val is not None else "авто (1% баланса)"

        msg = (
            "⚡ <b>ВАУ+</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"<code>🕐 Сессия      </code> <b>{info['session']}</b>\n"
            f"<code>📌 Фаза        </code> <b>{info['фаза']}</b>\n"
            f"<code>🎯 Сигнал      </code> <b>{'СИГНАЛ РАЗРЕШЁН' if info.get('сигнал_разрешён') else 'СИГНАЛ ЗАПРЕЩЁН'}</b>\n"
            f"<code>💡 Подсказка   </code> <i>{info.get('подсказка', '—')}</i>\n"
            "\n"
            f"<code>⚙️ Режим       </code> <b>{mode_label}</b>\n"
            f"<code>📄 Стратегия   </code> <b>{active_filter}</b>\n"
            f"<code>🔭 Сканер      </code> {scanner_icon}\n"
            f"<code>🎯 Входы       </code> {entries_icon}\n"
            f"<code>🛡 Монитор     </code> {monitor_icon}\n"
            f"<code>🔵 Исполнение  </code> simulation\n"
            f"\n"
            f"<code>📡 Universe    </code> <b>{scanner_state.get('total_pairs', 0)}</b>\n"
            f"<code>💧 Ликвидность </code> <b>{scanner_state.get('after_liquidity', 0)}</b>\n"
            f"<code>📈 Волатильность</code> <b>{scanner_state.get('after_volatility', 0)}</b>\n"
            f"<code>🏗 Структура   </code> <b>{scanner_state.get('after_structure', 0)}</b>\n"
            f"<code>🎯 Кандидаты   </code> <b>{scanner_state.get('candidates', 0)}</b>\n"
            "\n"
            f"<code>📊 Позиции     </code> <b>{open_cnt}</b>\n"
            f"<code>💰 PnL за день </code> <b>{sign}{pnl:.2f} USDT</b>\n"
            f"<code>📉 Float PnL   </code> <b>{float_sign}{float_pnl:.2f} USDT</b>\n"
            "\n"
            f"<code>⚖️ SL           </code> <b>{sl_str}</b>\n"
            f"<code>🎯 TP1          </code> <b>{tp1_str}</b>\n"
            f"<code>🎯 TP2          </code> <b>{tp2_str}</b>\n"
            f"<code>🎯 TP3          </code> <b>{tp3_str}</b>\n"
            f"<code>⚡ Плечо        </code> <b>{lev_str}</b>\n"
            f"<code>📦 Размер       </code> <b>{size_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"<code>🕐 Обновлено   </code> {now_str}"
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
        monitor_icon     = "✅" if tc_now.get("monitor_enabled") else "❌"

        msg = (
            f"📊 <b>Статус системы</b>\n"
            f"\n"
            f"<code>"
            f"Сессия      {info['session']}\n"
            f"До конца    {info['time_left']}\n"
            f"\n"
            f"Режим       {mode_label}\n"
            f"Сканер      {scanner_icon}\n"
            f"Входы       {entries_icon}\n"
            f"Монитор     {monitor_icon}\n"
            f"База данных {db_status}\n"
            f"\n"
            f"Баланс      {balance:.2f} USDT\n"
            f"PnL за день {sign}{pnl:.2f} USDT\n"
            f"Float PnL   {float_sign}{float_pnl:.2f} USDT\n"
            f"Текущий     {current_bal:.2f} USDT\n"
            f"\n"
            f"Позиций     {open_cnt}\n"
            f"Сделок      {trades}\n"
            f"Посл.сделка {last_activity}\n"
            f"</code>"
            f"\n"
            f"🕐 <i>Обновлено {now_str}</i>"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── ПОЗИЦИИ ───────────────────────────────────────────────────────────────

    if "Позиции" in text:
        open_cnt = get_open_positions_count()
        closed   = get_trades_count()
        rows     = get_open_positions()
        if not rows:
            msg = (
                "📍 <b>Позиции</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"Открытых сделок   : <b>{open_cnt}</b>\n"
                f"Закрытых сделок   : <b>{closed}</b>"
            )
        else:
            lines = [
                "📍 <b>Позиции</b>",
                "━━━━━━━━━━━━━━━━━━",
                f"Открытых сделок   : <b>{len(rows)}</b>",
                f"Закрытых сделок   : <b>{closed}</b>",
                "━━━━━━━━━━━━━━━━━━",
            ]
            for symbol, direction, fill_price, size, opened_at, sl, tp1, tp2, tp3 in rows:
                arrow        = "📈" if direction == "long" else "📉"
                symbol_short = str(symbol).replace(":USDT", "")
                dir_ru       = "лонг" if direction == "long" else "шорт"
                sl_str  = f"{sl}" if sl else "—"
                tp1_str = f"{tp1}" if tp1 else "—"
                lines.append(
                    f"{arrow} <b>{symbol_short}</b>  {dir_ru}  вход: {fill_price}  объём: {size}\n"
                    f"     🛡 SL: {sl_str}  🎯 TP1: {tp1_str}\n"
                    f"     🕐 {safe_format_dt(opened_at)}"
                )
                lines.append("─────────────────")
            msg = "\n".join(lines)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        return

    # ── FALLBACK ──────────────────────────────────────────────────────────────
    tc_now = tc_read()
    if tc_now.get("reset_pending"):
        tc_write({"reset_pending": False})

    menu = tc_now.get("current_menu", "main")
    if menu == "settings":
        fallback_kb = get_settings_keyboard()
    else:
        fallback_kb = get_main_keyboard()

    await update.message.reply_text("Команда не распознана.", reply_markup=fallback_kb)
