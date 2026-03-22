"""
APEX PROTOCOL™ — Finalizer
Закрывает позиции, считает PnL, пишет в таблицы.
"""

import logging
from datetime import datetime
from core.event_bus import EventBus

logger = logging.getLogger("apex.finalizer")


class Finalizer:

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus

    async def finalize(self, positions: list) -> None:
        """Финализация позиций со статусом 'closing'."""
        try:
            closing = [p for p in positions if p.get("status") == "closing"]
            for position in closing:
                result = self._calculate_pnl(position)
                await self._save(result)
                await self.event_bus.publish("trade.closed", {"result": result})
                logger.info(f"Trade closed: {result['symbol']} | {result['close_reason']} | PnL: {result['pnl_usdt']} USDT")
        except Exception as e:
            logger.error(f"Finalizer error: {e}", exc_info=True)

    def _calculate_pnl(self, position: dict) -> dict:
        """Расчёт PnL сделки."""
        entry = position.get("fill_price", position.get("entry", 0))
        close_reason = position.get("close_reason", "UNKNOWN")
        direction = position.get("direction", "long")
        size = position.get("size", 0)

        # Определяем цену закрытия по причине
        price_map = {
            "TP1": position.get("tp1"),
            "TP2": position.get("tp2"),
            "TP3": position.get("tp3"),
            "SL":  position.get("sl"),
        }
        close_price = price_map.get(close_reason, entry)

        if direction == "long":
            pnl_pct = ((close_price - entry) / entry) * 100
        else:
            pnl_pct = ((entry - close_price) / entry) * 100

        pnl_usdt = round(size * entry * (pnl_pct / 100), 4)

        return {
            **position,
            "close_price": close_price,
            "pnl_pct": round(pnl_pct, 4),
            "pnl_usdt": pnl_usdt,
            "status": "closed",
            "finalized_at": datetime.now().isoformat()
        }

    async def _save(self, result: dict) -> None:
        """Сохранение результата в таблицу. Заглушка — будет SQLite."""
        logger.debug(f"Finalizer: saving result for {result.get('symbol')}")
