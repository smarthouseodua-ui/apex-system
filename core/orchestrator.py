"""
APEX PROTOCOL™ — Core Orchestrator
Главный координатор торгового пайплайна.
Запускает, останавливает и контролирует все модули.
"""

import asyncio
import logging
from datetime import datetime
from core.time_manager import TimeManager
from core.state_manager import StateManager
from core.event_bus import EventBus
from core.id_manager import IdManager

logger = logging.getLogger("apex.orchestrator")


class Orchestrator:

    def __init__(self, config: dict):
        self.config = config
        self.running = False

        # Ядро
        self.time_manager = TimeManager(config)
        self.state_manager = StateManager()
        self.event_bus = EventBus()
        self.id_manager = IdManager()

        # Модули (инициализируются в setup)
        self.scanner = None
        self.strategy_engine = None
        self.signal_gate = None
        self.risk_manager = None
        self.execution_engine = None
        self.position_manager = None
        self.finalizer = None

        logger.info("Orchestrator initialized")

    async def setup(self):
        """Инициализация всех модулей."""
        from modules.scanner import Scanner
        from modules.strategy_engine import StrategyEngine
        from modules.signal_gate import SignalGate
        from modules.risk_manager import RiskManager
        from modules.execution_engine import ExecutionEngine
        from modules.position_manager import PositionManager
        from modules.finalizer import Finalizer

        self.scanner = Scanner(self.config, self.event_bus)
        self.strategy_engine = StrategyEngine(self.config, self.event_bus)
        self.signal_gate = SignalGate(self.config, self.event_bus)
        self.risk_manager = RiskManager(self.config, self.event_bus)
        self.execution_engine = ExecutionEngine(self.config, self.event_bus)
        self.position_manager = PositionManager(self.config, self.event_bus)
        self.finalizer = Finalizer(self.config, self.event_bus)

        logger.info("All modules initialized")

    async def run(self):
        """Главный цикл пайплайна."""
        await self.setup()
        self.running = True
        self.state_manager.set_state("running")
        logger.info(f"Pipeline started at {datetime.now()}")

        try:
            while self.running:
                await self._run_cycle()
                await asyncio.sleep(self.config.get("cycle_interval", 60))
        except asyncio.CancelledError:
            logger.info("Pipeline cancelled")
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
        finally:
            await self.stop()

    async def _run_cycle(self):
        """Один цикл пайплайна: Scanner → ... → Finalizer."""
        cycle_id = self.id_manager.next_cycle_id()
        logger.info(f"[{cycle_id}] Cycle start")

        try:
            # 1. Scanner — ищем кандидатов
            candidates = await self.scanner.scan()
            if not candidates:
                logger.info(f"[{cycle_id}] No candidates found")
                return

            # 2. Strategy Engine — генерируем сигналы
            signals = await self.strategy_engine.analyze(candidates)
            if not signals:
                return

            # 3. Signal Gate — фильтруем сигналы
            approved = await self.signal_gate.filter(signals)
            if not approved:
                return

            # 4. Risk Manager — рассчитываем параметры сделки
            orders = await self.risk_manager.calculate(approved)
            if not orders:
                return

            # 5. Execution Engine — исполняем ордера
            positions = await self.execution_engine.execute(orders)
            if not positions:
                return

            # 6. Position Manager — мониторим позиции
            await self.position_manager.monitor(positions)

            # 7. Finalizer — закрываем и логируем
            await self.finalizer.finalize(positions)

        except Exception as e:
            logger.error(f"[{cycle_id}] Cycle error: {e}", exc_info=True)

    async def stop(self):
        """Остановка пайплайна."""
        self.running = False
        self.state_manager.set_state("stopped")
        logger.info("Pipeline stopped")
