"""
APEX PROTOCOL™ — Execution Engine
Исполняет ордера. Пишет в SKL01_T05_execution_log.
"""

import logging
from datetime import datetime
from pytz import timezone as tz
from core.event_bus import EventBus

PODGORICA = tz("Europe/Podgorica")
from storage.db.repository import Repository
from services.telegram_notifier import get_notifier
from core.time_manager import time_features_for_dt

logger = logging.getLogger("apex.execution_engine")


def _build_session_label(tf: dict) -> str:
    """Человекочитаемая метка сессии по флагам из time_features_for_dt."""
    asia     = tf.get("session_asia", 0)
    london   = tf.get("session_london", 0)
    new_york = tf.get("session_new_york", 0)
    hk_open      = tf.get("event_hk_open", 0)
    lon_open     = tf.get("event_london_open", 0)
    ny_open      = tf.get("event_ny_open", 0)

    # 1. Overlap London + NY — высший приоритет
    if london and new_york:
        return "LONDON (NY)"

    # 2. Asia (с уточнением HK)
    if asia:
        return "ASIA (HK)" if hk_open else "ASIA"

    # 3. London
    if london:
        return "LONDON (OPEN)" if lon_open else "LONDON"

    # 4. New York
    if new_york:
        return "NEW YORK (OPEN)" if ny_open else "NEW YORK"

    return "OFF"


class ExecutionEngine:

    def __init__(self, config: dict, event_bus: EventBus, id_manager=None):
        self.config = config
        self.event_bus = event_bus
        self.repo = Repository()
        self.mode = config.get("mode", "simulation")
        self.id_manager = id_manager

    async def execute(self, orders: list) -> list:
        try:
            positions = []
            for order in orders:
                position = await self._execute_order(order)
                if position:
                    self.repo.log_execution(position)
                    positions.append(position)
                    try:
                        notifier = get_notifier()
                        if notifier:
                            await notifier.notify_open(position)
                    except Exception as e:
                        logger.warning(f"notify_open error: {e}")

            logger.info(f"ExecutionEngine [{self.mode}]: {len(positions)} positions opened")
            await self.event_bus.publish("execution.done", {"positions": positions})
            return positions
        except Exception as e:
            logger.error(f"ExecutionEngine error: {e}", exc_info=True)
            return []

    async def _execute_order(self, order: dict) -> dict | None:
        if self.mode == "simulation":
            return self._simulate(order)
        elif self.mode == "live":
            return await self._execute_live(order)
        return None

    def _simulate(self, order: dict) -> dict:
        trade_id = self.id_manager.next_trade_id() if self.id_manager else None
        opened_at = datetime.now(PODGORICA).strftime("%Y-%m-%dT%H:%M:%S")
        time_features = time_features_for_dt(opened_at)
        session_label = _build_session_label(time_features)

        asia     = time_features.get("session_asia", 0)
        london   = time_features.get("session_london", 0)
        new_york = time_features.get("session_new_york", 0)
        if asia:
            session_name = "ASIA"
        elif london:
            session_name = "LONDON"
        elif new_york:
            session_name = "NEW_YORK"
        else:
            session_name = "OFF"

        return {
            **order,
            "trade_id": trade_id,
            "status": "open",
            "fill_price": order["entry"],
            "slippage": 0.0,
            "commission": 0.0,
            "opened_at": opened_at,
            "mode": "simulation",
            **time_features,
            "session_label": session_label,
            "session_name": session_name,
        }

    async def _execute_live(self, order: dict) -> dict | None:
        logger.warning("Live execution not implemented yet")
        return None
