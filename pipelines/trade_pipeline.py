"""
APEX PROTOCOL™ — Trade Pipeline
Главный пайплайн — связывает все модули в единый поток.
"""

import asyncio
import logging
from core.orchestrator import Orchestrator
from core.time_manager import TimeManager

logger = logging.getLogger("apex.pipeline")


class TradePipeline:

    def __init__(self, config: dict):
        self.config = config
        self.orchestrator = Orchestrator(config)
        self.time_manager = TimeManager(config)

    async def run(self):
        """Запуск пайплайна."""
        logger.info("TradePipeline starting...")

        # Проверка тестового контура
        try:
            from services.test_control import read as tc_read
            tc = tc_read()
        except Exception:
            tc = {}

        if tc.get("test_enabled") or tc.get("hourly_test_enabled"):
            mode = tc.get("mode", "TEST")
            logger.info(f"Test control ACTIVE [{mode}] — bypassing session guard")

            if not tc.get("scanner_enabled") or not tc.get("entries_enabled"):
                logger.info("Test control: scanner/entries disabled — skipping cycle")
                return

            if tc.get("hourly_test_enabled"):
                self.config["_hourly_test"] = True
            else:
                self.config.pop("_hourly_test", None)

            await self.orchestrator.run()
            return

        # Штатная логика
        self.config.pop("_hourly_test", None)

        session_info = self.time_manager.get_session_info()
        logger.info(f"Session: {session_info['session']} | Direction: {session_info['direction']} | Time: {session_info['time']}")

        if self.time_manager.is_blocked_hour():
            logger.warning(f"Blocked hour {self.time_manager.current_hour()}:xx — pipeline paused")
            return

        if False and not self.time_manager.is_trading_time():
            logger.info("OFF session — pipeline skipped")
            return

        await self.orchestrator.run()

    async def run_loop(self):
        """Бесконечный цикл пайплайна."""
        max_cycles = self.config.get("pipeline", {}).get("max_cycles", 0)
        cycle_interval = self.config.get("cycle_interval", 60)
        cycle = 0

        while True:
            cycle += 1
            logger.info(f"=== Pipeline cycle #{cycle} ===")
            try:
                await self.run()
            except Exception as e:
                logger.error(f"Pipeline cycle error: {e}", exc_info=True)

            if max_cycles and cycle >= max_cycles:
                logger.info(f"Max cycles reached ({max_cycles}), stopping")
                break

            await asyncio.sleep(cycle_interval)
