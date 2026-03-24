"""
APEX PROTOCOL™ — Time Manager
Управление временем и торговыми сессиями.
Timezone: Europe/Podgorica (CET/CEST)
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger("apex.time_manager")

TZ = ZoneInfo("Europe/Podgorica")

SESSIONS = {
    "ASIA":      {"start": 0,  "end": 4},
    "HONG_KONG": {"start": 4,  "end": 8},
    "LONDON":    {"start": 8,  "end": 13},
    "NEW_YORK":  {"start": 13, "end": 22},
    "OFF":       {"start": 22, "end": 24},
}

# Направление торговли по сессии
SESSION_DIRECTION = {
    "HONG_KONG": "buy",
    "NEW_YORK":  "sell",
    "LONDON":    "both",
    "ASIA":      "both",
    "OFF":       "none",
}

# Сессионные окна для time_features (в минутах от полуночи, Europe/Podgorica)
_SESSION_WINDOWS = {
    "session_asia":      (1 * 60,       9 * 60),       # 01:00–09:00
    "session_london":    (9 * 60,       18 * 60),      # 09:00–18:00
    "session_new_york":  (14 * 60 + 30, 23 * 60),      # 14:30–23:00
}

_SESSION_LABELS = {
    "session_asia":     "ASIA",
    "session_london":   "LONDON",
    "session_new_york": "NEW_YORK",
}

# Event-окна для time_features (в минутах от полуночи, Europe/Podgorica)
_EVENT_WINDOWS = {
    "event_tokyo_open":        (1 * 60,       2 * 60),       # 01:00–02:00
    "event_hk_open":           (2 * 60 + 30,  3 * 60 + 30),  # 02:30–03:30
    "event_london_open":       (9 * 60,       10 * 60),      # 09:00–10:00
    "event_ny_open":           (14 * 60 + 30, 15 * 60 + 30), # 14:30–15:30
    "event_overlap_london_ny": (14 * 60 + 30, 17 * 60),      # 14:30–17:00
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
        "session_london": 0,
        "session_new_york": 0,
        "event_tokyo_open": 0,
        "event_hk_open": 0,
        "event_london_open": 0,
        "event_ny_open": 0,
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
        """Определить текущую торговую сессию."""
        hour = self.current_hour()
        for session, times in SESSIONS.items():
            if times["start"] <= hour < times["end"]:
                return session
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
