"""
APEX PROTOCOL™ — SMC Analyzer v2.0
Расширенный анализ SMC для APEX_AGS_ANALYTICS.
"""

import logging
import numpy as np
from datetime import datetime, timezone

logger = logging.getLogger("apex.smc_analyzer")


class SMCAnalyzer:

    def __init__(self, config: dict):
        self.config = config

    async def analyze_and_update(self, symbols: list, timeframe: str = "15m"):
        try:
            from modules.scanner import Scanner
            from storage.db.repository import Repository
            from core.event_bus import EventBus
            scanner = Scanner(self.config, EventBus())
            await scanner._ensure_connected()
            repo = Repository()
            for symbol in symbols:
                try:
                    result = await self._analyze_symbol(scanner, symbol, timeframe)
                    if result:
                        repo.update_smc_fields(symbol, result)
                        logger.info(
                            f"[SMC] {symbol} | phase={result["market_phase"]} | "
                            f"BOS={result["bos_present"]} CHoCH={result["choch_present"]} | "
                            f"discount={result["entry_in_discount"]}"
                        )
                except Exception as e:
                    logger.warning(f"[SMC] {symbol} ошибка: {e}")
        except Exception as e:
            logger.error(f"SMCAnalyzer error: {e}", exc_info=True)

    async def _analyze_symbol(self, scanner, symbol: str, timeframe: str) -> dict:
        candles = await scanner.exchange_service.exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        if not candles or len(candles) < 20:
            return None

        opens  = np.array([c[1] for c in candles])
        highs  = np.array([c[2] for c in candles])
        lows   = np.array([c[3] for c in candles])
        closes = np.array([c[4] for c in candles])
        volumes= np.array([c[5] for c in candles])

        now_utc = datetime.now(timezone.utc)
        current_price = float(closes[-1])
        current_volume = float(volumes[-1])

        # ── ORB ──────────────────────────────────────────────────────────
        orb_high = float(np.max(highs[:4]))
        orb_low  = float(np.min(lows[:4]))
        orb_mid  = round((orb_high + orb_low) / 2, 8)
        orb_size = orb_high - orb_low

        # ── Dealing Range (последние 20 свечей) ───────────────────────────
        dealing_high = float(np.max(highs[-20:]))
        dealing_low  = float(np.min(lows[-20:]))
        dealing_mid  = round((dealing_high + dealing_low) / 2, 8)
        price_location = round((current_price - dealing_low) / (dealing_high - dealing_low), 4) if (dealing_high - dealing_low) > 0 else 0.5

        # ── Premium / Discount / Equilibrium ─────────────────────────────
        entry_in_discount = 1 if current_price < orb_mid else 0
        if current_price > orb_mid * 1.002:
            premium_zone_status   = "premium"
            discount_zone_status  = "none"
            equilibrium_zone_status = "above_eq"
        elif current_price < orb_mid * 0.998:
            premium_zone_status   = "none"
            discount_zone_status  = "discount"
            equilibrium_zone_status = "below_eq"
        else:
            premium_zone_status   = "none"
            discount_zone_status  = "none"
            equilibrium_zone_status = "at_eq"

        # ── ATR ───────────────────────────────────────────────────────────
        atr_values = highs[-14:] - lows[-14:]
        atr_value  = float(np.mean(atr_values))
        atr_percent = round(atr_value / current_price * 100, 4) if current_price > 0 else 0.0
        if atr_percent > 3.0:
            volatility_state = "high"
        elif atr_percent > 1.0:
            volatility_state = "medium"
        else:
            volatility_state = "low"

        # ── Volume ────────────────────────────────────────────────────────
        avg_volume = float(np.mean(volumes[-20:]))
        volume_ratio = round(current_volume / avg_volume, 4) if avg_volume > 0 else 1.0
        if volume_ratio > 1.5:
            volume_state = "high"
        elif volume_ratio > 0.7:
            volume_state = "normal"
        else:
            volume_state = "low"

        # ── Trend ─────────────────────────────────────────────────────────
        sma20 = float(np.mean(closes[-20:]))
        sma50 = float(np.mean(closes[-50:])) if len(closes) >= 50 else sma20
        if sma20 > sma50 * 1.01:
            market_phase = "BULL"
            trend_state  = "bullish"
            internal_structure_state = "bullish"
            external_structure_state = "bullish"
        elif sma20 < sma50 * 0.99:
            market_phase = "BEAR"
            trend_state  = "bearish"
            internal_structure_state = "bearish"
            external_structure_state = "bearish"
        else:
            market_phase = "RANGE"
            trend_state  = "ranging"
            internal_structure_state = "ranging"
            external_structure_state = "ranging"

        # ── BOS ───────────────────────────────────────────────────────────
        prev_high = float(np.max(highs[-20:-1]))
        prev_low  = float(np.min(lows[-20:-1]))
        bos_bullish = current_price > prev_high
        bos_bearish = current_price < prev_low
        bos_present = 1 if (bos_bullish or bos_bearish) else 0
        bos_direction = "bullish" if bos_bullish else ("bearish" if bos_bearish else "none")
        structure_break_strength = round(abs(current_price - prev_high) / prev_high * 100, 4) if bos_bullish else (
            round(abs(current_price - prev_low) / prev_low * 100, 4) if bos_bearish else 0.0
        )

        # ── CHoCH ─────────────────────────────────────────────────────────
        last3_up   = closes[-1] > closes[-4]
        last3_down = closes[-1] < closes[-4]
        trend_up   = closes[-10] < closes[-5]
        trend_down = closes[-10] > closes[-5]
        choch_present = 1 if ((trend_up and last3_down) or (trend_down and last3_up)) else 0
        choch_direction = "bearish" if (trend_up and last3_down) else ("bullish" if (trend_down and last3_up) else "none")
        market_shift_detected = 1 if (bos_present and choch_present) else 0

        # ── Equal Highs / Lows ────────────────────────────────────────────
        tolerance = 0.001
        recent_highs = highs[-10:]
        recent_lows  = lows[-10:]
        equal_highs_present = 1 if float(np.max(recent_highs) - np.min(recent_highs)) / float(np.mean(recent_highs)) < tolerance else 0
        equal_lows_present  = 1 if float(np.max(recent_lows)  - np.min(recent_lows))  / float(np.mean(recent_lows))  < tolerance else 0

        # ── Liquidity ─────────────────────────────────────────────────────
        buy_side_liq  = float(np.max(highs[-10:]))
        sell_side_liq = float(np.min(lows[-10:]))
        dist_to_buy  = abs(current_price - buy_side_liq) / current_price * 100
        dist_to_sell = abs(current_price - sell_side_liq) / current_price * 100
        if dist_to_buy < dist_to_sell:
            liquidity_pool_present = 1
            liquidity_side = "buyside"
            liquidity_distance_pct = round(dist_to_buy, 4)
        else:
            liquidity_pool_present = 1
            liquidity_side = "sellside"
            liquidity_distance_pct = round(dist_to_sell, 4)

        # ── Sweep ─────────────────────────────────────────────────────────
        prev_range_high = float(np.max(highs[-5:-1]))
        prev_range_low  = float(np.min(lows[-5:-1]))
        last_high = float(highs[-1])
        last_low  = float(lows[-1])
        last_close = float(closes[-1])
        sweep_bullish = last_low < prev_range_low and last_close > prev_range_low
        sweep_bearish = last_high > prev_range_high and last_close < prev_range_high
        sweep_present = 1 if (sweep_bullish or sweep_bearish) else 0
        sweep_side = "sellside" if sweep_bullish else ("buyside" if sweep_bearish else "none")
        sweep_strength = round(abs(last_low - prev_range_low) / prev_range_low * 100, 4) if sweep_bullish else (
            round(abs(last_high - prev_range_high) / prev_range_high * 100, 4) if sweep_bearish else 0.0
        )
        liquidity_taken_flag = sweep_present

        # ── Order Block ───────────────────────────────────────────────────
        entry_near_ob = 0
        ob_type = "none"
        for i in range(-5, -1):
            body = abs(closes[i] - closes[i-1])
            avg_body = np.mean(np.abs(np.diff(closes[-20:])))
            if body > avg_body * 1.5:
                ob_zone_high = max(closes[i], closes[i-1])
                ob_zone_low  = min(closes[i], closes[i-1])
                if ob_zone_low <= current_price <= ob_zone_high * 1.005:
                    entry_near_ob = 1
                    ob_type = "bullish" if closes[i] > closes[i-1] else "bearish"
                    break

        # ── FVG ───────────────────────────────────────────────────────────
        entry_near_fvg = 0
        fvg_type = "none"
        for i in range(1, len(candles) - 1):
            fvg_up   = lows[i+1] > highs[i-1]
            fvg_down = highs[i+1] < lows[i-1]
            if fvg_up:
                fvg_low_val  = float(highs[i-1])
                fvg_high_val = float(lows[i+1])
                if fvg_low_val <= current_price <= fvg_high_val:
                    entry_near_fvg = 1
                    fvg_type = "bullish"
                    break
            if fvg_down:
                fvg_high_val = float(lows[i-1])
                fvg_low_val  = float(highs[i+1])
                if fvg_low_val <= current_price <= fvg_high_val:
                    entry_near_fvg = 1
                    fvg_type = "bearish"
                    break

        # ── Displacement ──────────────────────────────────────────────────
        last3_range = float(np.max(highs[-3:]) - np.min(lows[-3:]))
        avg_range   = float(np.mean(highs[-20:] - lows[-20:]))
        displacement_present = 1 if last3_range > avg_range * 1.5 else 0
        displacement_direction = trend_state if displacement_present else "none"
        displacement_strength  = round(last3_range / avg_range * 100, 2) if avg_range > 0 else 0.0
        impulse_candle_count = int(np.sum(np.abs(np.diff(closes[-5:])) > np.mean(np.abs(np.diff(closes[-20:])))))

        # ── Rejection ────────────────────────────────────────────────────
        last_candle_body = abs(float(closes[-1]) - float(opens[-1]))
        last_candle_range = float(highs[-1]) - float(lows[-1])
        rejection_present = 1 if (last_candle_range > 0 and last_candle_body / last_candle_range < 0.3) else 0
        reaction_strength = round((1 - last_candle_body / last_candle_range) * 100, 2) if last_candle_range > 0 else 0.0

        # ── Scores ────────────────────────────────────────────────────────
        structure_score  = round(min(100, (bos_present * 30 + choch_present * 20 + market_shift_detected * 50)), 1)
        liquidity_score  = round(min(100, (sweep_present * 40 + liquidity_pool_present * 30 + equal_highs_present * 15 + equal_lows_present * 15)), 1)
        zone_score       = round(min(100, (entry_near_ob * 40 + entry_near_fvg * 40 + (1 - abs(price_location - 0.5) * 2) * 20)), 1)
        momentum_score   = round(min(100, (displacement_present * 40 + rejection_present * 30 + min(volume_ratio, 3) / 3 * 30)), 1)
        smc_alignment_score = round((structure_score + liquidity_score + zone_score + momentum_score) / 4, 2)

        if smc_alignment_score >= 75:
            setup_quality = "A"
        elif smc_alignment_score >= 60:
            setup_quality = "B"
        elif smc_alignment_score >= 45:
            setup_quality = "C"
        else:
            setup_quality = "D"

        setup_direction = trend_state
        setup_valid_flag = 1 if (bos_present and (entry_near_ob or entry_near_fvg) and smc_alignment_score >= 50) else 0
        invalidation_reason = "none" if setup_valid_flag else (
            "no_bos" if not bos_present else "no_zone" if not (entry_near_ob or entry_near_fvg) else "low_score"
        )

        analyst_comment_short = f"{market_phase} | BOS={bos_present} CHoCH={choch_present} | OB={entry_near_ob} FVG={entry_near_fvg} | Score={smc_alignment_score}"

        # ── Session context ───────────────────────────────────────────────
        h = now_utc.hour
        session_name_calc = "ASIA" if 0 <= h < 8 else "LONDON" if 8 <= h < 13 else "NEW_YORK" if 13 <= h < 21 else "OFF"
        session_group_calc = "ASIA" if session_name_calc == "ASIA" else "EUROPE" if session_name_calc == "LONDON" else "AMERICA" if session_name_calc == "NEW_YORK" else "OFF"
        day_of_week = now_utc.strftime("%A")
        weekend_flag = 1 if now_utc.weekday() >= 5 else 0

        return {
            # базовые
            "market_phase":              market_phase,
            "bos_present":               bos_present,
            "choch_present":             choch_present,
            "entry_in_discount":         entry_in_discount,
            "entry_near_ob":             entry_near_ob,
            "entry_near_fvg":            entry_near_fvg,
            "orb_high":                  round(orb_high, 8),
            "orb_low":                   round(orb_low, 8),
            "orb_mid":                   round(orb_mid, 8),
            # расширенные для AGS
            "exchange":                  "Bybit",
            "market_type":               "FUTURES",
            "timeframe":                 timeframe,
            "timezone":                  "UTC",
            "session_group":             session_group_calc,
            "day_of_week":               day_of_week,
            "hour_bucket":               h,
            "weekend_flag":              weekend_flag,
            "pre_session_flag":          0,
            "session_open_flag":         1,
            "overlap_flag":              0,
            "current_price":             round(current_price, 8),
            "trend_state":               trend_state,
            "volatility_state":          volatility_state,
            "atr_value":                 round(atr_value, 8),
            "atr_percent":               atr_percent,
            "volume_state":              volume_state,
            "volume_ratio":              volume_ratio,
            "bos_direction":             bos_direction,
            "choch_direction":           choch_direction,
            "market_shift_detected":     market_shift_detected,
            "structure_break_strength":  structure_break_strength,
            "internal_structure_state":  internal_structure_state,
            "external_structure_state":  external_structure_state,
            "premium_zone_status":       premium_zone_status,
            "discount_zone_status":      discount_zone_status,
            "equilibrium_zone_status":   equilibrium_zone_status,
            "dealing_range_high":        round(dealing_high, 8),
            "dealing_range_low":         round(dealing_low, 8),
            "dealing_range_mid":         round(dealing_mid, 8),
            "price_location_in_range":   price_location,
            "liquidity_pool_present":    liquidity_pool_present,
            "liquidity_side":            liquidity_side,
            "equal_highs_present":       equal_highs_present,
            "equal_lows_present":        equal_lows_present,
            "liquidity_distance_pct":    liquidity_distance_pct,
            "sweep_present":             sweep_present,
            "sweep_side":                sweep_side,
            "sweep_strength":            sweep_strength,
            "liquidity_taken_flag":      liquidity_taken_flag,
            "order_block_type":          ob_type,
            "order_block_tf":            timeframe,
            "order_block_freshness":     "fresh" if entry_near_ob else "none",
            "fvg_type":                  fvg_type,
            "fvg_tf":                    timeframe,
            "displacement_present":      displacement_present,
            "displacement_direction":    displacement_direction,
            "displacement_strength":     displacement_strength,
            "impulse_candle_count":      impulse_candle_count,
            "rejection_present":         rejection_present,
            "reaction_strength":         reaction_strength,
            "smc_alignment_score":       smc_alignment_score,
            "liquidity_score":           liquidity_score,
            "structure_score":           structure_score,
            "zone_score":                zone_score,
            "momentum_score":            momentum_score,
            "setup_quality":             setup_quality,
            "setup_direction":           setup_direction,
            "setup_valid_flag":          setup_valid_flag,
            "invalidation_reason":       invalidation_reason,
            "analyst_comment_short":     analyst_comment_short,
        }
