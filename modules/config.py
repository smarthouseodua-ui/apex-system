# config.py
from services.test_control import read as _tc_read

def get_exchange_name() -> str:
    try:
        return _tc_read().get("exchange_name", "Bybit") or "Bybit"
    except Exception:
        return "Bybit"

def get_active_exchanges() -> list:
    try:
        return _tc_read().get("active_exchanges", ["bybit"]) or ["bybit"]
    except Exception:
        return ["bybit"]

MODE = "PAPER"
DEFAULT_BALANCE = 1000
EXCHANGE_NAME = get_exchange_name()
MARKET_TYPE = "Futures"
REQUIRE_API_FOR_LIVE = True
BLOCK_IF_NO_BALANCE = True
BLOCK_IF_RISK = True
