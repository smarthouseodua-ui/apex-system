"""
APEX PROTOCOL™ — Fee Utils
Утилита получения fee rate из централизованного конфига.
"""

from config.fees_config import FEES_CONFIG


def get_fee_rate(exchange: str = "BYBIT", execution_type: str = "taker") -> float:
    """Возвращает fee percent (например 0.055) для указанной биржи и типа исполнения."""
    try:
        return FEES_CONFIG["SIMULATION"][str(exchange).upper()][execution_type]
    except Exception:
        return FEES_CONFIG["SIMULATION"]["DEFAULT"][execution_type]
