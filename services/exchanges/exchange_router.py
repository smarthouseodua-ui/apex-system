"""
APEX PROTOCOL™ — Exchange Router
Диспетчер бирж. Читает active_exchanges из test_control.json
и возвращает активные экземпляры сервисов.
"""
import json
import logging

logger = logging.getLogger("apex.exchange.router")

REGISTRY = {
    "bybit":   "services.exchanges.bybit_exchange.BybitExchangeService",
    "binance": "services.exchanges.binance_exchange.BinanceExchangeService",
    "okx":     "services.exchanges.okx_exchange.OKXExchangeService",
    "bingx":   "services.exchanges.bingx_exchange.BingXExchangeService",
    "mexc":    "services.exchanges.mexc_exchange.MEXCExchangeService",
}

_instances: dict = {}


def _get_active_exchanges() -> list:
    try:
        tc = json.load(open("/root/apex-system/storage/test_control.json"))
        return [e.lower() for e in tc.get("active_exchanges", ["bybit"])]
    except Exception:
        return ["bybit"]


def get_exchange_services(config: dict = None) -> dict:
    """
    Возвращает dict {exchange_name: instance} для активных бирж.
    Кэширует экземпляры.
    """
    active = _get_active_exchanges()
    services = {}

    for name in active:
        if name not in REGISTRY:
            logger.warning(f"[Router] unknown exchange: {name}")
            continue

        if name not in _instances:
            try:
                module_path, class_name = REGISTRY[name].rsplit(".", 1)
                import importlib
                module = importlib.import_module(module_path)
                cls = getattr(module, class_name)
                _instances[name] = cls(config or {})
                logger.info(f"[Router] created {name} service")
            except Exception as e:
                logger.error(f"[Router] failed to create {name}: {e}")
                continue

        services[name] = _instances[name]

    return services


def clear_cache():
    """Сбросить кэш экземпляров (при смене active_exchanges)."""
    global _instances
    _instances = {}
