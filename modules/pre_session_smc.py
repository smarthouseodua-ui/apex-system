"""
APEX PROTOCOL™ — Pre-Session SMC Analyzer
Анализ структуры рынка (Smart Money Concepts) перед открытием сессии.
Запускается в фазе PRE_SESSION (за 30 мин до открытия).
Результат → T09_pre_session_log.
"""

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("apex.pre_session_smc")

# Сессии и их время открытия (минуты от полуночи, Europe/Podgorica)
_SESSION_OPEN = {
    "ASIA": 60,        # 01:00
    "HONG_KONG": 150,  # 02:30
    "LONDON": 540,     # 09:00
    "NEW_YORK": 870,   # 14:30
}


class PreSessionAnalyzer:

    def __init__(self, config: dict, exchange_service, repo):
        self.config = config
        self.exchange = exchange_service
        self.repo = repo
        self.semaphore = asyncio.Semaphore(5)

    async def analyze(self, session_name: str, symbol_limit: int = None) -> list[dict]:
        """Запускает SMC-анализ для всех пар universe перед сессией."""
        limit = symbol_limit or self.config.get("pairs_limit", 200)
        today = datetime.now().strftime("%Y-%m-%d")

        if self.repo.get_pre_session_done(session_name, today):
            logger.info(f"[PRE_SESSION] {session_name} already analyzed today, skip")
            return []

        # Universe — топ пар по объёму
        tickers = await self.exchange.get_tickers()
        if not tickers:
            logger.error("[PRE_SESSION] No tickers — abort")
            return []

        sorted_pairs = sorted(
            [(s, t) for s, t in tickers.items()
             if s.endswith("/USDT:USDT") and t.get("quoteVolume")],
            key=lambda x: float(x[1].get("quoteVolume", 0)),
            reverse=True
        )[:limit]
        symbols = [s for s, _ in sorted_pairs]

        logger.info(f"[PRE_SESSION] {session_name}: analyzing {len(symbols)} pairs on 1H")

        now = datetime.now(timezone.utc)
        open_minutes = _SESSION_OPEN.get(session_name, 0)
        open_h, open_m = divmod(open_minutes, 60)
        session_open_time = f"{open_h:02d}:{open_m:02d}"
        pre_session_start = f"{(open_h * 60 + open_m - 30) // 60:02d}:{(open_minutes - 30) % 60:02d}"

        results = []
        tasks = [self._analyze_symbol(sym, session_name, pre_session_start, session_open_time)
                 for sym in symbols]
        done = await asyncio.gather(*tasks, return_exceptions=True)

        for r in done:
            if isinstance(r, Exception):
                logger.error(f"[PRE_SESSION] error: {r}")
                continue
            if r:
                results.append(r)

        logger.info(f"[PRE_SESSION] {session_name}: {len(results)}/{len(symbols)} pairs written to T09")
        return results

    async def _analyze_symbol(self, symbol: str, session_name: str,
                               pre_start: str, session_open: str) -> dict | None:
        async with self.semaphore:
            try:
                ohlcv = await self.exchange.get_ohlcv(symbol, "1h", 100)
                if not ohlcv or len(ohlcv) < 20:
                    return None

                candles = [{"ts": c[0], "o": c[1], "h": c[2], "l": c[3], "c": c[4], "v": c[5]}
                           for c in ohlcv if c[4]]

                if len(candles) < 20:
                    return None

                zone = self._zone_analysis(candles)
                structure = self._market_structure(candles)
                bos = self._detect_bos(candles, structure["trend"])
                choch = self._detect_choch(candles, structure["trend"])
                ob = self._detect_order_block(candles)
                fvg = self._detect_fvg(candles)
                sweep = self._detect_sweep(candles)
                displacement = self._detect_displacement(candles)

                comment = self._build_comment(zone, structure, bos, choch, ob, fvg, sweep)

                record = {
                    "symbol": symbol,
                    "session_name": session_name,
                    "timezone": "Europe/Podgorica",
                    "pre_session_start_time": pre_start,
                    "session_open_time": session_open,
                    "analysis_time": datetime.now().isoformat(),
                    "premium_zone_status": zone["premium"],
                    "discount_zone_status": zone["discount"],
                    "market_structure_state": structure["trend"],
                    "bos_detected": int(bos),
                    "choch_detected": int(choch),
                    "order_block_present": int(ob),
                    "fvg_present": int(fvg),
                    "liquidity_pool_present": 0,
                    "mitigation_present": 0,
                    "displacement_present": int(displacement),
                    "sweep_present": int(sweep),
                    "analyst_comment_short": comment,
                }
                self.repo.log_pre_session(record)
                return record

            except Exception as e:
                logger.error(f"[PRE_SESSION] {symbol}: {e}")
                return None

    # ── Zone Analysis ──

    def _zone_analysis(self, candles: list) -> dict:
        highs = [c["h"] for c in candles]
        lows = [c["l"] for c in candles]
        range_high = max(highs)
        range_low = min(lows)
        rng = range_high - range_low
        if rng == 0:
            return {"premium": "EQUILIBRIUM", "discount": "EQUILIBRIUM"}

        price = candles[-1]["c"]
        ratio = (price - range_low) / rng

        if abs(ratio - 0.5) <= 0.05:
            return {"premium": "EQUILIBRIUM", "discount": "EQUILIBRIUM"}
        elif ratio > 0.5:
            return {"premium": "PREMIUM", "discount": "—"}
        else:
            return {"premium": "—", "discount": "DISCOUNT"}

    # ── Market Structure (HH/HL/LH/LL) ──

    def _find_swings(self, candles: list, lookback: int = 3) -> tuple[list, list]:
        swing_highs, swing_lows = [], []
        for i in range(lookback, len(candles) - lookback):
            h = candles[i]["h"]
            l = candles[i]["l"]
            if all(h >= candles[i + d]["h"] for d in range(-lookback, lookback + 1) if d != 0):
                swing_highs.append((i, h))
            if all(l <= candles[i + d]["l"] for d in range(-lookback, lookback + 1) if d != 0):
                swing_lows.append((i, l))
        return swing_highs, swing_lows

    def _market_structure(self, candles: list) -> dict:
        swing_highs, swing_lows = self._find_swings(candles)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return {"trend": "RANGING", "swing_highs": swing_highs, "swing_lows": swing_lows}

        hh = swing_highs[-1][1] > swing_highs[-2][1]
        hl = swing_lows[-1][1] > swing_lows[-2][1]
        lh = swing_highs[-1][1] < swing_highs[-2][1]
        ll = swing_lows[-1][1] < swing_lows[-2][1]

        if hh and hl:
            trend = "BULLISH"
        elif lh and ll:
            trend = "BEARISH"
        else:
            trend = "RANGING"

        return {"trend": trend, "swing_highs": swing_highs, "swing_lows": swing_lows}

    # ── BOS: Break of Structure ──

    def _detect_bos(self, candles: list, trend: str) -> bool:
        swing_highs, swing_lows = self._find_swings(candles)
        price = candles[-1]["c"]

        if trend == "BULLISH" and len(swing_highs) >= 2:
            return price > swing_highs[-2][1]
        elif trend == "BEARISH" and len(swing_lows) >= 2:
            return price < swing_lows[-2][1]
        return False

    # ── CHoCH: Change of Character ──

    def _detect_choch(self, candles: list, trend: str) -> bool:
        swing_highs, swing_lows = self._find_swings(candles)
        price = candles[-1]["c"]

        if trend == "BULLISH" and len(swing_lows) >= 1:
            return price < swing_lows[-1][1]
        elif trend == "BEARISH" and len(swing_highs) >= 1:
            return price > swing_highs[-1][1]
        return False

    # ── Order Block ──

    def _detect_order_block(self, candles: list) -> bool:
        if len(candles) < 5:
            return False
        for i in range(len(candles) - 4, max(len(candles) - 20, 0), -1):
            curr = candles[i]
            nxt = candles[i + 1]
            body_curr = abs(curr["c"] - curr["o"])
            body_nxt = abs(nxt["c"] - nxt["o"])
            if body_nxt > body_curr * 2:
                bearish_ob = curr["c"] < curr["o"] and nxt["c"] > nxt["o"]
                bullish_ob = curr["c"] > curr["o"] and nxt["c"] < nxt["o"]
                if bearish_ob or bullish_ob:
                    price = candles[-1]["c"]
                    ob_top = max(curr["o"], curr["c"])
                    ob_bot = min(curr["o"], curr["c"])
                    if ob_bot <= price <= ob_top:
                        return True
        return False

    # ── Fair Value Gap ──

    def _detect_fvg(self, candles: list) -> bool:
        for i in range(len(candles) - 3, max(len(candles) - 15, 0), -1):
            c1, c2, c3 = candles[i], candles[i + 1], candles[i + 2]
            bull_fvg = c1["h"] < c3["l"]
            bear_fvg = c1["l"] > c3["h"]
            if bull_fvg or bear_fvg:
                price = candles[-1]["c"]
                if bull_fvg and price <= c3["l"]:
                    return True
                if bear_fvg and price >= c3["h"]:
                    return True
        return False

    # ── Liquidity Sweep ──

    def _detect_sweep(self, candles: list) -> bool:
        if len(candles) < 10:
            return False
        recent = candles[-5:]
        prev_lows = [c["l"] for c in candles[-20:-5]]
        prev_highs = [c["h"] for c in candles[-20:-5]]
        if not prev_lows:
            return False
        prev_low = min(prev_lows)
        prev_high = max(prev_highs)
        for c in recent:
            if c["l"] < prev_low and c["c"] > prev_low:
                return True
            if c["h"] > prev_high and c["c"] < prev_high:
                return True
        return False

    # ── Displacement ──

    def _detect_displacement(self, candles: list) -> bool:
        if len(candles) < 3:
            return False
        for i in range(len(candles) - 3, max(len(candles) - 10, 0), -1):
            c = candles[i]
            body = abs(c["c"] - c["o"])
            wick = c["h"] - c["l"]
            if wick > 0 and body / wick > 0.7 and body > 0:
                avg_body = sum(abs(candles[j]["c"] - candles[j]["o"]) for j in range(max(0, i-5), i)) / 5
                if avg_body > 0 and body > avg_body * 2:
                    return True
        return False

    # ── Comment Builder ──

    def _build_comment(self, zone, structure, bos, choch, ob, fvg, sweep) -> str:
        z = zone["premium"] if zone["premium"] != "—" else zone["discount"]
        parts = [
            z,
            structure["trend"],
            f"BOS {'✓' if bos else '—'}",
            f"CHoCH {'✓' if choch else '—'}",
            f"OB {'✓' if ob else '—'}",
            f"FVG {'✓' if fvg else '—'}",
            f"SWEEP {'✓' if sweep else '—'}",
        ]
        return " | ".join(parts)
