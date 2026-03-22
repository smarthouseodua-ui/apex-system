"""
APEX PROTOCOL™ — Event Bus
Шина событий для коммуникации между модулями.
"""

import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger("apex.event_bus")


class EventBus:

    def __init__(self):
        self._subscribers = defaultdict(list)

    def subscribe(self, event: str, callback):
        """Подписаться на событие."""
        self._subscribers[event].append(callback)
        logger.debug(f"Subscribed to '{event}'")

    async def publish(self, event: str, data: dict = None):
        """Опубликовать событие."""
        callbacks = self._subscribers.get(event, [])
        if not callbacks:
            return
        logger.debug(f"Event '{event}' → {len(callbacks)} subscribers")
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                logger.error(f"Event '{event}' handler error: {e}", exc_info=True)

    def unsubscribe(self, event: str, callback):
        """Отписаться от события."""
        if event in self._subscribers:
            self._subscribers[event].remove(callback)
