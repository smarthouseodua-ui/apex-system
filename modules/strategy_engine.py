"""
APEX PROTOCOL™ — Strategy Engine
ORB (Opening Range Breakout) — строго по APEX_ORB_UNIFIED_SPEC v1.0
Логика: BUILD_ORB → BREAKOUT → RETEST → CONFIRM → SIGNAL
"""

import logging
from datetime import datetime, timedelta, timezone
import pytz

logger = logging.getLogger("apex.strategy_engine")

PODGORICA = pytz.timezone("Europe/Podgorica")

SESSION_TZ = {
    "TOKYO":     pytz.timezone("Asia/Tokyo"),
    "HONG_KONG": pytz.timezone("Asia/Hong_Kong"),
    "LONDON":    pytz.timezone("Europe/London"),
    "NEW_YORK":  pytz.timezone("America/New_York"),
    "TEST_1":    pytz.timezone("Europe/Podgorica"),
    "TEST_2":    pytz.timezone("Europe/Podgorica"),
    "TEST_3":    pytz.timezone("Europe/Podgorica"),
}


class StrategyEngine:

    def __init__(self, config: dict, event_bus=None):
        self.config = config
        self.event_bus = event_bus
        self.exchange_service = None
        self._connected = False
        self.repo = None
        self._orb_states: dict[str, dict] = {}

    async def _ensure_connected(self):
        if not self._connected:
            from services.exchange_service import ExchangeService
            self.exchange_service = ExchangeService(self.config)
            await self.exchange_service.connect()
            self._connected = True
        if self.repo is None:
            from storage.db.repository import Repository
            self.repo = Repository()

    async def analyze(self, candidates: list) -> list:
        try:
            await self._ensure_connected()
            session_name, session_open_utc = self._get_active_session()
            if not session_name or not session_open_utc:
                logger.info("StrategyEngine: нет активной сессии")
                return []

            now_utc = datetime.now(timezone.utc)
            exec_window_end = session_open_utc + timedelta(minutes=90)

            if now_utc < session_open_utc:
                logger.info(f"StrategyEngine [{session_name}]: сессия ещё не открылась")
                return []
            if now_utc >= exec_window_end:
                logger.info(f"StrategyEngine [{session_name}]: Execution Window закрыто")
                return []

            logger.info(f"StrategyEngine [{session_name}]: сканируем {len(candidates)} кандидатов")

            signals = []
            for candidate in candidates:
                signal = await self._process_candidate(candidate, session_name, session_open_utc, now_utc)
                if signal:
                    signals.append(signal)
                    break  # MAX 1 активная сделка

            logger.info(f"StrategyEngine [{session_name}]: {len(signals)} сигналов")

            if self.repo:
                for s in signals:
                    self.repo.log_strategy(s)

            return signals

        except Exception as e:
            logger.error(f"StrategyEngine error: {e}", exc_info=True)
            return []

    async def _process_candidate(self, candidate, session_name, session_open_utc, now_utc):
        symbol = candidate.get("symbol")
        try:
            orb = await self._build_orb(symbol, session_open_utc)
            if not orb:
                return None

            breakout = await self._detect_breakout(symbol, orb, session_open_utc)
            if not breakout:
                return None

            retest = await self._wait_retest(symbol, orb, breakout)
            if not retest:
                return None

            confirmation = await self._confirm_entry(symbol, breakout["direction"])
            if not confirmation:
                return None

            exec_window_end = session_open_utc + timedelta(minutes=90)
            if datetime.now(timezone.utc) >= exec_window_end:
                logger.info(f"[CANCEL] {symbol}: время вышло за Execution Window")
                return None

            direction   = breakout["direction"]
            entry_price = confirmation["entry_price"]

            if direction == "long":
                sl = retest["low"]
                R  = entry_price - sl
            else:
                sl = retest["high"]
                R  = sl - entry_price

            if R <= 0:
                logger.warning(f"[CANCEL] {symbol}: R <= 0")
                return None

            tp1 = entry_price + R   if direction == "long" else entry_price - R
            tp2 = entry_price + 2*R if direction == "long" else entry_price - 2*R
            tp3 = entry_price + 3*R if direction == "long" else entry_price - 3*R

            obs_start  = session_open_utc + timedelta(minutes=90)
            hard_close = session_open_utc + timedelta(minutes=120)
            tz         = SESSION_TZ.get(session_name, PODGORICA)
            now_local  = datetime.now(tz)

            signal = {
                "symbol":                   symbol,
                "direction":                direction,
                "session_name":             session_name,
                "timezone":                 str(tz),
                "strategy":                 "APEX_ORB",
                "timeframe":                "5m",
                "session_open_time":        session_open_utc.isoformat(),
                "execution_window_start":   session_open_utc.isoformat(),
                "execution_window_end":     exec_window_end.isoformat(),
                "observation_window_start": obs_start.isoformat(),
                "hard_close_time":          hard_close.isoformat(),
                "orb_high":                 orb["orb_high"],
                "orb_low":                  orb["orb_low"],
                "orb_mid":                  orb["orb_mid"],
                "orb_size":                 orb["orb_size"],
                "entry":                    round(entry_price, 6),
                "entry_price":              round(entry_price, 6),
                "entry_time":               now_local.strftime("%Y-%m-%d %H:%M %Z"),
                "entry_hour":               now_local.hour,
                "entry_minute":             now_local.minute,
                "sl":                       round(sl, 6),
                "tp1":                      round(tp1, 6),
                "tp2":                      round(tp2, 6),
                "tp3":                      round(tp3, 6),
                "risk_R_value":             round(R, 6),
                "confidence":               1.0,
                "generated_at":             datetime.now(PODGORICA).strftime("%Y-%m-%dT%H:%M:%S"),
                "score":                    candidate.get("score"),
                "price":                    candidate.get("price"),
                "ema":                      candidate.get("ema"),
                "reasons":                  candidate.get("reasons", []),
                "candidate_status":         candidate.get("candidate_status"),
                "scanned_at":               candidate.get("scanned_at"),
            }

            logger.info(
                f"[SIGNAL] {symbol} {direction.upper()} | "
                f"entry={entry_price:.4f} SL={sl:.4f} "
                f"TP1={tp1:.4f} TP2={tp2:.4f} TP3={tp3:.4f} R={R:.6f}"
            )
            return signal

        except Exception as e:
            logger.error(f"_process_candidate {symbol}: {e}", exc_info=True)
            return None

    async def _build_orb(self, symbol, session_open_utc):
        try:
            candles = await self.exchange_service.get_ohlcv(symbol, "5m", limit=10)
            if not candles or len(candles) < 2:
                return None

            open_ts_ms    = int(session_open_utc.timestamp() * 1000)
            range_end_ms  = open_ts_ms + 5 * 60 * 1000
            now_ms        = int(datetime.now(timezone.utc).timestamp() * 1000)

            range_candle = None
            for c in candles:
                if c[0] >= open_ts_ms and (c[0] + 5*60*1000) <= now_ms:
                    range_candle = c
                    break

            if not range_candle:
                range_candle = candles[-2]

            orb_high = range_candle[2]
            orb_low  = range_candle[3]
            orb_size = orb_high - orb_low

            if orb_size <= 0:
                return None

            return {
                "orb_high": round(orb_high, 6),
                "orb_low":  round(orb_low,  6),
                "orb_mid":  round((orb_high + orb_low) / 2, 6),
                "orb_size": round(orb_size, 6),
            }
        except Exception as e:
            logger.error(f"_build_orb {symbol}: {e}")
            return None

    async def _detect_breakout(self, symbol, orb, session_open_utc):
        try:
            candles = await self.exchange_service.get_ohlcv(symbol, "5m", limit=20)
            if not candles:
                return None

            range_end_ts = int(session_open_utc.timestamp() * 1000) + 5 * 60 * 1000

            for c in candles:
                if c[0] < range_end_ts:
                    continue
                candle_close = c[4]
                if candle_close > orb["orb_high"]:
                    return {"direction": "long",  "candle_ts": c[0], "candle_close": candle_close}
                elif candle_close < orb["orb_low"]:
                    return {"direction": "short", "candle_ts": c[0], "candle_close": candle_close}

            return None
        except Exception as e:
            logger.error(f"_detect_breakout {symbol}: {e}")
            return None

    async def _wait_retest(self, symbol, orb, breakout):
        try:
            candles = await self.exchange_service.get_ohlcv(symbol, "5m", limit=20)
            if not candles:
                return None

            direction   = breakout["direction"]
            breakout_ts = breakout["candle_ts"]
            orb_high    = orb["orb_high"]
            orb_low     = orb["orb_low"]

            for c in candles:
                if c[0] <= breakout_ts:
                    continue

                high  = c[2]; low = c[3]; close = c[4]

                if direction == "long":
                    if close < orb_high:
                        return None  # инвалидация
                    if low <= orb_high and close >= orb_high:
                        return {"candle_ts": c[0], "high": high, "low": low, "close": close}
                else:
                    if close > orb_low:
                        return None  # инвалидация
                    if high >= orb_low and close <= orb_low:
                        return {"candle_ts": c[0], "high": high, "low": low, "close": close}

            return None
        except Exception as e:
            logger.error(f"_wait_retest {symbol}: {e}")
            return None

    async def _confirm_entry(self, symbol, direction):
        try:
            candles_1m = await self.exchange_service.get_ohlcv(symbol, "1m", limit=5)
            if not candles_1m or len(candles_1m) < 2:
                return None

            prev = candles_1m[-2]
            curr = candles_1m[-1]

            prev_open  = prev[1]; prev_high = prev[2]
            prev_low   = prev[3]; prev_close = prev[4]
            curr_open  = curr[1]; curr_high = curr[2]
            curr_low   = curr[3]; curr_close = curr[4]

            confirmed = False

            if direction == "long":
                engulfing = (curr_close > curr_open and prev_close < prev_open
                             and curr_open <= prev_close and curr_close >= prev_open)
                confirmed = engulfing or (curr_close > prev_high)

            elif direction == "short":
                engulfing = (curr_close < curr_open and prev_close > prev_open
                             and curr_open >= prev_close and curr_close <= prev_open)
                confirmed = engulfing or (curr_close < prev_low)

            if not confirmed:
                return None

            return {"entry_price": curr_close, "candle_ts": curr[0]}

        except Exception as e:
            logger.error(f"_confirm_entry {symbol}: {e}")
            return None

    def _get_active_session(self):
        try:
            from core.session_engine import _ALL_SESSIONS, get_session_state
            now_utc = datetime.now(timezone.utc)

            for name in _ALL_SESSIONS:
                state = get_session_state(name)
                if state.get("фаза") == "ВХОД":
                    open_str = _ALL_SESSIONS[name]["open"]
                    h, m = map(int, open_str.split(":"))
                    open_dt = now_utc.replace(hour=h, minute=m, second=0, microsecond=0)
                    return name, open_dt

            return None, None
        except Exception as e:
            logger.error(f"_get_active_session: {e}")
            return None, None
