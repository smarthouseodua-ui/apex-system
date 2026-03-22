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
    "ASIA":   {"start": 0,  "end": 8},
    "LONDON": {"start": 8,  "end": 13},
    "NEW_YORK": {"start": 13, "end": 22},
    "OFF":    {"start": 22, "end": 24},
}


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

    def is_trading_time(self) -> bool:
        """Торговое время или нет."""
        return self.current_session() != "OFF"

    def get_session_info(self) -> dict:
        return {
            "time": self.now().strftime("%Y-%m-%d %H:%M:%S"),
            "session": self.current_session(),
            "hour": self.current_hour(),
            "is_trading": self.is_trading_time()
        }
