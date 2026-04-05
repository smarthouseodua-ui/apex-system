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
        try:
            self.exchange.load_markets()
            print("[ExchangeClient] markets loaded OK")
        except Exception as e:
            print(f"[ExchangeClient] load_markets failed: {e}")

    def get_balance(self):
        try:
            balance = self.exchange.fetch_balance()
            return balance.get("USDT", {}).get("free", 0)
        except Exception:
            return 0

    def get_balance_bybit(self) -> float:
        """Получить свободный баланс USDT с Bybit."""
        try:
            ex = ccxt.bybit({
                "apiKey": os.getenv("BYBIT_API_KEY"),
                "secret": os.getenv("BYBIT_API_SECRET"),
                "enableRateLimit": True,
            })
            balance = ex.fetch_balance()
            return float(balance.get("USDT", {}).get("free", 0))
        except Exception as e:
            print(f"[ExchangeClient] Bybit balance error: {e}")
            return 0.0

    def get_balance_binance(self) -> float:
        """Получить свободный баланс USDT с Binance Futures."""
        try:
            ex = ccxt.binance({
                "apiKey": os.getenv("BINANCE_API_KEY"),
                "secret": os.getenv("BINANCE_API_SECRET"),
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            })
            balance = ex.fetch_balance()
            return float(balance.get("USDT", {}).get("free", 0))
        except Exception as e:
            print(f"[ExchangeClient] Binance balance error: {e}")
            return 0.0

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
