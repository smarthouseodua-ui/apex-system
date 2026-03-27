# pnl_engine.py

def calculate_pnl(position: dict) -> float:
    entry = position["entry_price"]
    close = position["close_price"]
    size = position["size"]
    side = position["side"]

    if side == "LONG":
        pnl = (close - entry) * size
    else:
        pnl = (entry - close) * size

    return round(pnl, 6)
