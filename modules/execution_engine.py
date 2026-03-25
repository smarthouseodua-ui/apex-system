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


def _resolve_session(tf: dict) -> tuple[str, str]:
    """Возвращает (session_name, session_label) по флагам из time_features_for_dt.

    session_name  — для БД: ASIA, ASIA+HK, HONG_KONG, LONDON, LONDON+NY, NEW_YORK, OFF
    session_label — человекочитаемая метка с уточнением (OPEN) и т.д.
    """
    asia     = tf.get("session_asia", 0)
    hk       = tf.get("session_hong_kong", 0)
    london   = tf.get("session_london", 0)
    new_york = tf.get("session_new_york", 0)
    lon_open = tf.get("event_london_open", 0)
    ny_open  = tf.get("event_ny_open", 0)

    if asia and hk:
        return "ASIA+HK", "ASIA (HK)"
    elif asia:
        return "ASIA", "ASIA"
    elif london and new_york:
        label = "LONDON+NY (OPEN)" if ny_open else "LONDON+NY"
        return "LONDON+NY", label
    elif london:
        label = "LONDON (OPEN)" if lon_open else "LONDON"
        return "LONDON", label
    elif new_york:
        label = "NEW YORK (OPEN)" if ny_open else "NEW YORK"
        return "NEW_YORK", label
    elif hk:
        return "HONG_KONG", "HONG KONG"
    else:
        return "OFF", "OFF"


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
        session_name, session_label = _resolve_session(time_features)

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
