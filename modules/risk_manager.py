# risk_manager.py
"""
APEX PROTOCOL™ — Risk Manager

Контроль риска + сессионный фильтр на базе SessionPhase.
Новые сделки разрешены ТОЛЬКО в фазе EXECUTION (0–90 мин от session_open).
"""

import logging
from datetime import datetime
from core.time_manager import SessionPhase, get_session_phase

logger = logging.getLogger("apex.risk_manager")

MAX_POSITIONS = 5
RISK_PER_TRADE = 0.01

MAX_DAILY_LOSS = -50      # USDT
MAX_TOTAL_LOSS = -200     # USDT

LOSS_STREAK_LIMIT = 3

STATE = {
    "daily_pnl": 0.0,
    "total_pnl": 0.0,
    "loss_streak": 0,
    "blocked": False,
    "last_reset_day": datetime.utcnow().date()
}


# ── Сессионный фильтр ─────────────────────────────────────────────────────

def check_session_filter() -> tuple[bool, dict]:
    """
    Проверяет, разрешена ли торговля.
    Новые сделки — ТОЛЬКО в фазе EXECUTION.
    """
    phase, session, minutes_in = get_session_phase()
    phase_str = phase.value

    if phase == SessionPhase.EXECUTION:
        info = {
            "session": session,
            "phase": phase_str,
            "allowed": True,
            "reason": "ok",
            "minutes_in": minutes_in,
        }
        logger.info(
            f"[SESSION FILTER] session={session} phase={phase_str} "
            f"allowed=true min={minutes_in}"
        )
        return True, info

    # Все остальные фазы — запрет
    reason_map = {
        SessionPhase.PRE_SESSION: "pre_session",
        SessionPhase.OBSERVATION: "observation_mode",
        SessionPhase.HARD_CLOSE:  "hard_close",
        SessionPhase.OFF:         "outside_session",
    }
    info = {
        "session": session,
        "phase": phase_str,
        "allowed": False,
        "reason": reason_map.get(phase, "unknown"),
        "minutes_in": minutes_in,
    }
    logger.info(
        f"[SESSION FILTER] session={session} phase={phase_str} "
        f"allowed=false reason={info['reason']} min={minutes_in}"
    )
    return False, info


# ── PnL / лимиты (без изменений) ──────────────────────────────────────────

def reset_daily():
    today = datetime.utcnow().date()

    if STATE["last_reset_day"] != today:
        STATE["daily_pnl"] = 0.0
        STATE["loss_streak"] = 0
        STATE["last_reset_day"] = today


def update_after_trade(pnl: float):
    reset_daily()

    STATE["daily_pnl"] += pnl
    STATE["total_pnl"] += pnl

    if pnl < 0:
        STATE["loss_streak"] += 1
    else:
        STATE["loss_streak"] = 0

    check_limits()


def check_limits():
    if STATE["daily_pnl"] <= MAX_DAILY_LOSS:
        STATE["blocked"] = True

    if STATE["total_pnl"] <= MAX_TOTAL_LOSS:
        STATE["blocked"] = True

    if STATE["loss_streak"] >= LOSS_STREAK_LIMIT:
        STATE["blocked"] = True


def can_trade(current_positions: int) -> bool:
    """
    Главная точка входа для execution_engine.
    Проверяет:
    1. Сессионный фильтр (SessionPhase)
    2. Блокировку по PnL / серии убытков
    3. Лимит позиций
    """
    reset_daily()

    # 1. Сессионный фильтр
    session_ok, session_info = check_session_filter()
    if not session_ok:
        return False

    # 2. PnL / streak блокировка
    if STATE["blocked"]:
        return False

    # 3. Лимит позиций
    if current_positions >= MAX_POSITIONS:
        return False

    return True


def get_state():
    """Расширенное состояние: PnL + сессия."""
    phase, session, minutes_in = get_session_phase()
    return {
        **STATE,
        "session": session,
        "session_phase": phase.value,
        "session_minutes_in": minutes_in,
    }
