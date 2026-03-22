"""
APEX PROTOCOL™ — State Manager
Управление состоянием системы.
"""

import logging
from datetime import datetime

logger = logging.getLogger("apex.state_manager")

VALID_STATES = ["idle", "running", "stopped", "error", "paused"]


class StateManager:

    def __init__(self):
        self._state = "idle"
        self._history = []
        logger.info("StateManager initialized")

    def set_state(self, state: str):
        """Установить новое состояние."""
        if state not in VALID_STATES:
            raise ValueError(f"Invalid state: {state}. Valid: {VALID_STATES}")
        prev = self._state
        self._state = state
        self._history.append({
            "from": prev,
            "to": state,
            "time": datetime.now().isoformat()
        })
        logger.info(f"State: {prev} → {state}")

    def get_state(self) -> str:
        return self._state

    def is_running(self) -> bool:
        return self._state == "running"

    def get_history(self) -> list:
        return self._history.copy()
