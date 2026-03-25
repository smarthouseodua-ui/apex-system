"""
APEX PROTOCOL™ — Finalizer
Закрывает позиции, считает PnL, пишет в таблицы.
"""

import logging
from datetime import datetime
from pytz import timezone as tz
from core.event_bus import EventBus

PODGORICA = tz("Europe/Podgorica")

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
            "TP1":     position.get("tp1"),
            "TP2":     position.get("tp2"),
            "TP3":     position.get("tp3"),
            "SL":      position.get("sl"),
            "TIMEOUT": position.get("current_price"),
        }
        close_price = price_map.get(close_reason) or position.get("current_price") or entry

        if direction == "long":
            pnl_pct = ((close_price - entry) / entry) * 100
        else:
            pnl_pct = ((entry - close_price) / entry) * 100

        pnl_usdt = round(size * entry * (pnl_pct / 100), 4)

        finalized_at = datetime.now(PODGORICA).strftime("%Y-%m-%dT%H:%M:%S")

        duration_minutes = None
        opened_at_str = position.get("opened_at")
        closed_at_str = position.get("closed_at") or finalized_at
        if opened_at_str and closed_at_str:
            try:
                opened_dt = datetime.fromisoformat(opened_at_str.replace("Z", ""))
                closed_dt = datetime.fromisoformat(closed_at_str.replace("Z", ""))
                duration_minutes = int((closed_dt - opened_dt).total_seconds() / 60)
            except Exception:
                pass

        try:
            from services.test_control import read as tc_read
            strategy_name = tc_read().get("active_filter")
        except Exception:
            strategy_name = None

        return {
            **position,
            "close_price": close_price,
            "pnl_pct": round(pnl_pct, 4),
            "pnl_usdt": pnl_usdt,
            "status": "closed",
            "finalized_at": finalized_at,
            "trade_id": position.get("trade_id"),
            "session_name": position.get("session_name"),
            "duration_minutes": duration_minutes,
            "minutes_to_close": duration_minutes,
            "strategy_name": strategy_name,
        }

    async def _save(self, result: dict) -> None:
        from storage.db.repository import Repository
        repo = Repository()
        repo.log_final_trade(result)
        repo.close_execution(result.get("trade_id"))
        logger.info(f"Finalizer: saved {result.get('symbol')} → SKL01_T07, T05 status=closed [{result.get('trade_id')}]")
        try:
            from services.telegram_notifier import get_notifier
            notifier = get_notifier()
            if notifier:
                await notifier.notify_close(result)
        except Exception as e:
            logger.warning(f"notify_close error: {e}")
