"""
APEX PROTOCOL™ — ID Manager
Генерация уникальных идентификаторов для сделок, циклов, ордеров.
"""

import logging
from datetime import datetime

logger = logging.getLogger("apex.id_manager")


class IdManager:

    def __init__(self):
        self._cycle_counter = 0
        self._trade_counter = 0
        self._order_counter = 0

    def next_cycle_id(self) -> str:
        self._cycle_counter += 1
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"CYC-{ts}-{self._cycle_counter:04d}"

    def next_trade_id(self) -> str:
        self._trade_counter += 1
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"TRD-{ts}-{self._trade_counter:04d}"

    def next_order_id(self) -> str:
        self._order_counter += 1
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"ORD-{ts}-{self._order_counter:04d}"

    def get_counters(self) -> dict:
        return {
            "cycles": self._cycle_counter,
            "trades": self._trade_counter,
            "orders": self._order_counter
        }
