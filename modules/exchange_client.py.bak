# exchange_client.py

import os
import ccxt


class ExchangeClient:

    def __init__(self):
        self.exchange = None

    def connect(self):
        self.exchange = ccxt.bybit({
            "apiKey": os.getenv("BYBIT_API_KEY"),
            "secret": os.getenv("BYBIT_API_SECRET"),
            "enableRateLimit": True,
        })

    def get_balance(self):
        balance = self.exchange.fetch_balance()
        return balance.get("USDT", {}).get("free", 0)

    def place_order(self, symbol, side, size):
        try:
            order = self.exchange.create_market_order(
                symbol=symbol,
                side="buy" if side == "LONG" else "sell",
                amount=size
            )
            print(f"[LIVE ORDER] {symbol} {side} size={size}")
            return order
        except Exception as e:
            print(f"[ERROR] order failed: {e}")
            return None

    def get_positions(self):
        try:
            return self.exchange.fetch_positions()
        except Exception:
            return []
