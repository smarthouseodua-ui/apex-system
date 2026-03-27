"""
APEX PROTOCOL™ — Scanner
Сканирует рынок, находит кандидатов. Пишет в SKL01_T01_scanner_log.
"""

import sys
import logging
from datetime import datetime
from core.event_bus import EventBus
from services.exchange_service import ExchangeService
from storage.db.repository import Repository

sys.path.insert(0, "/root/data-core")
from app import write_scanner_results_batch
from modules.runtime_state import scanner_state, update_scanner_state

logger = logging.getLogger("apex.scanner")


class Scanner:

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.exchange_service = ExchangeService(config)
        self.repo = Repository()
        self._connected = False

    async def _ensure_connected(self):
        if not self._connected:
            await self.exchange_service.connect()
            self._connected = True

    async def scan(self) -> list:
        try:
            await self._ensure_connected()
            cycle_ts = datetime.now().isoformat()

            # Stage 1: Universe
            pairs = await self._fetch_universe(cycle_ts)
            scanner_state["total_pairs"] = len(pairs)
            logger.info(f"[SCANNER] Universe: {len(pairs)}")

            # Stage 2: Liquidity
            pairs = self._filter_liquidity(pairs)
            scanner_state["after_liquidity"] = len(pairs)
            logger.info(f"[SCANNER] Liquidity: {len(pairs)}")

            # Stage 3: Volatility
            pairs = self._filter_volatility(pairs)
            scanner_state["after_volatility"] = len(pairs)
            logger.info(f"[SCANNER] Volatility: {len(pairs)}")

            # Stage 4: Structure
            pairs = await self._filter_structure(pairs)
            scanner_state["after_structure"] = len(pairs)
            logger.info(f"[SCANNER] Structure: {len(pairs)}")

            # Stage 4.5: Early garbage filter
            pairs = [p for p in pairs if p.get("volume", 0) > 0 and p.get("price", 0) > 0]

            # Stage 5: Score
            pairs = self._apply_score(pairs)
            scanner_state["scored"] = len(pairs)
            scanner_state["top_score"] = pairs[0]["score"] if pairs else 0
            logger.info(f"[SCANNER] Top score: {pairs[0]['score'] if pairs else 0}")

            # Stage 6: Reasons/Tags
            pairs = self._apply_reasons(pairs)
            logger.info(f"[SCANNER] Reasons ready: {len(pairs)}")

            # Stage 7: Statuses
            pairs = self._apply_statuses(pairs)
            logger.info(f"[SCANNER] Statuses ready: {len(pairs)}")

            # Stage 8: Scanner-ready
            logger.info(f"[SCANNER] Scanner-ready: {len(pairs)}")

            for c in pairs:
                self.repo.log_scanner(c)

            # ── DATA CORE: batch write ───────────────────────────
            try:
                write_scanner_results_batch(pairs)
                logger.info(f"[SCANNER] DATA CORE: {len(pairs)} pairs written")
            except Exception as e:
                logger.error(f"[SCANNER] DATA CORE write failed: {e}")

            # Минимальный тренд-фильтр: отклонение от EMA >= 0.2%
            before_ema = len(pairs)
            pairs = [
                p for p in pairs
                if abs((p.get("price", 0) - p.get("ema", 0)) / max(p.get("ema", 1), 1e-9)) > 0.002
            ]
            after_ema = len(pairs)

            sent_to_filter_raw = len([
                p for p in pairs
                if p.get("candidate_status") == "SENT_TO_FILTER"
            ])

            filtered = [
                p for p in pairs
                if p.get("candidate_status") == "SENT_TO_FILTER"
                and p.get("score", 0) >= 65
            ]
            scanner_state["candidates"] = len(filtered)
            scanner_state["signals"] = len(filtered)

            # Determine reject reason
            reject_reason = ""
            if len(filtered) == 0:
                top = scanner_state["top_score"]
                if scanner_state["after_structure"] == 0:
                    reject_reason = "нет пар после structure фильтра"
                elif after_ema < before_ema and after_ema == 0:
                    reject_reason = "все отброшены EMA фильтром (< 0.2%)"
                elif sent_to_filter_raw == 0:
                    reject_reason = f"нет SENT_TO_FILTER (score < 60, top={top})"
                elif top < 65:
                    reject_reason = f"score ниже порога (top={top}, нужно 65)"
                else:
                    reject_reason = "финальный фильтр"

            update_scanner_state(
                total_pairs=scanner_state["total_pairs"],
                after_liquidity=scanner_state["after_liquidity"],
                after_volatility=scanner_state["after_volatility"],
                after_structure=scanner_state["after_structure"],
                scored=scanner_state["scored"],
                candidates=len(filtered),
                signals=len(filtered),
                top_score=scanner_state["top_score"],
                after_ema_filter=after_ema,
                sent_to_filter_raw=sent_to_filter_raw,
                last_reject_reason=reject_reason,
            )
            logger.info(f"[SCANNER] Sent to filter: {len(filtered)}")
            for f in filtered:
                print(f"[SIGNAL] {f.get('symbol')} score={f.get('score')}")

            if not filtered:
                logger.info("[SCANNER] Pipeline transfer skipped: 0 candidates")
                return pairs

            await self.event_bus.publish("scanner.done", {"candidates": filtered})
            logger.info(f"[SCANNER] Pipeline transfer OK: {len(filtered)} candidates sent")
            return pairs

        except Exception as e:
            logger.error(f"Scanner error: {e}", exc_info=True)
            return []

    # ── Stage 1: Universe ────────────────────────────────────────────────
    async def _fetch_universe(self, cycle_ts: str) -> list:
        """Получить все пары с биржи. Базовая валидация: price > 0, USDT quote."""
        cfg = self.config.get("scanner", {})
        quote_currency = cfg.get("quote_currency", "USDT")
        blacklist = cfg.get("blacklist", [])

        tickers = await self.exchange_service.get_tickers()
        pairs = []
        for symbol, ticker in tickers.items():
            try:
                if not symbol.endswith(f":{quote_currency}"):
                    continue
                if symbol in blacklist:
                    continue
                price = ticker.get("last", 0)
                volume = ticker.get("quoteVolume", 0)
                high = ticker.get("high", price)
                low = ticker.get("low", price)
                if price and price > 0:
                    volatility = round(((high - low) / price) * 100, 4)
                    pairs.append({
                        "symbol": symbol,
                        "price": price,
                        "volume": volume,
                        "volatility": volatility,
                        "high": high,
                        "low": low,
                        "scanned_at": cycle_ts
                    })
            except Exception:
                continue
        return pairs

    # ── Stage 2: Liquidity ───────────────────────────────────────────────
    def _filter_liquidity(self, pairs: list) -> list:
        """Фильтр ликвидности: volume >= min_volume, данные валидны."""
        cfg = self.config.get("scanner", {})
        min_volume = cfg.get("min_volume", 50_000_000)

        result = [
            p for p in pairs
            if p.get("volume") is not None
            and p.get("volume", 0) >= min_volume
        ]
        result.sort(key=lambda x: x.get("volume", 0), reverse=True)
        return result

    # ── Stage 3: Volatility ──────────────────────────────────────────────
    def _filter_volatility(self, pairs: list) -> list:
        """Фильтр волатильности: volatility в допустимом диапазоне."""
        cfg = self.config.get("scanner", {})
        min_volatility = cfg.get("min_volatility", 0.5)
        max_volatility = cfg.get("max_volatility", 15.0)

        return [
            p for p in pairs
            if min_volatility <= p.get("volatility", 0) <= max_volatility
        ]

    # ── Stage 4: Structure ───────────────────────────────────────────────
    async def _filter_structure(self, pairs: list) -> list:
        """Фильтр структуры: цена vs EMA-20 на 15m свечах.
        Пропускает пару только если цена отклоняется от EMA >= 0.1%
        (есть выраженный тренд, а не боковик).
        """
        cfg = self.config.get("scanner", {})
        max_candidates = cfg.get("max_candidates", 20)
        ema_period = cfg.get("structure_ema_period", 20)
        ema_min_deviation = cfg.get("structure_ema_min_deviation", 0.1)

        result = []
        for p in pairs:
            try:
                ohlcv = await self.exchange_service.get_ohlcv(
                    p["symbol"], timeframe="15m", limit=ema_period + 5
                )
                if not ohlcv or len(ohlcv) < ema_period:
                    continue

                closes = [c[4] for c in ohlcv if c[4]]
                if len(closes) < ema_period:
                    continue

                ema = self._calc_ema(closes, ema_period)
                price = p["price"]
                deviation = abs(price - ema) / ema * 100

                if deviation < ema_min_deviation:
                    continue

                p["ema"] = round(ema, 6)
                p["structure"] = "bullish" if price > ema else "bearish"
                result.append(p)
            except Exception:
                continue

        result.sort(key=lambda x: x.get("volume", 0), reverse=True)
        return result[:max_candidates]

    # ── Stage 5: Score ─────────────────────────────────────────────────
    def _apply_score(self, pairs: list) -> list:
        """Расчёт score (0–100) — ребалансированная формула."""
        if not pairs:
            return pairs

        max_volume = max(p.get("volume", 0) for p in pairs)
        cfg = self.config.get("scanner", {})
        max_volatility = cfg.get("max_volatility", 15.0)

        for p in pairs:
            volume = p.get("volume", 0)
            volatility = p.get("volatility", 0)
            price = p.get("price", 0)
            ema = p.get("ema", price)
            high = p.get("high", price)
            low = p.get("low", price)

            # 0. base_score (15): базовый уровень для всех пар прошедших structure
            base_score = 15

            # 1. liquidity_score (0–25): нормализация относительно макс. в списке
            liquidity_score = min(25, (volume / max_volume) * 25) if max_volume > 0 else 0

            # 2. trend_score (0–25): EMA deviation * 300
            ema_safe = max(ema, 1e-9)
            trend_score = min(25, abs(price - ema) / ema_safe * 300)

            # 3. momentum_score (0–20): направленное движение
            momentum = (price - low) / max(high - low, 1e-9) if high != low else 0.5
            momentum_score = min(20, momentum * 700 * 0.02857)  # ~20 max

            # 4. volatility_score (0–20): нормализованная волатильность
            volatility_norm = volatility / max_volatility if max_volatility > 0 else 0
            volatility_score = min(20, volatility_norm * 1500 * 0.01333)  # ~20 max

            # 5. range_score (0–15): range expansion
            avg_range = (high + low) / 2 if (high + low) > 0 else 1
            range_expansion = (high - low) / max(avg_range, 1e-9) * 100
            range_score = min(15, max(0, (range_expansion - 1) * 10))

            score = base_score + liquidity_score + trend_score + momentum_score + volatility_score + range_score

            # Ограничение итогового score
            score = max(0, min(100, int(score)))
            p["score"] = score

        pairs.sort(key=lambda x: x.get("score", 0), reverse=True)
        return pairs

    # ── Stage 6: Reasons/Tags ──────────────────────────────────────────
    def _apply_reasons(self, pairs: list) -> list:
        """Присвоить стандартизированные tags каждой паре."""
        if not pairs:
            return pairs

        cfg = self.config.get("scanner", {})
        min_volume = cfg.get("min_volume", 50_000_000)
        min_volatility = cfg.get("min_volatility", 0.5)
        max_volatility = cfg.get("max_volatility", 15.0)
        max_volume = max(p.get("volume", 0) for p in pairs)

        for p in pairs:
            reasons = []
            volume = p.get("volume", 0)
            volatility = p.get("volatility", 0)
            price = p.get("price", 0)
            ema = p.get("ema")
            score = p.get("score", 0)

            if max_volume > 0 and volume >= max_volume * 0.8:
                reasons.append("VolSpike")

            if min_volatility <= volatility <= max_volatility:
                reasons.append("ATR_OK")

            if ema is not None:
                reasons.append("EMAAlign")
                if price > ema:
                    reasons.append("Bullish")
                elif price < ema:
                    reasons.append("Bearish")

            if volume >= min_volume * 2:
                reasons.append("HighLiquidity")

            if score >= 70:
                reasons.append("HighScore")

            p["reasons"] = reasons

        return pairs

    # ── Stage 7: Statuses ──────────────────────────────────────────────
    def _apply_statuses(self, pairs: list) -> list:
        """Присвоить candidate_status каждой паре на основе score."""
        for p in pairs:
            status = "SCANNED"
            score = p.get("score", 0)

            if score >= 65:
                status = "SENT_TO_FILTER"
            elif score >= 45:
                status = "PASSED"
            elif score >= 30:
                status = "WATCH"
            else:
                status = "REJECTED"

            p["candidate_status"] = status

        return pairs

    @staticmethod
    def _calc_ema(closes: list, period: int) -> float:
        """Рассчитать EMA по списку closes."""
        multiplier = 2 / (period + 1)
        ema = closes[0]
        for close in closes[1:]:
            ema = (close - ema) * multiplier + ema
        return ema
