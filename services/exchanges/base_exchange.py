"""
APEX PROTOCOL™ — Base Exchange Service
Базовый класс для всех бирж.
"""
import logging
logger = logging.getLogger("apex.exchange")

class BaseExchangeService:
    NAME = "base"
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.exchange = None
        self._connected = False
    
    async def connect(self):
        raise NotImplementedError
    
    async def get_tickers(self) -> list:
        """Возвращает список dict с полями: symbol, price, volume, volatility, high, low, exchange_name."""
        raise NotImplementedError
    
    async def get_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 100) -> list:
        raise NotImplementedError
    
    async def get_balance(self) -> float:
        raise NotImplementedError
    
    async def close(self):
        if self.exchange:
            try:
                await self.exchange.close()
            except Exception:
                pass
        self.exchange = None
        self._connected = False
        logger.info(f"[{self.NAME}] connection closed")
