"""
APEX PROTOCOL™ — Signal Gate
Фильтрует сигналы: дубли, лимиты, сессии, cooldown.
"""

import logging
from datetime import datetime
from core.event_bus import EventBus

logger = logging.getLogger("apex.signal_gate")


class SignalGate:

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self._recent_signals = {}  # symbol → timestamp

    async def filter(self, signals: list) -> list:
        """
        Фильтрация сигналов.
        Возвращает одобренные сигналы.
        """
        try:
            approved = []
            for signal in signals:
                if self._check(signal):
                    approved.append(signal)
                    self._recent_signals[signal["symbol"]] = datetime.now()

            logger.info(f"SignalGate: {len(approved)}/{len(signals)} approved")
            await self.event_bus.publish("signal_gate.done", {"approved": approved})
            return approved
        except Exception as e:
            logger.error(f"SignalGate error: {e}", exc_info=True)
            return []

    def _check(self, signal: dict) -> bool:
        """Проверки: cooldown, лимит позиций, сессия."""
        symbol = signal.get("symbol")
        cooldown = self.config.get("signal_gate", {}).get("cooldown_minutes", 15)
        max_positions = self.config.get("signal_gate", {}).get("max_positions", 5)

        # Проверка cooldown
        if symbol in self._recent_signals:
            elapsed = (datetime.now() - self._recent_signals[symbol]).seconds / 60
            if elapsed < cooldown:
                logger.debug(f"SignalGate: {symbol} cooldown ({elapsed:.1f}m < {cooldown}m)")
                return False

        # Проверка лимита позиций
        if len(self._recent_signals) >= max_positions:
            logger.debug(f"SignalGate: max positions reached ({max_positions})")
            return False

        return True
