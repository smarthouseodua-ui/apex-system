"""
APEX PROTOCOL™ — Session Engine
Единый источник логики сессий для бота, API и Deboshore.
Все времена в UTC.
"""

from datetime import datetime, timedelta, timezone

# ─────────────────────────────────────────────
# СЕКЦИЯ 1 — КОНФИГ СЕССИЙ (UTC)
# ─────────────────────────────────────────────

SESSIONS = {
    "TOKYO":     {"open": "00:00", "no_watch": True},
    "HONG_KONG": {"open": "01:30"},
    "LONDON":    {"open": "08:00"},
    "NEW_YORK":  {"open": "13:30"},
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
    "TEST_1": {"open": "10:30"},  # 11:30 CET
    "TEST_2": {"open": "16:00"},  # 17:00 CET
    "TEST_3": {"open": "05:00"},  # 06:00 CET
}
SESSION_RU_TEST = {
    "TEST_1": "Тест 1 (12:00)",
    "TEST_2": "Тест 2 (17:30)",
    "TEST_3": "Тест 3 (06:00)",
}
_ALL_SESSIONS     = {**SESSIONS,    **SESSIONS_TEST}
_ALL_SESSIONS_RU  = {**SESSION_RU, **SESSION_RU_TEST}
# ─────────────────────────────────────────────
# КОНЕЦ ТЕСТ-БЛОКА
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# ТЕСТ-БЛОК — удалить после тестирования
# ─────────────────────────────────────────────
SESSIONS_TEST = {
    "TEST_1": {"open": "10:30"},  # 11:30 CET
    "TEST_2": {"open": "16:00"},  # 17:00 CET
    "TEST_3": {"open": "05:00"},  # 06:00 CET
}
SESSION_RU_TEST = {
    "TEST_1": "Тест 1 (12:00)",
    "TEST_2": "Тест 2 (17:30)",
    "TEST_3": "Тест 3 (06:00)",
}
_ALL_SESSIONS    = {**SESSIONS,   **SESSIONS_TEST}
_ALL_SESSIONS_RU = {**SESSION_RU, **SESSION_RU_TEST}
# ─────────────────────────────────────────────
# КОНЕЦ ТЕСТ-БЛОКА
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# ТЕСТ-БЛОК — удалить после тестирования
# ─────────────────────────────────────────────
SESSIONS_TEST = {
    "TEST_1": {"open": "10:30"},  # 11:30 CET
    "TEST_2": {"open": "16:00"},  # 17:00 CET
    "TEST_3": {"open": "05:00"},  # 06:00 CET
}
SESSION_RU_TEST = {
    "TEST_1": "Тест 1 (12:00)",
    "TEST_2": "Тест 2 (17:30)",
    "TEST_3": "Тест 3 (06:00)",
}
_ALL_SESSIONS    = {**SESSIONS,   **SESSIONS_TEST}
_ALL_SESSIONS_RU = {**SESSION_RU, **SESSION_RU_TEST}
# ─────────────────────────────────────────────
# КОНЕЦ ТЕСТ-БЛОКА
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# СЕКЦИЯ 2 — УТИЛИТЫ ВРЕМЕНИ
# ─────────────────────────────────────────────

def _parse_time_utc(time_str):
    h, m = map(int, time_str.split(":"))
    return h, m


def _today_utc_datetime(h, m):
    now = datetime.now(timezone.utc)
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


def _minutes_between(a, b):
    return int((b - a).total_seconds() / 60)

# ─────────────────────────────────────────────
# СЕКЦИЯ 3 — ОПРЕДЕЛЕНИЕ ФАЗЫ
# ─────────────────────────────────────────────

def _detect_phase(now, open_dt):
    pre_start  = open_dt - timedelta(minutes=30)
    entry_end  = open_dt + timedelta(minutes=90)   # ENTRY: первые 90 мин
    active_end = open_dt + timedelta(minutes=120)  # WATCH: 90-120 мин
    late_end   = open_dt + timedelta(minutes=120)  # совпадает с active_end

    if now < pre_start:
        return "ОЖИДАНИЕ"
    elif now < open_dt:
        return "ПОДГОТОВКА"
    elif now < entry_end:
        return "ВХОД"
    elif now < active_end:
        return "СОПРОВОЖДЕНИЕ"
    elif now < late_end:
        return "ПОЗДНЯЯ ФАЗА"
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
        return "Фаза сопровождения. Новые входы нежелательны"
    if phase == "ПОЗДНЯЯ ФАЗА":
        return f"До завершения сессии осталось {mins_to_close} мин. Контроль и закрытие"
    if phase == "СЕССИЯ ЗАКРЫТА":
        return "Сессия завершена"
    return ""

# ─────────────────────────────────────────────
# СЕКЦИЯ 5 — ОСНОВНАЯ ФУНКЦИЯ
# ─────────────────────────────────────────────

def get_session_state(session_name):
    """Возвращает полное состояние одной сессии."""
    now = datetime.now(timezone.utc)

    h, m = _parse_time_utc(_ALL_SESSIONS[session_name]["open"])
    open_dt = _today_utc_datetime(h, m)

    phase = _detect_phase(now, open_dt)

    pre_start  = open_dt - timedelta(minutes=30)
    entry_end  = open_dt + timedelta(minutes=90)   # ENTRY: первые 90 мин
    active_end = open_dt + timedelta(minutes=120)  # WATCH: 90-120 мин
    late_end   = open_dt + timedelta(minutes=120)  # совпадает с active_end

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
        data["до_60_мин"] = _minutes_between(now, active_end)

    elif phase == "ПОЗДНЯЯ ФАЗА":
        data["прошло_мин"] = _minutes_between(open_dt, now)
        data["до_закрытия_мин"] = _minutes_between(now, late_end)

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
    for name in _ALL_SESSIONS:
        state = get_session_state(name)
        phase = state["фаза"]
        if phase == "ПОДГОТОВКА":
            return "PRE_SESSION", name, phase
        elif phase == "ВХОД":
            return "ENTRY", name, phase
        elif phase in ("СОПРОВОЖДЕНИЕ", "ПОЗДНЯЯ ФАЗА"):
            # no_watch: сразу OFF (закрыть все позиции)
            if _ALL_SESSIONS.get(name, {}).get("no_watch"):
                return "OFF", name, phase
            return "WATCH", name, phase
    return "OFF", "OFF", "ОЖИДАНИЕ"
