"""
APEX PROTOCOL™ — Strategy Engine
Каркас. Временная тестовая стратегия: Session ORB 5m.
Пишет в SKL01_T02_strategy_log.
"""

import logging
from datetime import datetime
from core.event_bus import EventBus
from services.exchange_service import ExchangeService
from storage.db.repository import Repository

logger = logging.getLogger("apex.strategy_engine")

SESSION_OPEN_HOURS = [8, 12, 17]


class StrategyEngine:

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.exchange_service = ExchangeService(config)
        self.repo = Repository()
        self._connected = False

    async def _ensure_connected(self):
        if not self._connected:
            await self.exchange_service.connect()
            self._connected = True

    def _current_session_hour(self) -> int | None:
        now = datetime.now()
        if now.hour in SESSION_OPEN_HOURS and now.minute < 5:
            return now.hour
        return None

    async def analyze(self, candidates: list) -> list:
        try:
            await self._ensure_connected()
            signals = []

            session_hour = self._current_session_hour()
            if session_hour is None:
                logger.info("StrategyEngine: not a session open window — skipping")
                return []

            logger.info(f"StrategyEngine: session open {session_hour}:00 — scanning {len(candidates)} candidates")

            for candidate in candidates:
                signal = await self._session_orb_signal(candidate, session_hour)
                if signal:
                    self.repo.log_strategy(signal)
                    signals.append(signal)

            logger.info(f"StrategyEngine: {len(signals)} signals generated")
            await self.event_bus.publish("strategy.done", {"signals": signals})
            return signals
        except Exception as e:
            logger.error(f"StrategyEngine error: {e}", exc_info=True)
            return []

    async def _session_orb_signal(self, candidate: dict, session_hour: int) -> dict | None:
        symbol = candidate["symbol"]
        try:
            candles = await self.exchange_service.get_ohlcv(symbol, "5m", limit=3)
            if len(candles) < 2:
                return None

            session_candle = candles[0]
            orb_high = session_candle[2]
            orb_low  = session_candle[3]

            if orb_high <= orb_low:
                return None

            current_price = candidate["price"]

            direction = None
            if current_price > orb_high:
                direction = "long"
                entry = round(current_price, 6)
                sl = round(orb_low, 6)
            elif current_price < orb_low:
                direction = "short"
                entry = round(current_price, 6)
                sl = round(orb_high, 6)

            if not direction:
                return None

            return {
                "symbol": symbol,
                "direction": direction,
                "entry": entry,
                "sl": sl,
                "strategy": "SESSION_ORB_5M",
                "timeframe": "5m",
                "session_hour": session_hour,
                "orb_high": orb_high,
                "orb_low": orb_low,
                "confidence": 1.0,
                "generated_at": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Session ORB error {symbol}: {e}")
            return None
