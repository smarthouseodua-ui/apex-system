"""
APEX PROTOCOL™ — Scanner
Сканирует рынок, находит кандидатов для торговли.
"""

import logging
from datetime import datetime
from core.event_bus import EventBus
from services.exchange_service import ExchangeService

logger = logging.getLogger("apex.scanner")


class Scanner:

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.exchange_service = ExchangeService(config)
        self._connected = False

    async def _ensure_connected(self):
        if not self._connected:
            await self.exchange_service.connect()
            self._connected = True

    async def scan(self) -> list:
        try:
            await self._ensure_connected()
            candidates = await self._fetch_candidates()
            filtered = self._filter(candidates)
            logger.info(f"Scanner: {len(filtered)}/{len(candidates)} candidates passed filter")
            await self.event_bus.publish("scanner.done", {"candidates": filtered})
            return filtered
        except Exception as e:
            logger.error(f"Scanner error: {e}", exc_info=True)
            return []

    async def _fetch_candidates(self) -> list:
        tickers = await self.exchange_service.get_tickers()
        candidates = []

        for symbol, ticker in tickers.items():
            try:
                price = ticker.get("last", 0)
                volume = ticker.get("quoteVolume", 0)
                high = ticker.get("high", price)
                low = ticker.get("low", price)

                if price and price > 0:
                    volatility = round(((high - low) / price) * 100, 4)
                    candidates.append({
                        "symbol": symbol,
                        "price": price,
                        "volume": volume,
                        "volatility": volatility,
                        "high": high,
                        "low": low,
                        "scanned_at": datetime.now().isoformat()
                    })
            except Exception:
                continue

        return candidates

    def _filter(self, candidates: list) -> list:
        cfg = self.config.get("scanner", {})
        min_volume = cfg.get("min_volume", 50_000_000)
        min_volatility = cfg.get("min_volatility", 0.5)
        max_volatility = cfg.get("max_volatility", 15.0)
        max_candidates = cfg.get("max_candidates", 20)
        quote_currency = cfg.get("quote_currency", "USDT")
        blacklist = cfg.get("blacklist", [])

        result = [
            c for c in candidates
            if c.get("volume", 0) >= min_volume
            and min_volatility <= c.get("volatility", 0) <= max_volatility
            and c.get("symbol", "").endswith(f":{quote_currency}")
            and c.get("symbol") not in blacklist
        ]

        result.sort(key=lambda x: x.get("volume", 0), reverse=True)
        return result[:max_candidates]
