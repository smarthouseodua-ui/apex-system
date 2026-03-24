"""
APEX PROTOCOL™ — Position Manager
Мониторинг позиций. Пишет в SKL01_T06_position_manager_log.
"""

import logging
from datetime import datetime
from pytz import timezone as tz
from core.event_bus import EventBus

PODGORICA = tz("Europe/Podgorica")
from storage.db.repository import Repository
from services.exchange_service import ExchangeService

logger = logging.getLogger("apex.position_manager")


class PositionManager:

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.repo = Repository()
        self.exchange = ExchangeService(config)
        self._positions = {}

    async def _ensure_connected(self):
        try:
            await self.exchange.connect()
        except Exception:
            pass

    async def monitor(self, positions: list) -> None:
        try:
            await self._ensure_connected()
            symbols = [p.get("symbol") for p in positions if p.get("symbol")]
            prices = {}
            if symbols:
                try:
                    if not hasattr(self.exchange, '_connected') or not self.exchange._connected:
                        await self.exchange.connect()
                    tickers = await self.exchange.get_tickers(symbols)
                    prices = {sym: tick.get("last") for sym, tick in tickers.items() if tick.get("last")}
                except Exception as e:
                    logger.warning(f"PositionManager: price fetch failed: {e}")

            for position in positions:
                symbol = position.get("symbol")
                if symbol in prices:
                    position["current_price"] = prices[symbol]
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

        if not sl or not tp1:
            return

        if direction == "long":
            if current_price <= sl:
                await self._close_position(position, "SL")
                return
            elif current_price >= tp3:
                await self._close_position(position, "TP3")
                return
            elif current_price >= tp2:
                await self._close_position(position, "TP2")
                return
            elif current_price >= tp1:
                if not position.get("breakeven_activated"):
                    self._activate_breakeven(position)
                return
        else:
            if current_price >= sl:
                await self._close_position(position, "SL")
                return
            elif current_price <= tp3:
                await self._close_position(position, "TP3")
                return
            elif current_price <= tp2:
                await self._close_position(position, "TP2")
                return
            elif current_price <= tp1:
                if not position.get("breakeven_activated"):
                    self._activate_breakeven(position)
                return

        # --- Таймаут (проверяется последним) ---
        max_minutes = self.config.get("risk", {}).get("max_trade_minutes", 40)
        opened_at_str = position.get("opened_at")
        if opened_at_str:
            try:
                opened_at = datetime.fromisoformat(opened_at_str)
                elapsed = (datetime.now() - opened_at).total_seconds() / 60
                if elapsed >= max_minutes:
                    await self._close_position(position, "TIMEOUT")
            except Exception:
                pass

    def _activate_breakeven(self, position: dict) -> None:
        symbol = position.get("symbol")
        entry = position.get("fill_price") or position.get("entry")
        position["sl"] = entry
        position["breakeven_activated"] = True
        trade_id = position.get("trade_id")
        if trade_id:
            self.repo.update_position_sl(trade_id, entry)
        logger.info(f"Position {symbol} → breakeven activated: SL moved to entry {entry}")

    async def _close_position(self, position: dict, reason: str) -> None:
        symbol = position.get("symbol")
        position["close_reason"] = reason
        position["closed_at"] = datetime.now(PODGORICA).strftime("%Y-%m-%dT%H:%M:%S")
        position["status"] = "closing"
        logger.info(f"Position {symbol} → closing by {reason}")
        await self.event_bus.publish("position.closing", {"position": position})

    def get_open_positions(self) -> list:
        return [p for p in self._positions.values() if p.get("status") == "open"]
