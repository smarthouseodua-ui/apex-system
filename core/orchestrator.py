"""
APEX PROTOCOL™ — Core Orchestrator
Главный координатор торгового пайплайна.
Запускает, останавливает и контролирует все модули.
"""

import asyncio
import logging
from datetime import datetime
from pytz import timezone as tz

PODGORICA = tz("Europe/Podgorica")
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

        # Открытые позиции: symbol → position dict
        self._open_positions: dict[str, dict] = {}

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
        self.execution_engine = ExecutionEngine(self.config, self.event_bus, id_manager=self.id_manager)
        self.position_manager = PositionManager(self.config, self.event_bus)
        self.finalizer = Finalizer(self.config, self.event_bus)

        logger.info("All modules initialized")

    async def _load_open_positions(self):
        """Загружает открытые позиции из БД при старте (восстановление после рестарта)."""
        try:
            from storage.db.repository import Repository
            repo = Repository()
            positions = repo.get_open_positions()
            for p in positions:
                self._open_positions[p["symbol"]] = p
            if positions:
                logger.info(
                    f"Restored {len(positions)} open positions from DB: "
                    f"{[p['symbol'] for p in positions]}"
                )
            else:
                logger.info("No open positions in DB to restore")
        except Exception as e:
            logger.error(f"_load_open_positions error: {e}", exc_info=True)

    async def _close_all_session_end(self, reason: str = "SESSION_END"):
        """Принудительное закрытие всех открытых позиций."""
        if not self._open_positions:
            return
        now_dt = datetime.now(PODGORICA)
        now = now_dt.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            from storage.db.repository import Repository
            repo = Repository()
            for symbol, position in self._open_positions.items():
                entry = position.get("entry") or position.get("fill_price") or 0
                direction = position.get("direction", "long")
                size = position.get("size", 0)
                size_usdt = position.get("size_usdt") or position.get("risk_usdt") or 0

                # Берём актуальную цену из T06 (position_manager обновляет её в цикле)
                row = repo.conn.execute(
                    "SELECT current_price FROM SKL01_T06_position_manager_log "
                    "WHERE symbol=? ORDER BY id DESC LIMIT 1",
                    (symbol,)
                ).fetchone()
                if row and row[0]:
                    close_price = row[0]
                else:
                    close_price = position.get("current_price") or entry

                if entry and close_price:
                    if direction == "long":
                        pnl_pct = ((close_price - entry) / entry) * 100
                    else:
                        pnl_pct = ((entry - close_price) / entry) * 100
                    pnl_usdt = round((size_usdt or size * entry) * (pnl_pct / 100), 4)
                else:
                    pnl_pct = 0.0
                    pnl_usdt = 0.0

                # duration_minutes и minutes_to_close
                opened_at_str = position.get("opened_at")
                duration_minutes = None
                if opened_at_str:
                    try:
                        opened_dt = datetime.fromisoformat(opened_at_str)
                        if opened_dt.tzinfo is None:
                            opened_dt = PODGORICA.localize(opened_dt)
                        duration_minutes = int((now_dt - opened_dt).total_seconds() / 60)
                    except Exception:
                        duration_minutes = None

                # T05: пометить как closed
                repo.conn.execute(
                    "UPDATE SKL01_T05_execution_log SET status='closed' "
                    "WHERE symbol=? AND status='open'",
                    (symbol,)
                )

                # T07: через log_final_trade со всеми полями
                repo.log_final_trade({
                    "symbol": symbol,
                    "direction": direction,
                    "strategy": position.get("strategy"),
                    "entry": entry,
                    "close_price": close_price,
                    "sl": position.get("sl"),
                    "tp1": position.get("tp1"),
                    "tp2": position.get("tp2"),
                    "tp3": position.get("tp3"),
                    "size": size,
                    "leverage": position.get("leverage", 1),
                    "pnl_pct": round(pnl_pct, 4),
                    "pnl_usdt": pnl_usdt,
                    "close_reason": reason,
                    "mode": position.get("mode", "simulation"),
                    "session_hour": position.get("session_hour"),
                    "opened_at": opened_at_str,
                    "closed_at": now,
                    "finalized_at": now,
                    "trade_id": position.get("trade_id"),
                    "session_name": position.get("session_name"),
                    "duration_minutes": duration_minutes,
                    "minutes_to_close": duration_minutes,
                })

            logger.info(
                f"{reason}: closed {len(self._open_positions)} positions — "
                f"{list(self._open_positions.keys())}"
            )
            self._open_positions.clear()
        except Exception as e:
            logger.error(f"_close_all_session_end error: {e}", exc_info=True)

    def _tc_scanner_enabled(self) -> bool:
        """Читает scanner_enabled из test_control.json. Если файл недоступен — True."""
        try:
            from services.test_control import read as tc_read
            return tc_read().get("scanner_enabled", True)
        except Exception:
            return True

    async def run(self):
        """Главный цикл пайплайна."""
        await self.setup()
        await self._load_open_positions()

        # Проверка: если уже после :40 — сессия не запускается (пропускается в test mode)
        now = datetime.now(PODGORICA)
        test_mode = self.config.get("_hourly_test", False)
        if not test_mode and now.minute >= 40:
            logger.info(
                f"Session start blocked: current time {now.hour}:{now.minute:02d} — "
                f"already past :40. Waiting for next hour."
            )
            return

        session_end_str = f"{now.hour}:{40:02d}:00"
        logger.info(f"Session window: {now.hour}:{now.minute:02d} → {session_end_str}")

        self.running = True
        self.state_manager.set_state("running")
        logger.info(f"Pipeline started at {datetime.now(PODGORICA)}")

        _was_scanner_on = True

        try:
            while self.running:
                scanner_on = self._tc_scanner_enabled()

                # Если scanner выключен — войти в режим ожидания
                if not scanner_on:
                    if _was_scanner_on:
                        logger.info("test_control: scanner_enabled=False — closing positions, entering idle mode")
                        if self._open_positions:
                            await self._close_all_session_end(reason="MANUAL_STOP")
                        _was_scanner_on = False
                    await asyncio.sleep(self.config.get("cycle_interval", 60))
                    continue

                # Scanner включён — возобновляем работу
                if not _was_scanner_on:
                    logger.info("test_control: scanner_enabled=True — resuming pipeline")
                _was_scanner_on = True

                # Ресинк _hourly_test из test_control (может измениться после Stop → Start)
                try:
                    from services.test_control import read as tc_read
                    _tc = tc_read()
                    if _tc.get("hourly_test_enabled"):
                        self.config["_hourly_test"] = True
                        test_mode = True
                    else:
                        self.config.pop("_hourly_test", None)
                        test_mode = False
                except Exception:
                    pass

                # Проверка окончания сессии (пропускается в test mode)
                if not test_mode and datetime.now(PODGORICA).minute >= 40:
                    logger.info("Session end reached (:40) — force-closing all positions")
                    await self._close_all_session_end()
                    self.running = False
                    break

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
            # --- Сброс состояния SignalGate ---
            self.signal_gate.reset()

            # --- Мониторинг существующих открытых позиций ---
            if self._open_positions:
                open_list = list(self._open_positions.values())
                await self.position_manager.monitor(open_list)
                await self.finalizer.finalize(open_list)
                # Убираем закрытые/closing из трекинга
                self._open_positions = {
                    s: p for s, p in self._open_positions.items()
                    if p.get("status") == "open"
                }
                logger.info(
                    f"[{cycle_id}] Open positions after monitor: {len(self._open_positions)}"
                )

            # --- Новые сигналы ---
            candidates = await self.scanner.scan()
            if not candidates:
                logger.info(f"[{cycle_id}] No candidates found")
                return

            signals = await self.strategy_engine.analyze(candidates)
            if not signals:
                return

            # Передаём текущие открытые символы в SignalGate
            approved = await self.signal_gate.filter(
                signals, open_symbols=set(self._open_positions.keys())
            )
            if not approved:
                return

            orders = await self.risk_manager.calculate(approved)
            if not orders:
                return

            positions = await self.execution_engine.execute(orders)
            if not positions:
                return

            # Добавляем новые позиции в трекинг
            for p in positions:
                self._open_positions[p["symbol"]] = p

            logger.info(
                f"[{cycle_id}] New positions opened: {[p['symbol'] for p in positions]}"
            )

        except Exception as e:
            logger.error(f"[{cycle_id}] Cycle error: {e}", exc_info=True)

    async def stop(self):
        """Остановка пайплайна."""
        self.running = False
        self.state_manager.set_state("stopped")
        logger.info("Pipeline stopped")
