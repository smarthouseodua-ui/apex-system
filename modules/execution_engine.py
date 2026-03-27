# execution_engine.py

from datetime import datetime
from modules.position_monitor import add_position
from modules.risk_manager import can_trade, get_state
from modules.telegram_control import get_mode
from modules.config import MODE, DEFAULT_BALANCE
from modules.exchange_client import ExchangeClient

OPEN_POSITIONS = {}

MAX_POSITIONS = 5
RISK_PER_TRADE = 0.01  # 1%

client = ExchangeClient()
client.connect()


def can_open(symbol: str) -> bool:
    if symbol in OPEN_POSITIONS:
        return False
    if len(OPEN_POSITIONS) >= MAX_POSITIONS:
        return False
    return True


def calculate_position_size(balance: float, price: float) -> float:
    risk_amount = balance * RISK_PER_TRADE
    size = risk_amount / price
    return round(size, 6)


def build_order(signal: dict, balance: float) -> dict:
    symbol = signal["symbol"]
    price = signal["price"]

    size = calculate_position_size(balance, price)
    notional = round(price * size, 2)

    side = "LONG"

    if side == "LONG":
        sl = round(price * 0.99, 6)
        tp1 = round(price * 1.01, 6)
        tp2 = round(price * 1.02, 6)
        tp3 = round(price * 1.03, 6)
    else:
        sl = round(price * 1.01, 6)
        tp1 = round(price * 0.99, 6)
        tp2 = round(price * 0.98, 6)
        tp3 = round(price * 0.97, 6)

    return {
        "symbol": symbol,
        "side": side,
        "entry_price": price,
        "size": size,
        "notional": notional,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "mode": MODE,
        "timestamp": datetime.utcnow().isoformat()
    }


def execute(signal: dict, balance: float = DEFAULT_BALANCE):
    symbol = signal["symbol"]
    print(f"[EXECUTION TRY] {symbol}")

    if get_mode() != "RUN":
        print(f"[BLOCKED] {symbol} (mode={get_mode()})")
        return None

    if not can_open(symbol):
        print(f"[BLOCKED] {symbol} (already open or max positions)")
        return None

    if not can_trade(len(OPEN_POSITIONS)):
        print(f"[BLOCKED] {symbol} (risk manager)")
        return None

    # Safety check for LIVE
    if MODE == "LIVE":
        state = get_state()
        if state["blocked"]:
            print(f"[BLOCKED] {symbol} (risk blocked)")
            return None
        if balance <= 0:
            print(f"[BLOCKED] {symbol} (no balance)")
            return None

    order = build_order(signal, balance)

    # SIMULATION
    if MODE == "SIMULATION":
        OPEN_POSITIONS[symbol] = order
        add_position(order)
        print(f"[OPENED] {symbol} [SIM]")
        return order

    # PAPER
    if MODE == "PAPER":
        OPEN_POSITIONS[symbol] = order
        add_position(order)
        print(f"[OPENED] {symbol} [PAPER]")
        return order

    # LIVE
    if MODE == "LIVE":
        success = client.place_order(
            symbol,
            order["side"],
            order["size"]
        )

        if success:
            OPEN_POSITIONS[symbol] = order
            add_position(order)
            print(f"[OPENED] {symbol} [LIVE]")
            return order

    return None
