"""
APEX PROTOCOL™ — Risk Manager
Рассчитывает параметры сделки. Пишет в SKL01_T04_risk_manager_log.
"""

import logging
from core.event_bus import EventBus
from storage.db.repository import Repository

logger = logging.getLogger("apex.risk_manager")


class RiskManager:

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.repo = Repository()

    async def calculate(self, signals: list) -> list:
        try:
            orders = []
            for signal in signals:
                order = self._calculate_order(signal)
                if order:
                    self.repo.log_risk_manager(order)
                    orders.append(order)

            logger.info(f"RiskManager: {len(orders)} orders calculated")
            await self.event_bus.publish("risk_manager.done", {"orders": orders})
            return orders
        except Exception as e:
            logger.error(f"RiskManager error: {e}", exc_info=True)
            return []

    def _calculate_order(self, signal: dict) -> dict | None:
        cfg = self.config.get("risk", {})
        balance = cfg.get("balance_usdt", 1000)
        risk_pct = cfg.get("risk_per_trade_pct", 1.0)
        leverage = cfg.get("leverage", 10)
        rr = cfg.get("rr_ratio", 2.0)

        entry = signal.get("entry")
        sl = signal.get("sl")
        if not entry or not sl:
            return None

        sl_distance = abs(entry - sl)
        if sl_distance == 0:
            return None

        risk_usdt = balance * (risk_pct / 100)
        size = round((risk_usdt * leverage) / entry, 4)
        direction = signal.get("direction", "long")

        tp1 = entry + sl_distance * 1.0 if direction == "long" else entry - sl_distance * 1.0
        tp2 = entry + sl_distance * 2.0 if direction == "long" else entry - sl_distance * 2.0
        tp3 = entry + sl_distance * 3.0 if direction == "long" else entry - sl_distance * 3.0

        return {
            **signal,
            "entry": entry,
            "sl": sl,
            "tp1": round(tp1, 6),
            "tp2": round(tp2, 6),
            "tp3": round(tp3, 6),
            "size": size,
            "leverage": leverage,
            "rr": rr,
            "risk_usdt": risk_usdt
        }
