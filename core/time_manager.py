"""
APEX PROTOCOL™ — Time Manager
Управление временем и торговыми сессиями.
Timezone: Europe/Podgorica (CET/CEST)
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from enum import Enum

logger = logging.getLogger("apex.time_manager")

TZ = ZoneInfo("Europe/Podgorica")

# ── Все времена в UTC+2 (Europe/Podgorica) ───────────────────────────────────

# Базовые окна сессий (в минутах от полуночи)
_SESSION_WINDOWS = {
    "session_asia":      (1 * 60,        3 * 60),        # 01:00–03:00  Токио
    "session_hong_kong": (2 * 60 + 30,   4 * 60 + 30),   # 02:30–04:30  Гонконг
    "session_london":    (9 * 60,        11 * 60),        # 09:00–11:00  Лондон
    "session_new_york":  (14 * 60 + 30,  16 * 60 + 30),  # 14:30–16:30  Нью-Йорк
    # ── ТЕСТ-БЛОК ──────────────────────────────────────────────────────
    "session_test1":     (11 * 60 + 30,  13 * 60 + 30),  # 11:30–13:30  Тест 1
    "session_test2":     (17 * 60,       19 * 60),        # 17:00–19:00  Тест 2
    "session_test3":     (6  * 60,       8  * 60),        # 06:00–08:00  Тест 3
    # ── КОНЕЦ ТЕСТ-БЛОКА ────────────────────────────────────────────────
}

_SESSION_LABELS = {
    "session_asia":      "ASIA",
    "session_hong_kong": "HONG_KONG",
    "session_london":    "LONDON",
    "session_new_york":  "NEW_YORK",
    "session_test1":     "TEST_1",
    "session_test2":     "TEST_2",
    "session_test3":     "TEST_3",
}

# Маппинг label → ключ _SESSION_WINDOWS
_LABEL_TO_KEY = {v: k for k, v in _SESSION_LABELS.items()}


class SessionPhase(Enum):
    PRE_SESSION = "PRE_SESSION"
    EXECUTION   = "EXECUTION"
    OBSERVATION = "OBSERVATION"
    HARD_CLOSE  = "HARD_CLOSE"
    OFF         = "OFF"


def get_session_phase(session_name: str = None) -> tuple["SessionPhase", str, int]:
    """
    Определяет фазу сессии по текущему времени (Europe/Podgorica).

    Если session_name=None — берёт последнюю начавшуюся активную сессию.

    Returns:
        (phase, session_name, minutes_elapsed)
        minutes_elapsed — минут от session_open (отрицательные = до открытия)
    """
    now_pg = datetime.now(TZ)
    total_minutes = now_pg.hour * 60 + now_pg.minute

    # Если session_name задан — считаем для конкретной сессии
    if session_name:
        key = _LABEL_TO_KEY.get(session_name)
        if not key:
            return SessionPhase.OFF, session_name, 0
        start = _SESSION_WINDOWS[key][0]
        minutes_elapsed = total_minutes - start

        if minutes_elapsed < -30:
            return SessionPhase.OFF, session_name, minutes_elapsed
        elif minutes_elapsed < 0:
            return SessionPhase.PRE_SESSION, session_name, minutes_elapsed
        elif minutes_elapsed < 90:
            return SessionPhase.EXECUTION, session_name, minutes_elapsed
        elif minutes_elapsed < 120:
            return SessionPhase.OBSERVATION, session_name, minutes_elapsed
        else:
            return SessionPhase.HARD_CLOSE, session_name, minutes_elapsed

    # Авто-определение: найти все активные сессии
    best = None
    for key, (start, end) in _SESSION_WINDOWS.items():
        label = _SESSION_LABELS[key]
        minutes_elapsed = total_minutes - start
        # Рассматриваем сессии от −30 мин до конца окна
        if -30 <= minutes_elapsed and total_minutes < end:
            if best is None or start > best[1]:
                best = (label, start, minutes_elapsed)

    if not best:
        return SessionPhase.OFF, "OFF", 0

    label, start, minutes_elapsed = best
    if minutes_elapsed < 0:
        return SessionPhase.PRE_SESSION, label, minutes_elapsed
    elif minutes_elapsed < 90:
        return SessionPhase.EXECUTION, label, minutes_elapsed
    elif minutes_elapsed < 120:
        return SessionPhase.OBSERVATION, label, minutes_elapsed
    else:
        return SessionPhase.HARD_CLOSE, label, minutes_elapsed


# SESSIONS — для TimeManager.current_session() и handlers.py (часы, Podgorica)
SESSIONS = {
    "ASIA":      {"start": 1,  "end": 10},   # 01:00–10:00
    "ASIA+HK":   {"start": 3,  "end": 10},   # 03:00–10:00  overlap
    "HONG_KONG": {"start": 3,  "end": 12},   # 03:00–12:00
    "LONDON":    {"start": 10, "end": 19},    # 10:00–19:00
    "LONDON+NY": {"start": 15, "end": 19},    # 15:30–19:00  overlap
    "NEW_YORK":  {"start": 15, "end": 22},    # 15:30–22:00
    "OFF":       {"start": 22, "end": 1},
}

# Направление торговли по сессии
SESSION_DIRECTION = {
    "ASIA":      "both",
    "ASIA+HK":   "both",
    "HONG_KONG": "buy",
    "LONDON":    "both",
    "LONDON+NY": "both",
    "NEW_YORK":  "sell",
    "OFF":       "none",
}

# Event-окна для time_features (в минутах от полуночи, Europe/Podgorica)
_EVENT_WINDOWS = {
    "event_tokyo_open":        (1 * 60,        2 * 60),       # 01:00–02:00
    "event_hk_open":           (3 * 60,        4 * 60),       # 03:00–04:00
    "event_london_open":       (10 * 60,       11 * 60),      # 10:00–11:00
    "event_ny_open":           (15 * 60 + 30,  16 * 60 + 30), # 15:30–16:30
    "event_overlap_asia_hk":   (3 * 60,        10 * 60),      # 03:00–10:00
    "event_overlap_london_ny": (15 * 60 + 30,  19 * 60),      # 15:30–19:00
}


def time_features_for_dt(value) -> dict:
    """
    По времени открытия сделки возвращает session-флаги и event-флаги.

    value: строка "%Y-%m-%dT%H:%M:%S" (уже в Europe/Podgorica) или datetime.

    Возвращает dict:
        session_asia, session_london, session_new_york  — 0/1
        event_tokyo_open, event_hk_open, event_london_open,
        event_ny_open, event_overlap_london_ny           — 0/1
        session_name                                     — "ASIA", "LONDON,NEW_YORK", "OFF" и т.д.
    """
    _empty = {
        "session_asia": 0,
        "session_hong_kong": 0,
        "session_london": 0,
        "session_new_york": 0,
        "event_tokyo_open": 0,
        "event_hk_open": 0,
        "event_london_open": 0,
        "event_ny_open": 0,
        "event_overlap_asia_hk": 0,
        "event_overlap_london_ny": 0,
        "session_name": "OFF",
    }
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", ""))
        elif isinstance(value, datetime):
            dt = value
        else:
            return _empty

        # opened_at уже в Europe/Podgorica — берём час и минуту напрямую
        total_minutes = dt.hour * 60 + dt.minute

        result = {}

        # --- session flags ---
        active_sessions = []
        for key, (start, end) in _SESSION_WINDOWS.items():
            flag = 1 if start <= total_minutes < end else 0
            result[key] = flag
            if flag:
                active_sessions.append(_SESSION_LABELS[key])

        # --- event flags ---
        for key, (start, end) in _EVENT_WINDOWS.items():
            result[key] = 1 if start <= total_minutes < end else 0

        result["session_name"] = ",".join(active_sessions) if active_sessions else "OFF"

        return result

    except Exception:
        return _empty


class TimeManager:

    def __init__(self, config: dict):
        self.config = config

    def now(self) -> datetime:
        """Текущее время в Europe/Podgorica."""
        return datetime.now(tz=TZ)

    def now_utc(self) -> datetime:
        """Текущее время UTC."""
        return datetime.utcnow()

    def current_hour(self) -> int:
        return self.now().hour

    def current_session(self) -> str:
        """Определить текущую торговую сессию с учётом overlap."""
        now = self.now()
        total_minutes = now.hour * 60 + now.minute

        asia = _SESSION_WINDOWS["session_asia"][0] <= total_minutes < _SESSION_WINDOWS["session_asia"][1]
        hk   = _SESSION_WINDOWS["session_hong_kong"][0] <= total_minutes < _SESSION_WINDOWS["session_hong_kong"][1]
        lon  = _SESSION_WINDOWS["session_london"][0] <= total_minutes < _SESSION_WINDOWS["session_london"][1]
        ny   = _SESSION_WINDOWS["session_new_york"][0] <= total_minutes < _SESSION_WINDOWS["session_new_york"][1]

        if asia and hk:
            return "ASIA+HK"
        elif asia:
            return "ASIA"
        elif lon and ny:
            return "LONDON+NY"
        elif lon:
            return "LONDON"
        elif ny:
            return "NEW_YORK"
        elif hk:
            return "HONG_KONG"
        else:
            return "OFF"

    def session_direction(self, session: str = None) -> str:
        """Разрешённое направление для сессии."""
        s = session or self.current_session()
        return SESSION_DIRECTION.get(s, "both")

    def is_trading_time(self) -> bool:
        """Торговое время или нет."""
        return self.current_session() != "OFF"

    def is_blocked_hour(self) -> bool:
        """Проверка заблокированных часов."""
        blocked = self.config.get("risk", {}).get("blocked_hours", [13])
        return self.current_hour() in blocked

    def get_session_info(self) -> dict:
        session = self.current_session()
        return {
            "time": self.now().strftime("%Y-%m-%d %H:%M:%S"),
            "session": session,
            "hour": self.current_hour(),
            "direction": self.session_direction(session),
            "is_trading": self.is_trading_time(),
            "is_blocked": self.is_blocked_hour()
        }
