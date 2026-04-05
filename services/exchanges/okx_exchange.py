"""
APEX PROTOCOL™ — OKX Exchange Service
Заглушка. Будет подключена позже.
"""
import logging
from services.exchanges.base_exchange import BaseExchangeService

logger = logging.getLogger("apex.exchange.okx")


class OKXExchangeService(BaseExchangeService):
    NAME = "okx"

    async def connect(self):
        logger.warning("[OKX] not connected — stub only")

    async def get_tickers(self) -> list:
        logger.warning("[OKX] get_tickers — stub, returning empty")
        return []

    async def get_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 100) -> list:
        return []

    async def get_balance(self) -> float:
        return 0.0
