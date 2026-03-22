"""
APEX PROTOCOL™ — Scanner
Сканирует рынок, находит кандидатов для торговли.
"""

import logging
from datetime import datetime
from core.event_bus import EventBus

logger = logging.getLogger("apex.scanner")


class Scanner:

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.exchange = None  # инициализируется через exchange_service

    async def scan(self) -> list:
        """
        Сканирование рынка.
        Возвращает список кандидатов: [{symbol, price, volume, volatility, session}]
        """
        try:
            candidates = await self._fetch_candidates()
            filtered = self._filter(candidates)
            logger.info(f"Scanner: {len(filtered)} candidates found")
            await self.event_bus.publish("scanner.done", {"candidates": filtered})
            return filtered
        except Exception as e:
            logger.error(f"Scanner error: {e}", exc_info=True)
            return []

    async def _fetch_candidates(self) -> list:
        """Получить список пар с биржи. Заглушка — будет заменена на ccxt."""
        return []

    def _filter(self, candidates: list) -> list:
        """Фильтрация по минимальному объёму и волатильности."""
        min_volume = self.config.get("scanner", {}).get("min_volume", 1_000_000)
        min_volatility = self.config.get("scanner", {}).get("min_volatility", 0.5)

        result = []
        for c in candidates:
            if c.get("volume", 0) >= min_volume and c.get("volatility", 0) >= min_volatility:
                c["scanned_at"] = datetime.now().isoformat()
                result.append(c)
        return result
