"""
APEX PROTOCOL™ — APEX_SCENARIO_LAB
SC_002_SECOND_CANDLE — вход по второй свече.

Логика:
  1. Берём 2 последние завершённые 1m-свечи по символу
  2. Первая свеча: определяет направление (close > open → bullish, close < open → bearish)
  3. Вторая свеча: подтверждение (закрылась в том же направлении)
  4. Если обе свечи совпадают по направлению → сигнал
  5. Entry = close второй свечи
"""
import sys
sys.path.insert(0, '/root/apex-system')
sys.path.insert(0, '/root/apex-system/strategies/APEX_SCENARIO_LAB')

import logging
from scenarios.base_scenario import BaseScenario

logger = logging.getLogger("apex.scenario_lab.sc_002")

SYMBOLS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "BNB/USDT:USDT",
    "XRP/USDT:USDT",
]

CLOSE_SEQUENCE = ["TP1", "SL", "TP1", "SL", "TP2", "TP3", "MANUAL_STOP", None]


class SC002SecondCandle(BaseScenario):
    name = "SC_002_SECOND_CANDLE"
    description = "Entry on second candle confirmation (1m)"
    smc_mode = "REQUIRED_SOFT"

    def __init__(self):
        self._signal_counter = 0

    def pick_symbol(self) -> str | None:
        return SYMBOLS[self._signal_counter % len(SYMBOLS)]

    def generate_signal(self, symbol: str, context: dict) -> dict | None:
        try:
            import urllib.request, json as _json
            bybit_sym = symbol.replace("/", "").replace(":USDT", "")
            url = (
                f"https://api.bybit.com/v5/market/kline"
                f"?category=linear&symbol={bybit_sym}&interval=1&limit=3"
            )
            with urllib.request.urlopen(url, timeout=10) as r:
                data = _json.loads(r.read().decode())

            candles = data.get("result", {}).get("list", [])
            if len(candles) < 3:
                logger.warning(f"SC_002: not enough candles for {symbol}")
                return None

            c1_open  = float(candles[2][1])
            c1_close = float(candles[2][4])
            c2_open  = float(candles[1][1])
            c2_close = float(candles[1][4])

            c1_bullish = c1_close > c1_open
            c2_bullish = c2_close > c2_open

            if c1_bullish and c2_bullish:
                direction = "long"
            elif (not c1_bullish) and (not c2_bullish):
                direction = "short"
            else:
                logger.info(
                    f"SC_002: no candle confirmation for {symbol} "
                    f"c1={'bull' if c1_bullish else 'bear'} "
                    f"c2={'bull' if c2_bullish else 'bear'}"
                )
                return None

            entry_price = c2_close
            if entry_price <= 0:
                return None

            logger.info(
                f"SC_002: signal {symbol} {direction} entry={entry_price} "
                f"c1={c1_open:.4f}->{c1_close:.4f} "
                f"c2={c2_open:.4f}->{c2_close:.4f}"
            )

            return {
                "symbol":      symbol,
                "direction":   direction,
                "entry_price": entry_price,
                "context":     context,
            }

        except Exception as e:
            logger.warning(f"SC_002: signal error for {symbol}: {e}")
            return None

    def apply_risk(self, signal: dict, lab_config: dict) -> dict | None:
        try:
            entry     = float(signal["entry_price"])
            direction = signal["direction"]
            risk_usdt = float(lab_config.get("risk_usdt_per_trade", 500.0))
            leverage  = 20

            sl_pct, tp1_pct, tp2_pct, tp3_pct = 0.01, 0.01, 0.02, 0.03

            if direction == "long":
                sl  = round(entry * (1 - sl_pct), 8)
                tp1 = round(entry * (1 + tp1_pct), 8)
                tp2 = round(entry * (1 + tp2_pct), 8)
                tp3 = round(entry * (1 + tp3_pct), 8)
            else:
                sl  = round(entry * (1 + sl_pct), 8)
                tp1 = round(entry * (1 - tp1_pct), 8)
                tp2 = round(entry * (1 - tp2_pct), 8)
                tp3 = round(entry * (1 - tp3_pct), 8)

            risk_distance = abs(entry - sl)
            if risk_distance <= 0:
                logger.warning(f"SC_002: risk_distance=0 for {signal['symbol']}")
                return None

            size     = round(risk_usdt / risk_distance, 6)
            rr       = round(abs(tp1 - entry) / risk_distance, 2)
            risk_pct = round(
                (risk_usdt / float(lab_config.get("lab_balance", 100000.0))) * 100, 4
            )

            ctx = signal.get("context", {}) or {}
            close_reason_planned = CLOSE_SEQUENCE[self._signal_counter % len(CLOSE_SEQUENCE)]

            result = {
                **signal,
                "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
                "size": size, "leverage": leverage,
                "risk_usdt": risk_usdt, "risk_pct": risk_pct, "rr": rr,
                "market_phase":      ctx.get("market_phase"),
                "bos_present":       ctx.get("bos_present", 0),
                "choch_present":     ctx.get("choch_present", 0),
                "entry_in_discount": ctx.get("entry_in_discount", 0),
                "entry_near_ob":     ctx.get("entry_near_ob", 0),
                "entry_near_fvg":    ctx.get("entry_near_fvg", 0),
                "orb_high": ctx.get("orb_high"),
                "orb_low":  ctx.get("orb_low"),
                "orb_mid":  ctx.get("orb_mid"),
                "_planned_close":    close_reason_planned,
                "entry_reason_code": (
                    f"PLANNED:{close_reason_planned}"
                    if close_reason_planned else "PLANNED:OPEN"
                ),
            }
            self._signal_counter += 1
            return result

        except Exception as e:
            logger.error(f"SC_002.apply_risk error: {e}")
            return None

    def get_close_event(self, position: dict, current_price: float) -> tuple | None:
        planned = position.get("_planned_close")

        if planned is None:
            code = position.get("entry_reason_code", "") or ""
            if code.startswith("PLANNED:"):
                planned = code.replace("PLANNED:", "") or None
                if planned == "OPEN":
                    planned = None

        if planned is None:
            return None

        entry     = float(position.get("entry") or position.get("fill_price") or 0)
        direction = str(position.get("direction", "long")).lower()
        sl  = float(position.get("sl")  or 0)
        tp1 = float(position.get("tp1") or 0)
        tp2 = float(position.get("tp2") or 0)
        tp3 = float(position.get("tp3") or 0)

        price_map = {
            "TP1": tp1 if tp1 else round(entry * (1.01 if direction == "long" else 0.99), 8),
            "TP2": tp2 if tp2 else round(entry * (1.02 if direction == "long" else 0.98), 8),
            "TP3": tp3 if tp3 else round(entry * (1.03 if direction == "long" else 0.97), 8),
            "SL":  sl  if sl  else round(entry * (0.99 if direction == "long" else 1.01), 8),
            "MANUAL_STOP": current_price if current_price else entry,
        }

        return (price_map.get(planned, current_price), planned)

    def validate(self) -> bool:
        return True
