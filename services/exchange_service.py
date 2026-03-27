"""
APEX PROTOCOL™ — Exchange Service
Подключение к биржам через ccxt. Получение рыночных данных.
"""

import os
import ccxt.async_support as ccxt
import logging
from datetime import datetime

logger = logging.getLogger("apex.exchange_service")


class ExchangeService:

    def __init__(self, config: dict):
        self.config = config
        self.exchange = None

    async def connect(self):
        """Подключение к бирже. Ключи из ENV."""
        api_key = os.getenv("BYBIT_API_KEY")
        api_secret = os.getenv("BYBIT_API_SECRET")

        self.exchange = ccxt.bybit({
            "apiKey": api_key,
            "secret": api_secret,
            "options": {
                "defaultType": "future",
            },
            "enableRateLimit": True,
        })

        logger.info("ExchangeService: connected to Bybit Futures")

    async def get_tickers(self, symbols: list = None) -> dict:
        """Получить тикеры."""
        try:
            if symbols:
                tickers = {}
                for symbol in symbols:
                    tickers[symbol] = await self.exchange.fetch_ticker(symbol)
            else:
                tickers = await self.exchange.fetch_tickers()
            return tickers
        except Exception as e:
            logger.error(f"get_tickers error: {e}")
            return {}

    async def get_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 100) -> list:
        """Получить свечи OHLCV."""
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            return ohlcv
        except Exception as e:
            logger.error(f"get_ohlcv error {symbol}: {e}")
            return []

    async def get_futures_symbols(self) -> list:
        """Получить список всех USDT перпетуальных фьючерсных пар."""
        try:
            markets = await self.exchange.load_markets()
            symbols = [
                s for s, m in markets.items()
                if m.get("quote") == "USDT"
                and m.get("type") == "swap"
                and m.get("active")
                and m.get("linear")
            ]
            logger.info(f"ExchangeService: {len(symbols)} USDT perpetual pairs loaded")
            return symbols
        except Exception as e:
            logger.error(f"get_futures_symbols error: {e}")
            return []

    async def test_connection(self):
        """Безопасный тест API — только чтение, без ордеров."""
        try:
            balance = await self.exchange.fetch_balance()
            total_usdt = balance.get("USDT", {}).get("total", 0)
            free_usdt = balance.get("USDT", {}).get("free", 0)
            logger.info(f"[EXCHANGE] API OK | USDT total={total_usdt} free={free_usdt}")
            return {
                "status": "OK",
                "total_usdt": total_usdt,
                "free_usdt": free_usdt,
            }
        except Exception as e:
            logger.error(f"[EXCHANGE] API ERROR: {e}")
            return {
                "status": "ERROR",
                "error": str(e),
            }

    async def create_order(self, symbol: str, side: str, amount: float, order_type: str = "market", params: dict | None = None):
        """Отправить ордер на биржу."""
        params = params or {}
        return await self.exchange.create_order(symbol, order_type, side, amount, None, params)

    async def close(self):
        """Закрыть соединение."""
        if self.exchange:
            await self.exchange.close()
            logger.info("ExchangeService: connection closed")
