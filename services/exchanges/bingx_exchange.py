"""
APEX PROTOCOL™ — BingX Exchange Service
Независимый модуль сканирования BingX Futures.
"""
import os
import asyncio
import logging
import ccxt.async_support as ccxt
from services.exchanges.base_exchange import BaseExchangeService

logger = logging.getLogger("apex.exchange.bingx")


class BingXExchangeService(BaseExchangeService):
    NAME = "bingx"

    async def connect(self):
        if self._connected and self.exchange:
            return
        if self.exchange:
            try:
                await self.exchange.close()
            except Exception:
                pass
        self.exchange = ccxt.bingx({
            "apiKey": os.getenv("BINGX_API_KEY"),
            "secret": os.getenv("BINGX_API_SECRET"),
            "options": {"defaultType": "swap"},
            "enableRateLimit": True,
        })
        self._connected = True
        logger.info("[BingX] connected to BingX Futures")

    async def get_tickers(self) -> list:
        """Получить все USDT фьючерсные пары с BingX."""
        if not self.exchange:
            return []
        try:
            tickers = await self.exchange.fetch_tickers()
            pairs = []
            for symbol, ticker in tickers.items():
                if not symbol.endswith(":USDT"):
                    continue
                price = ticker.get("last", 0)
                volume = ticker.get("quoteVolume", 0)
                high = ticker.get("high", price) or price
                low = ticker.get("low", price) or price
                if price and price > 0:
                    volatility = round(((high - low) / price) * 100, 4)
                    pairs.append({
                        "symbol": symbol,
                        "price": price,
                        "volume": volume,
                        "volatility": volatility,
                        "high": high,
                        "low": low,
                        "exchange_name": "bingx",
                    })
            logger.info(f"[BingX] {len(pairs)} pairs loaded")
            return pairs
        except Exception as e:
            logger.error(f"[BingX] get_tickers error: {e}")
            return []

    async def get_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 100) -> list:
        await asyncio.sleep(0.2)
        try:
            return await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        except Exception as e:
            logger.error(f"[BingX] get_ohlcv error {symbol}: {e}")
            return []

    async def get_balance(self) -> float:
        try:
            balance = await self.exchange.fetch_balance()
            return float(balance.get("USDT", {}).get("free", 0))
        except Exception as e:
            logger.error(f"[BingX] get_balance error: {e}")
            return 0.0
