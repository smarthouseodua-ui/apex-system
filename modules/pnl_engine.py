# pnl_engine.py

def calculate_pnl(position: dict) -> float:
    entry = position.get("entry_price") or position.get("entry") or 0
    close = position.get("close_price") or position.get("current_price") or entry
    size = position.get("size") or 0
    side = str(position.get("side", "LONG")).upper()

    if not entry or not size:
        return 0.0

    if side == "LONG":
        pnl = (close - entry) * size
    else:
        pnl = (entry - close) * size

    return round(pnl, 6)
