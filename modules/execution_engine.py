"""
APEX PROTOCOL™ — Execution Engine
Исполняет ордера. Режим: simulation / live.
"""

import logging
from datetime import datetime
from core.event_bus import EventBus

logger = logging.getLogger("apex.execution_engine")


class ExecutionEngine:

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.mode = config.get("mode", "simulation")

    async def execute(self, orders: list) -> list:
        """
        Исполнение ордеров.
        Возвращает список открытых позиций.
        """
        try:
            positions = []
            for order in orders:
                position = await self._execute_order(order)
                if position:
                    positions.append(position)

            logger.info(f"ExecutionEngine [{self.mode}]: {len(positions)} positions opened")
            await self.event_bus.publish("execution.done", {"positions": positions})
            return positions
        except Exception as e:
            logger.error(f"ExecutionEngine error: {e}", exc_info=True)
            return []

    async def _execute_order(self, order: dict) -> dict | None:
        """Исполнение одного ордера."""
        if self.mode == "simulation":
            return self._simulate(order)
        elif self.mode == "live":
            return await self._execute_live(order)
        return None

    def _simulate(self, order: dict) -> dict:
        """Симуляция исполнения ордера."""
        return {
            **order,
            "status": "open",
            "fill_price": order["entry"],
            "slippage": 0.0,
            "commission": 0.0,
            "opened_at": datetime.now().isoformat(),
            "mode": "simulation"
        }

    async def _execute_live(self, order: dict) -> dict | None:
        """Реальное исполнение через ccxt. Заглушка."""
        logger.warning("Live execution not implemented yet")
        return None
