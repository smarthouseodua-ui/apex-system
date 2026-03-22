"""
APEX PROTOCOL™ — Position Manager
Мониторинг позиций. Пишет в SKL01_T06_position_manager_log.
"""

import logging
from datetime import datetime
from core.event_bus import EventBus
from storage.db.repository import Repository

logger = logging.getLogger("apex.position_manager")


class PositionManager:

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.repo = Repository()
        self._positions = {}

    async def monitor(self, positions: list) -> None:
        try:
            for position in positions:
                symbol = position.get("symbol")
                self._positions[symbol] = position
                await self._check_position(position)
                self.repo.log_position(position)

            logger.info(f"PositionManager: monitoring {len(self._positions)} positions")
            await self.event_bus.publish("position_manager.update", {
                "positions": list(self._positions.values())
            })
        except Exception as e:
            logger.error(f"PositionManager error: {e}", exc_info=True)

    async def _check_position(self, position: dict) -> None:
        symbol = position.get("symbol")
        current_price = position.get("current_price", position.get("entry"))
        direction = position.get("direction", "long")

        sl  = position.get("sl")
        tp1 = position.get("tp1")
        tp2 = position.get("tp2")
        tp3 = position.get("tp3")

        if direction == "long":
            if current_price <= sl:
                await self._close_position(position, "SL")
            elif current_price >= tp3:
                await self._close_position(position, "TP3")
            elif current_price >= tp2:
                await self._close_position(position, "TP2")
            elif current_price >= tp1:
                await self._close_position(position, "TP1")
        else:
            if current_price >= sl:
                await self._close_position(position, "SL")
            elif current_price <= tp3:
                await self._close_position(position, "TP3")
            elif current_price <= tp2:
                await self._close_position(position, "TP2")
            elif current_price <= tp1:
                await self._close_position(position, "TP1")

    async def _close_position(self, position: dict, reason: str) -> None:
        symbol = position.get("symbol")
        position["close_reason"] = reason
        position["closed_at"] = datetime.now().isoformat()
        position["status"] = "closing"
        logger.info(f"Position {symbol} → closing by {reason}")
        await self.event_bus.publish("position.closing", {"position": position})

    def get_open_positions(self) -> list:
        return [p for p in self._positions.values() if p.get("status") == "open"]
