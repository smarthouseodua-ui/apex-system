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
        self._recent_signals = {}

    async def filter(self, signals: list) -> list:
        try:
            approved = []
            for signal in signals:
                ok, reason = self._check(signal)
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

    def _check(self, signal: dict) -> tuple[bool, str]:
        symbol = signal.get("symbol")
        cooldown = self.config.get("signal_gate", {}).get("cooldown_minutes", 15)
        max_positions = self.config.get("signal_gate", {}).get("max_positions", 5)

        if symbol in self._recent_signals:
            elapsed = (datetime.now() - self._recent_signals[symbol]).seconds / 60
            if elapsed < cooldown:
                return False, f"cooldown ({elapsed:.1f}m < {cooldown}m)"

        if len(self._recent_signals) >= max_positions:
            return False, f"max_positions reached ({max_positions})"

        return True, ""
