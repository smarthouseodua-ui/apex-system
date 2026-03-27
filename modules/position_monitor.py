# position_monitor.py

from datetime import datetime, timedelta
from modules.pnl_engine import calculate_pnl
from modules.result_storage import save_result
from modules.risk_manager import update_after_trade

OPEN_POSITIONS = {}

TP_PERCENT = 0.02   # +2%
SL_PERCENT = 0.01   # -1%

TP1_PERCENT = 0.01  # +1%
TP2_PERCENT = 0.02  # +2%
TP3_PERCENT = 0.03  # +3%

TIME_LIMIT_MIN = 60


def add_position(order: dict):
    symbol = order["symbol"]
    entry = order["entry_price"]
    # ── Запись в T05 ────────────────────────────────────────────────────
    try:
        from storage.db.repository import Repository
        repo = Repository()
        repo.log_execution({
            "symbol":       symbol,
            "direction":    order.get("side", "LONG").lower(),
            "fill_price":   entry,
            "size":         order.get("size"),
            "risk_usdt":    order.get("notional"),
            "sl":           order.get("sl"),
            "tp1":          order.get("tp1"),
            "tp2":          order.get("tp2"),
            "tp3":          order.get("tp3"),
            "mode":         order.get("mode", "PAPER"),
            "status":       "open",
            "opened_at":    order.get("opened_at", ""),
            "trade_id":     order.get("trade_id", ""),
            "session_name": order.get("session_name", ""),
            "session_label": order.get("session_name", ""),
            "session_asia": 0, "session_london": 0, "session_new_york": 0,
            "event_tokyo_open": 0, "event_hk_open": 0,
            "event_london_open": 0, "event_ny_open": 0,
            "event_overlap_london_ny": 0,
        })
    except Exception as e:
        import logging
        logging.getLogger("apex.position_monitor").error(f"T05 write error: {e}")
    # ────────────────────────────────────────────────────────────────────
    side = order.get("side", "LONG")

    if side == "LONG":
        sl = round(entry * (1 - SL_PERCENT), 6)
        tp1 = round(entry * (1 + TP1_PERCENT), 6)
        tp2 = round(entry * (1 + TP2_PERCENT), 6)
        tp3 = round(entry * (1 + TP3_PERCENT), 6)
    else:
        sl = round(entry * (1 + SL_PERCENT), 6)
        tp1 = round(entry * (1 - TP1_PERCENT), 6)
        tp2 = round(entry * (1 - TP2_PERCENT), 6)
        tp3 = round(entry * (1 - TP3_PERCENT), 6)

    OPEN_POSITIONS[symbol] = {
        "symbol": symbol,
        "side": side,
        "entry_price": entry,
        "size": order["size"],
        "notional": round(entry * order["size"], 2),
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "mode": order.get("mode", "PAPER"),
        "opened_at": datetime.utcnow(),
        "status": "open",
        "current_price": entry,
    }


def should_close(position: dict, current_price: float):
    entry = position["entry_price"]

    tp_price = entry * (1 + TP_PERCENT)
    sl_price = entry * (1 - SL_PERCENT)

    # TP
    if current_price >= tp_price:
        return "TP"

    # SL
    if current_price <= sl_price:
        return "SL"

    # TIME EXIT
    if datetime.utcnow() - position["opened_at"] > timedelta(minutes=TIME_LIMIT_MIN):
        return "TIME"

    return None


def close_position(symbol: str, reason: str, price: float):
    pos = OPEN_POSITIONS[symbol]

    pos["status"] = "closed"
    pos["close_reason"] = reason
    pos["close_price"] = price
    pos["closed_at"] = datetime.utcnow()

    pnl = calculate_pnl(pos)
    pos["pnl"] = pnl

    print(
        f"[RESULT] {pos['symbol']} "
        f"{pos['close_reason']} "
        f"PnL={pos['pnl']}"
    )

    save_result(pos)
    update_after_trade(pnl)

    return pos


def monitor(current_prices: dict):
    closed = []

    for symbol, position in list(OPEN_POSITIONS.items()):
        if position["status"] != "open":
            continue

        if symbol not in current_prices:
            continue

        # Update current price for live display
        position["current_price"] = current_prices[symbol]

        reason = should_close(position, current_prices[symbol])

        if reason:
            closed_pos = close_position(symbol, reason, current_prices[symbol])
            closed.append(closed_pos)

            print(f"[CLOSE] {symbol} {reason}")

    return closed
