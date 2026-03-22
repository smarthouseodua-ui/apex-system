"""
APEX PROTOCOL™ — Monitor
Быстрая проверка состояния системы.
"""

import sys
import os
import yaml
import logging

sys.path.insert(0, "/root/apex-system")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("apex.monitor")


def load_config() -> dict:
    config = {}
    config_dir = "/root/apex-system/config"
    for fname in ["system.yaml", "risk.yaml"]:
        path = os.path.join(config_dir, fname)
        with open(path, "r") as f:
            config.update(yaml.safe_load(f))
    return config


def main():
    print("=" * 50)
    print("APEX PROTOCOL - MONITOR")
    print("=" * 50)

    config = load_config()

    from core.time_manager import TimeManager
    tm = TimeManager(config)
    info = tm.get_session_info()

    print(f"Time:      {info['time']}")
    print(f"Session:   {info['session']}")
    print(f"Direction: {info['direction']}")
    print(f"Trading:   {info['is_trading']}")
    print(f"Blocked:   {info['is_blocked']}")
    print(f"Mode:      {config.get('system', {}).get('mode', 'simulation')}")
    print(f"Balance:   {config.get('risk', {}).get('balance_usdt')} USDT")
    print("=" * 50)

    log_path = "/root/apex-system/logs/system.log"
    if os.path.exists(log_path):
        size = os.path.getsize(log_path)
        print(f"Log size:  {size} bytes")
    else:
        print("Log:       not created yet")


if __name__ == "__main__":
    main()
