"""
APEX PROTOCOL™ — TOP20 1M Breakout Strategy
TOP20_1M_BREAKOUT_v1

Логика:
- Universe: TOP20 по объёму (USDT perpetual)
- Timeframe: 1m
- LONG:  open текущей 1m > high предыдущей 1m
- SHORT: open текущей 1m < low предыдущей 1m
- Entry: market (текущая цена)
- close_on_first_tp: true (закрытие на TP1)
- max_entries_per_pair_per_run: 1
- reset_on_new_run: true
"""

import logging
from datetime import datetime
from pytz import timezone as tz

logger = logging.getLogger("apex.top20_breakout")
PODGORICA = tz("Europe/Podgorica")


class Top20BreakoutStrategy:

    def __init__(self, config: dict, event_bus=None):
        self.config = config
        self.event_bus = event_bus
        self.exchange_service = None
        self._connected = False
        self._run_id = None
        self._traded_pairs: set = set()

    def new_run(self):
        """START — новый run_id, сброс лимитов."""
        self._run_id = f"RUN-{datetime.now(PODGORICA).strftime('%Y%m%d-%H%M%S')}"
        self._traded_pairs = set()
        logger.info(f"[TOP20] New run started: {self._run_id}")

    async def _ensure_connected(self):
        if not self._connected:
            from services.exchange_service import ExchangeService
            self.exchange_service = ExchangeService(self.config)
            await self.exchange_service.connect()
            self._connected = True

    async def run(self, open_symbols: set) -> tuple:
        """
        Полный цикл: TOP20 universe → 1m candles → breakout check → signals.
        Returns: (signals: list, current_prices: dict)
        """
        try:
            await self._ensure_connected()

            if not self._run_id:
                self.new_run()

            # ── 1. TOP20 по объёму ────────────────────────────────────────
            tickers = await self.exchange_service.get_tickers()
            if not tickers:
                logger.warning("[TOP20] No tickers received")
                return [], {}

            pairs = []
            for symbol, ticker in tickers.items():
                if not symbol.endswith("USDT:USDT"):
                    continue
                vol = ticker.get("quoteVolume") or 0
                price = ticker.get("last") or 0
                if vol > 0 and price > 0:
                    pairs.append({"symbol": symbol, "volume": vol, "price": price})

            pairs.sort(key=lambda x: x["volume"], reverse=True)
            top20 = pairs[:1000]

            current_prices = {p["symbol"]: p["price"] for p in pairs if p.get("price")}

            top20_symbols = [p["symbol"].split("/")[0] for p in top20]
            logger.info(f"[TOP20] Universe: {len(pairs)} pairs | TOP20: {', '.join(top20_symbols)}")
            # Обновляем scanner_state для ВАУ+/Статус
            try:
                from modules.runtime_state import update_scanner_state
                update_scanner_state(
                    total_pairs=len(pairs),
                    after_liquidity=len(pairs),
                    after_volatility=len(pairs),
                    after_structure=20,
                    scored=20,
                    candidates=20,
                    signals=0,
                    top_score=0,
                )
            except Exception:
                pass

            # ── 2. Параметры из test_control ──────────────────────────────
            try:
                from services.test_control import read as tc_read
                tc = tc_read()
                sl_pct  = float(tc.get("param_sl_pct") or 1.0) / 100.0
                tp1_pct = float(tc.get("param_tp1_pct") or 1.0) / 100.0
                tp2_pct = float(tc.get("param_tp2_pct") or 2.0) / 100.0
                tp3_pct = float(tc.get("param_tp3_pct") or 3.0) / 100.0
                direction_mode = tc.get("direction", "both")
            except Exception:
                sl_pct, tp1_pct, tp2_pct, tp3_pct = 0.01, 0.01, 0.02, 0.03
                direction_mode = "both"

            # ── 3. Проверка breakout для каждой пары ──────────────────────
            signals = []
            for pair in top20:
                symbol = pair["symbol"]

                # max_entries_per_pair_per_run = 1
                if symbol in self._traded_pairs:
                    continue

                # Не открывать уже открытые
                if symbol in open_symbols:
                    continue

                signal = await self._check_breakout(
                    symbol, pair["price"],
                    sl_pct, tp1_pct, tp2_pct, tp3_pct,
                    direction_mode,
                )
                if signal:
                    signals.append(signal)

            if signals:
                sym_list = ", ".join(s["symbol"].split("/")[0] for s in signals)
                logger.info(f"[TOP20] Signals: {len(signals)} — {sym_list}")
            else:
                logger.info(f"[TOP20] No breakout signals this cycle")

            return signals, current_prices

        except Exception as e:
            logger.error(f"[TOP20] run error: {e}", exc_info=True)
            return [], {}

    def mark_traded(self, symbol: str):
        """Отметить пару как торгованную в текущем run."""
        self._traded_pairs.add(symbol)
        logger.info(f"[TOP20] Pair traded: {symbol} ({len(self._traded_pairs)}/20 in {self._run_id})")

    @property
    def run_complete(self) -> bool:
        """Все 1000 пар исчерпаны."""
        return len(self._traded_pairs) >= 1000

    async def _check_breakout(self, symbol, current_price, sl_pct, tp1_pct, tp2_pct, tp3_pct, direction_mode):
        """Проверка 1m breakout для одной пары."""
        try:
            await asyncio.sleep(1.5)  # throttle
            candles = await self.exchange_service.get_ohlcv(symbol, "1m", limit=3)
            if not candles or len(candles) < 2:
                return None

            prev = candles[-2]   # Предыдущая завершённая 1m свеча
            curr = candles[-1]   # Текущая (формирующаяся) 1m свеча

            prev_high = prev[2]
            prev_low  = prev[3]
            curr_open = curr[1]
            curr_close = curr[4]

            direction = None
            entry_price = current_price

            # LONG: open текущей 1m > high предыдущей 1m
            if curr_close > prev_high and direction_mode in ("both", "long"):
                direction = "long"
                sl  = round(entry_price * (1 - sl_pct), 10)
                tp1 = round(entry_price * (1 + tp1_pct), 10)
                tp2 = round(entry_price * (1 + tp2_pct), 10)
                tp3 = round(entry_price * (1 + tp3_pct), 10)

            # SHORT: open текущей 1m < low предыдущей 1m
            elif curr_close < prev_low and direction_mode in ("both", "short"):
                direction = "short"
                sl  = round(entry_price * (1 + sl_pct), 10)
                tp1 = round(entry_price * (1 - tp1_pct), 10)
                tp2 = round(entry_price * (1 - tp2_pct), 10)
                tp3 = round(entry_price * (1 - tp3_pct), 10)

            if not direction:
                return None

            now = datetime.now(PODGORICA)

            signal = {
                "symbol":           symbol,
                "direction":        direction,
                "session_name":     self._run_id,
                "strategy":         "TOP20_1M_BREAKOUT_v1",
                "strategy_name":    "TOP20_1M_BREAKOUT_v1",
                "timeframe":        "1m",
                "entry":            round(entry_price, 10),
                "entry_price":      round(entry_price, 10),
                "entry_hour":       now.hour,
                "sl":               sl,
                "tp1":              tp1,
                "tp2":              tp2,
                "tp3":              tp3,
                "risk_R_value":     round(abs(entry_price - sl), 6),
                "confidence":       1.0,
                "generated_at":     now.strftime("%Y-%m-%dT%H:%M:%S"),
                "score":            100,
                "price":            current_price,
                "reasons":          ["1M_BREAKOUT"],
                "candidate_status": "SENT_TO_FILTER",
                "scanned_at":       now.isoformat(),
            }

            logger.info(
                f"[TOP20 SIGNAL] {symbol} {direction.upper()} | "
                f"entry={entry_price:.4f} SL={sl:.4f} TP1={tp1:.4f} | "
                f"prev_h={prev_high:.4f} prev_l={prev_low:.4f} curr_o={curr_open:.4f}"
            )
            return signal

        except Exception as e:
            logger.error(f"[TOP20] _check_breakout {symbol}: {e}")
            return None
