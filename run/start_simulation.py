"""
APEX PROTOCOL™ — Start Simulation
Точка запуска в режиме симуляции.
"""

import asyncio
import logging
import yaml
import os
import sys

sys.path.insert(0, "/root/apex-system")

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/root/apex-system/logs/system.log"),
    ]
)
logger = logging.getLogger("apex.start")


def load_config() -> dict:
    config = {}
    config_dir = "/root/apex-system/config"
    for fname in ["system.yaml", "exchanges.yaml", "risk.yaml", "pipeline.yaml"]:
        path = os.path.join(config_dir, fname)
        with open(path, "r") as f:
            data = yaml.safe_load(f)
            config.update(data)
    config["mode"] = "simulation"
    return config


async def main():
    logger.info("=" * 50)
    logger.info("⚡ APEX PROTOCOL™ — SIMULATION MODE")
    logger.info("=" * 50)

    config = load_config()
    logger.info(f"Config loaded | Mode: {config.get('mode')} | Balance: {config.get('risk', {}).get('balance_usdt')} USDT")

    from pipelines.trade_pipeline import TradePipeline
    pipeline = TradePipeline(config)
    await pipeline.run_loop()


if __name__ == "__main__":
    asyncio.run(main())
