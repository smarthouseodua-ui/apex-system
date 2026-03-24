"""
APEX PROTOCOL™ — Strategy Engine
Каркас. Тестовые стратегии: SESSION_ORB_5M, FIRST_10M_BREAKOUT, PREV_CANDLE_BREAKOUT.
Отдельный режим: FIRST_5M_SESSION.
Пишет в SKL01_T02_strategy_log.
"""

import logging
from datetime import datetime
from pytz import timezone as tz
from core.event_bus import EventBus

PODGORICA = tz("Europe/Podgorica")
from services.exchange_service import ExchangeService
from storage.db.repository import Repository

logger = logging.getLogger("apex.strategy_engine")

SESSION_OPEN_HOURS = [8, 12, 17]


class StrategyEngine:

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.exchange_service = ExchangeService(config)
        self.repo = Repository()
        self._connected = False
        # hourly test: {target_hour: set(symbols already traded)}
        self._hourly_trades: dict[int, set] = {}

    async def _ensure_connected(self):
        if not self._connected:
            await self.exchange_service.connect()
            self._connected = True

    def _current_session_hour(self) -> int | None:
        now = datetime.now(PODGORICA)
        if now.hour in SESSION_OPEN_HOURS and now.minute < 5:
            return now.hour
        return None

    async def analyze(self, candidates: list) -> list:
        try:
            await self._ensure_connected()

            # --- FIRST_5M_SESSION: отдельный режим, не зависит от hourly_test ---
            try:
                from services.test_control import read as tc_read
                tc = tc_read()
            except Exception:
                tc = {}

            if tc.get("mode") == "FIRST_5M_SESSION":
                return await self.run_first_5m_session(candidates)

            if self.config.get("_hourly_test"):
                return await self._hourly_test_analyze(candidates)

            signals = []
            session_hour = self._current_session_hour()
            if session_hour is None:
                logger.info("StrategyEngine: не в окне сессии — пропуск")
                return []

            logger.info(f"StrategyEngine: сессия {session_hour}:00 — сканирую {len(candidates)} кандидатов")

            for candidate in candidates:
                signal = await self._session_orb_signal(candidate, session_hour)
                if signal:
                    self.repo.log_strategy(signal)
                    signals.append(signal)

            logger.info(f"StrategyEngine: {len(signals)} сигналов")
            await self.event_bus.publish("strategy.done", {"signals": signals})
            return signals
        except Exception as e:
            logger.error(f"StrategyEngine error: {e}", exc_info=True)
            return []

    # ── FIRST_5M_SESSION ─────────────────────────────────────────────────────

    async def run_first_5m_session(self, candidates: list) -> list:
        """
        FIRST_5M_SESSION — отдельный режим, не зависит от hourly_test.

        1. Читает start_time и fired из test_control
        2. Если fired == True → return []
        3. Для каждого кандидата берёт 10 свечей 5m
        4. Находит первую свечу, close_time которой > start_time
        5. Если свеча ещё не закрыта → пропуск
        6. LONG:  first_close > prev_high
           SHORT: first_close < prev_low
        7. После первого сигнала → tc_write(first_5m_fired=True), выход
        """
        try:
            from services.test_control import read as tc_read, write as tc_write
            tc = tc_read()
        except Exception:
            logger.error("FIRST_5M_SESSION: не удалось прочитать test_control")
            return []

        # Уже сработала — пропуск
        if tc.get("first_5m_fired"):
            logger.info("FIRST_5M_SESSION: уже сработала (fired=True) — пропуск")
            return []

        # Парсим start_time
        start_time_str = tc.get("first_5m_session_start")
        if not start_time_str:
            logger.warning("FIRST_5M_SESSION: нет first_5m_session_start — пропуск")
            return []

        try:
            start_time = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M:%S")
        except (ValueError, TypeError):
            logger.error(f"FIRST_5M_SESSION: неверный формат start_time: {start_time_str}")
            return []

        # start_time в миллисекундах для сравнения с candle timestamp
        start_ts_ms = int(start_time.timestamp() * 1000)

        now = datetime.now(PODGORICA)
        now_ts_ms = int(now.timestamp() * 1000)

        logger.info(
            f"FIRST_5M_SESSION: start={start_time_str}, "
            f"кандидатов={len(candidates)}, ожидаю закрытия первой 5m свечи"
        )

        signals = []

        for candidate in candidates:
            symbol = candidate["symbol"]
            try:
                candles = await self.exchange_service.get_ohlcv(symbol, "5m", limit=10)
                if len(candles) < 2:
                    continue

                # candles отсортированы от старой к новой: [oldest, ..., newest]
                # Каждая свеча: [timestamp_ms, open, high, low, close, volume]
                # timestamp_ms — время ОТКРЫТИЯ свечи
                # close_time = timestamp_ms + 5 * 60 * 1000

                first_candle = None
                prev_candle = None

                for i, candle in enumerate(candles):
                    candle_open_ts = candle[0]
                    candle_close_ts = candle_open_ts + 5 * 60 * 1000  # +5 минут

                    # Ищем первую свечу, которая закрылась ПОСЛЕ start_time
                    if candle_close_ts > start_ts_ms:
                        # Проверяем что свеча уже закрыта (close_time <= now)
                        if candle_close_ts > now_ts_ms:
                            # Свеча ещё не закрыта — ждём
                            break

                        first_candle = candle
                        if i > 0:
                            prev_candle = candles[i - 1]
                        break

                if first_candle is None or prev_candle is None:
                    continue

                first_close = first_candle[4]   # close первой свечи
                prev_high   = prev_candle[2]    # high предыдущей
                prev_low    = prev_candle[3]    # low предыдущей

                if prev_high <= prev_low:
                    continue

                current_price = candidate["price"]

                if first_close > prev_high:
                    direction = "long"
                elif first_close < prev_low:
                    direction = "short"
                else:
                    continue

                signal = {
                    "symbol":       symbol,
                    "direction":    direction,
                    "entry":        round(current_price, 6),
                    "strategy":     "FIRST_5M_SESSION",
                    "timeframe":    "5m",
                    "session_hour": now.hour,
                    "first_close":  first_close,
                    "prev_high":    prev_high,
                    "prev_low":     prev_low,
                    "confidence":   1.0,
                    "generated_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
                }

                self.repo.log_strategy(signal)
                signals.append(signal)

                # 1 сигнал = 1 сделка — помечаем как сработавшую
                try:
                    tc_write({"first_5m_fired": True})
                except Exception:
                    pass

                logger.info(
                    f"FIRST_5M_SESSION: сигнал {direction} {symbol} "
                    f"(first_close={first_close}, prev_high={prev_high}, prev_low={prev_low})"
                )
                break  # Один сигнал — выход

            except Exception as e:
                logger.error(f"FIRST_5M_SESSION error {symbol}: {e}")
                continue

        if not signals:
            logger.info("FIRST_5M_SESSION: нет сигналов в этом цикле")

        await self.event_bus.publish("strategy.done", {"signals": signals})
        return signals

    # ── HOURLY TEST ──────────────────────────────────────────────────────────

    async def _hourly_test_analyze(self, candidates: list) -> list:
        """
        Часовой тест: SESSION_ORB_5M, FIRST_10M_BREAKOUT, PREV_CANDLE_BREAKOUT.
        Один вход на символ в час. Только simulation.
        """
        now = datetime.now(PODGORICA)

        try:
            from services.test_control import read as tc_read, write as tc_write
            tc = tc_read()
        except Exception:
            tc = {}

        active_filter = tc.get("active_filter", "SESSION_ORB_5M")
        manual_mode   = tc.get("manual_hour_enabled", False)
        selected_hour = tc.get("selected_hour")

        if manual_mode and selected_hour is not None:
            target_hour = selected_hour
            logger.info(
                f"HourlyTest MANUAL: целевой час={target_hour}:00, "
                f"текущее время={now.hour}:{now.minute:02d}"
            )
        else:
            target_hour = now.hour

            if active_filter == "PREV_CANDLE_BREAKOUT":
                # Без ограничений по минутам — работает каждый цикл
                pass
            elif active_filter == "FIRST_10M_BREAKOUT":
                # Вход только в минуты 10–14
                if now.minute < 10 or now.minute >= 15:
                    logger.info(
                        f"HourlyTest FIRST_10M_BREAKOUT: вне окна входа "
                        f"(минута={now.minute}, нужно 10–14) — пропуск"
                    )
                    return []
            else:
                # SESSION_ORB_5M и прочие: первые 5 минут
                if now.minute >= 5:
                    logger.info(f"HourlyTest AUTO: вне окна (минута={now.minute}) — пропуск")
                    return []

        # Сбрасываем словарь если начался новый час
        if target_hour not in self._hourly_trades:
            self._hourly_trades = {target_hour: set()}

        already_traded = self._hourly_trades[target_hour]
        signals = []

        logger.info(
            f"HourlyTest [{active_filter}]: час={target_hour}:00 — "
            f"сканирую {len(candidates)} кандидатов, "
            f"уже торговано: {len(already_traded)}"
        )

        for candidate in candidates:
            symbol = candidate["symbol"]
            # PREV_CANDLE_BREAKOUT: не блокируем по already_traded —
            # повторный вход разрешён после закрытия позиции (дедупликация через SignalGate)
            if active_filter != "PREV_CANDLE_BREAKOUT" and symbol in already_traded:
                continue

            if active_filter == "PREV_CANDLE_BREAKOUT":
                signal = await self._prev_candle_breakout_signal(candidate, target_hour)
            elif active_filter == "FIRST_10M_BREAKOUT":
                signal = await self._first_10m_breakout_signal(candidate, target_hour)
                if signal:
                    signal["strategy"] = "FIRST_10M_BREAKOUT"
            elif manual_mode:
                signal = await self._manual_open_signal(candidate, target_hour)
            else:
                signal = await self._session_orb_signal(candidate, target_hour)
                if signal:
                    signal["strategy"] = "HOURLY_ORB_5M"

            if signal:
                if active_filter != "PREV_CANDLE_BREAKOUT":
                    already_traded.add(symbol)
                self.repo.log_strategy(signal)
                signals.append(signal)

        logger.info(f"HourlyTest [{active_filter}]: час={target_hour}:00 → {len(signals)} сигналов")

        # Записываем ORB диапазон в state после первого сигнала
        if signals and manual_mode:
            try:
                first = signals[0]
                tc_write({
                    "selected_hour_orb_high": first.get("orb_high"),
                    "selected_hour_orb_low":  first.get("orb_low"),
                })
            except Exception:
                pass

        await self.event_bus.publish("strategy.done", {"signals": signals})
        return signals

    # ── SIGNAL METHODS ───────────────────────────────────────────────────────

    async def _prev_candle_breakout_signal(self, candidate: dict, session_hour: int) -> dict | None:
        """
        PREV CANDLE BREAKOUT (тестовый режим непрерывной генерации):
        - Берёт последнюю закрытую 5m свечу (candles[1] из limit=3)
        - Если current_price > prev_high → LONG
        - Если current_price < prev_low  → SHORT
        - Очень частое условие — высокий поток сигналов для теста каркаса
        """
        symbol = candidate["symbol"]
        try:
            candles = await self.exchange_service.get_ohlcv(symbol, "5m", limit=3)
            if len(candles) < 2:
                return None

            prev_candle = candles[1]   # последняя закрытая свеча
            prev_high = prev_candle[2]
            prev_low  = prev_candle[3]

            if prev_high <= prev_low:
                return None

            current_price = candidate["price"]

            if current_price > prev_high:
                direction = "long"
                entry = round(current_price, 6)
                sl    = round(entry * (1 - 0.004), 6)
            elif current_price < prev_low:
                direction = "short"
                entry = round(current_price, 6)
                sl    = round(entry * (1 + 0.004), 6)
            else:
                return None

            return {
                "symbol":       symbol,
                "direction":    direction,
                "entry":        entry,
                "sl":           sl,
                "strategy":     "PREV_CANDLE_BREAKOUT",
                "timeframe":    "5m",
                "session_hour": session_hour,
                "orb_high":     prev_high,
                "orb_low":      prev_low,
                "confidence":   1.0,
                "generated_at": datetime.now(PODGORICA).strftime("%Y-%m-%dT%H:%M:%S"),
            }
        except Exception as e:
            logger.error(f"PREV_CANDLE_BREAKOUT error {symbol}: {e}")
            return None

    async def _first_10m_breakout_signal(self, candidate: dict, session_hour: int) -> dict | None:
        """
        FIRST 10M BREAKOUT:
        - Берёт первые 2 свечи 5m текущего часа (= 10 минут)
        - first_high = max HIGH двух свечей
        - first_low  = min LOW  двух свечей
        - Если current_price > first_high → LONG
        - Если current_price < first_low  → SHORT
        """
        symbol = candidate["symbol"]
        try:
            candles = await self.exchange_service.get_ohlcv(symbol, "5m", limit=3)
            if len(candles) < 2:
                return None

            c0, c1 = candles[0], candles[1]
            first_high = max(c0[2], c1[2])
            first_low  = min(c0[3], c1[3])

            if first_high <= first_low:
                return None

            current_price = candidate["price"]

            if current_price > first_high:
                direction = "long"
                entry = round(current_price, 6)
                sl    = round(entry * (1 - 0.004), 6)
            elif current_price < first_low:
                direction = "short"
                entry = round(current_price, 6)
                sl    = round(entry * (1 + 0.004), 6)
            else:
                return None

            return {
                "symbol":       symbol,
                "direction":    direction,
                "entry":        entry,
                "sl":           sl,
                "strategy":     "FIRST_10M_BREAKOUT",
                "timeframe":    "5m",
                "session_hour": session_hour,
                "orb_high":     first_high,
                "orb_low":      first_low,
                "confidence":   1.0,
                "generated_at": datetime.now(PODGORICA).strftime("%Y-%m-%dT%H:%M:%S"),
            }
        except Exception as e:
            logger.error(f"FIRST_10M_BREAKOUT error {symbol}: {e}")
            return None

    async def _manual_open_signal(self, candidate: dict, session_hour: int) -> dict | None:
        """
        Ручной тест: сравниваем текущую цену с open первой 5м-свечи.
        LONG  если current_price > open * 1.001
        SHORT если current_price < open * 0.999
        """
        symbol = candidate["symbol"]
        try:
            candles = await self.exchange_service.get_ohlcv(symbol, "5m", limit=2)
            if len(candles) < 1:
                return None

            ref_candle = candles[0]
            open_price = ref_candle[1]
            orb_high   = ref_candle[2]
            orb_low    = ref_candle[3]
            current_price = candidate["price"]

            if current_price > open_price * 1.001:
                direction = "long"
                entry = round(current_price, 6)
                sl    = round(orb_low, 6)
            elif current_price < open_price * 0.999:
                direction = "short"
                entry = round(current_price, 6)
                sl    = round(orb_high, 6)
            else:
                return None

            return {
                "symbol":       symbol,
                "direction":    direction,
                "entry":        entry,
                "sl":           sl,
                "strategy":     "MANUAL_OPEN_5M",
                "timeframe":    "5m",
                "session_hour": session_hour,
                "orb_high":     orb_high,
                "orb_low":      orb_low,
                "open_price":   open_price,
                "confidence":   1.0,
                "generated_at": datetime.now(PODGORICA).strftime("%Y-%m-%dT%H:%M:%S")
            }
        except Exception as e:
            logger.error(f"ManualOpenSignal error {symbol}: {e}")
            return None

    async def _session_orb_signal(self, candidate: dict, session_hour: int) -> dict | None:
        symbol = candidate["symbol"]
        try:
            candles = await self.exchange_service.get_ohlcv(symbol, "5m", limit=3)
            if len(candles) < 2:
                return None

            session_candle = candles[0]
            orb_high = session_candle[2]
            orb_low  = session_candle[3]

            if orb_high <= orb_low:
                return None

            current_price = candidate["price"]

            direction = None
            if current_price > orb_high:
                direction = "long"
                entry = round(current_price, 6)
                sl    = round(orb_low, 6)
            elif current_price < orb_low:
                direction = "short"
                entry = round(current_price, 6)
                sl    = round(orb_high, 6)

            if not direction:
                return None

            return {
                "symbol":       symbol,
                "direction":    direction,
                "entry":        entry,
                "sl":           sl,
                "strategy":     "SESSION_ORB_5M",
                "timeframe":    "5m",
                "session_hour": session_hour,
                "orb_high":     orb_high,
                "orb_low":      orb_low,
                "confidence":   1.0,
                "generated_at": datetime.now(PODGORICA).strftime("%Y-%m-%dT%H:%M:%S")
            }
        except Exception as e:
            logger.error(f"Session ORB error {symbol}: {e}")
            return None
