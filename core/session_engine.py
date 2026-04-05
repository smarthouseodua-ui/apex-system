"""
APEX PROTOCOL™ — Session Engine
Единый источник логики сессий для бота, API и Deboshore.
Все времена в Europe/Podgorica (CET/CEST — DST автоматически).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ_PG = ZoneInfo("Europe/Podgorica")

# ─────────────────────────────────────────────
# СЕКЦИЯ 1 — КОНФИГ СЕССИЙ (Europe/Podgorica)
# ─────────────────────────────────────────────

SESSIONS = {
    "TOKYO":     {"open": "01:00", "no_watch": True},
    "HONG_KONG": {"open": "02:30"},
    "LONDON":    {"open": "08:00"},
    "NEW_YORK":  {"open": "14:30"},
}

SESSION_RU = {
    "TOKYO":     "Токио",
    "HONG_KONG": "Гонконг",
    "LONDON":    "Лондон",
    "NEW_YORK":  "Нью-Йорк",
}


# ─────────────────────────────────────────────
# ТЕСТ-БЛОК — удалить после тестирования
# ─────────────────────────────────────────────
SESSIONS_TEST = {
}
SESSION_RU_TEST = {
}
_ALL_SESSIONS    = {**SESSIONS,   **SESSIONS_TEST}
_ALL_SESSIONS_RU = {**SESSION_RU, **SESSION_RU_TEST}
# ─────────────────────────────────────────────
# КОНЕЦ ТЕСТ-БЛОКА
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# СЕКЦИЯ 2 — УТИЛИТЫ ВРЕМЕНИ
# ─────────────────────────────────────────────

def _parse_time(time_str):
    h, m = map(int, time_str.split(":"))
    return h, m


def _today_pg_datetime(h, m):
    now = datetime.now(TZ_PG)
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


def _minutes_between(a, b):
    return int((b - a).total_seconds() / 60)

# ─────────────────────────────────────────────
# СЕКЦИЯ 3 — ОПРЕДЕЛЕНИЕ ФАЗЫ
# ─────────────────────────────────────────────

def _detect_phase(now, open_dt):
    pre_start   = open_dt - timedelta(minutes=30)
    entry_end   = open_dt + timedelta(minutes=90)    # ВХОД: 0-90 мин
    watch_end   = entry_end + timedelta(minutes=30)   # СОПРОВОЖДЕНИЕ: 90-120 мин

    if now < pre_start:
        return "ОЖИДАНИЕ"
    elif now < open_dt:
        return "ПОДГОТОВКА"
    elif now < entry_end:
        return "ВХОД"
    elif now < watch_end:
        return "СОПРОВОЖДЕНИЕ"
    else:
        return "СЕССИЯ ЗАКРЫТА"

# ─────────────────────────────────────────────
# СЕКЦИЯ 4 — ПОДСКАЗКИ
# ─────────────────────────────────────────────

def _build_hint(phase, mins_to_open=None, mins_to_close=None):
    if phase == "ОЖИДАНИЕ":
        return "До начала подготовки ещё есть время"
    if phase == "ПОДГОТОВКА":
        return f"До открытия сессии осталось {mins_to_open} мин для проверки входа"
    if phase == "ВХОД":
        return "Активная фаза входа в рынок"
    if phase == "СОПРОВОЖДЕНИЕ":
        return f"До завершения сессии осталось {mins_to_close} мин. Контроль и закрытие"
    if phase == "СЕССИЯ ЗАКРЫТА":
        return "Сессия завершена"
    return ""

# ─────────────────────────────────────────────
# СЕКЦИЯ 5 — ОСНОВНАЯ ФУНКЦИЯ
# ─────────────────────────────────────────────

def get_session_state(session_name):
    """Возвращает полное состояние одной сессии."""
    now = datetime.now(TZ_PG)

    h, m = _parse_time(_ALL_SESSIONS[session_name]["open"])
    open_dt = _today_pg_datetime(h, m)

    phase = _detect_phase(now, open_dt)

    pre_start  = open_dt - timedelta(minutes=30)
    entry_end  = open_dt + timedelta(minutes=90)
    watch_end  = entry_end + timedelta(minutes=30)

    data = {
        "сессия": _ALL_SESSIONS_RU.get(session_name, session_name),
        "сессия_код": session_name,
        "текущее_время": now.strftime("%H:%M:%S"),
        "открытие": open_dt.strftime("%H:%M"),
        "фаза": phase,
        "сигнал_разрешён": phase == "ВХОД",
    }

    if phase == "ОЖИДАНИЕ":
        data["до_подготовки_мин"] = _minutes_between(now, pre_start)

    elif phase == "ПОДГОТОВКА":
        data["до_открытия_мин"] = _minutes_between(now, open_dt)

    elif phase == "ВХОД":
        data["прошло_мин"] = _minutes_between(open_dt, now)
        data["до_конца_входа_мин"] = _minutes_between(now, entry_end)

    elif phase == "СОПРОВОЖДЕНИЕ":
        data["прошло_мин"] = _minutes_between(open_dt, now)
        data["до_закрытия_мин"] = _minutes_between(now, watch_end)

    elif phase == "СЕССИЯ ЗАКРЫТА":
        next_open = open_dt + timedelta(days=1)
        data["до_следующей_сессии_мин"] = _minutes_between(now, next_open)

    data["подсказка"] = _build_hint(
        phase,
        data.get("до_открытия_мин"),
        data.get("до_закрытия_мин"),
    )

    return data

# ─────────────────────────────────────────────
# СЕКЦИЯ 6 — ВСЕ СЕССИИ
# ─────────────────────────────────────────────

def get_all_sessions():
    """Возвращает состояние всех 4 сессий."""
    return {name: get_session_state(name) for name in _ALL_SESSIONS}

# ─────────────────────────────────────────────
# СЕКЦИЯ 7 — ФИЛЬТРЫ ДЛЯ БОТА
# ─────────────────────────────────────────────

def is_entry_allowed(session_name=None):
    """Разрешён ли вход? Если session_name=None — проверяет все сессии."""
    if session_name:
        return get_session_state(session_name)["сигнал_разрешён"]
    return any(s["сигнал_разрешён"] for s in get_all_sessions().values())


def get_active_session():
    """Возвращает текущую активную сессию (не ОЖИДАНИЕ и не ЗАКРЫТА), или None."""
    for name in _ALL_SESSIONS:
        state = get_session_state(name)
        if state["фаза"] not in ("ОЖИДАНИЕ", "СЕССИЯ ЗАКРЫТА"):
            return state
    return None


def get_phase_for_orchestrator():
    """Маппинг фаз session_engine → логика оркестратора.

    Returns:
        (phase, session_name, raw_phase)
        phase: "ENTRY" / "WATCH" / "PRE_SESSION" / "OFF"
        session_name: "TOKYO" / "HONG_KONG" / "LONDON" / "NEW_YORK" / "OFF"
        raw_phase: русская фаза
    """
    # ── CLEAN MANUAL TEST WINDOW ───────────────────────────────────────────
    try:
        import json
        now = datetime.now(TZ_PG)
        tc_path = "/root/apex-system/storage/test_control.json"
        tc = json.loads(Path(tc_path).read_text(encoding="utf-8"))

        if tc.get("manual_hour_enabled") and tc.get("selected_hour") is not None:
            selected_hour = int(tc.get("selected_hour"))
            if now.hour == selected_hour:
                return "ENTRY", "LONDON", "MANUAL_TEST_HOUR"
    except Exception:
        pass

    # ── TEST CONTROL OVERRIDE DISABLED FOR SESSION SYNC ───────────────
    # Disabled to make orchestrator use only штатная логика сессий.
    # If needed later, restore from backup.

    # ── ШТАТНАЯ ЛОГИКА ───────────────────────────────────────────────────
    for name in _ALL_SESSIONS:
        state = get_session_state(name)
        phase = state["фаза"]
        if phase == "ПОДГОТОВКА":
            return "PRE_SESSION", name, phase
        elif phase == "ВХОД":
            return "ENTRY", name, phase
        elif phase == "СОПРОВОЖДЕНИЕ":
            if _ALL_SESSIONS.get(name, {}).get("no_watch"):
                return "OFF", name, phase
            return "WATCH", name, phase

    return "OFF", "OFF", "ОЖИДАНИЕ"

