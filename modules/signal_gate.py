"""
APEX PROTOCOL™ — Signal Gate
Фильтрует сигналы. Пишет в SKL01_T03_signal_gate_log.
"""

import logging
from datetime import datetime
from core.event_bus import EventBus
from storage.db.repository import Repository

logger = logging.getLogger("apex.signal_gate")


class SignalGate:

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.repo = Repository()
        self._recent_signals: dict[str, datetime] = {}

    def reset(self):
        """Сбросить состояние в начале каждого цикла."""
        self._recent_signals.clear()
        logger.info("SignalGate: reset — _recent_signals cleared")

    async def filter(self, signals: list, open_symbols: set = None) -> list:
        try:
            approved = []
            for signal in signals:
                ok, reason = self._check(signal, open_symbols or set())
                self.repo.log_signal_gate(signal["symbol"], ok, reason)
                if ok:
                    approved.append(signal)
                    self._recent_signals[signal["symbol"]] = datetime.now()

            logger.info(f"SignalGate: {len(approved)}/{len(signals)} approved")
            await self.event_bus.publish("signal_gate.done", {"approved": approved})
            return approved
        except Exception as e:
            logger.error(f"SignalGate error: {e}", exc_info=True)
            return []

    def _check(self, signal: dict, open_symbols: set) -> tuple[bool, str]:
        symbol = signal.get("symbol")
        max_pos = self.config.get("max_positions", 100)
        cooldown_minutes = self.config.get("cooldown_minutes", 15)

        # Блокировка: символ уже в открытых позициях
        if symbol in open_symbols:
            return False, "already_open"

        db_open = self.repo.get_open_symbols()
        if symbol in db_open:
            return False, "already_open_db"

        if symbol in self._recent_signals:
            elapsed = (datetime.now() - self._recent_signals[symbol]).total_seconds() / 60
            if elapsed < cooldown_minutes:
                return False, f"cooldown ({elapsed:.1f}m < {cooldown_minutes}m)"

        if len(self._recent_signals) >= max_pos:
            return False, f"max_positions reached ({max_pos})"

        return True, ""
