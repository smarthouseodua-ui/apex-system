"""
APEX PROTOCOL™ — Start Pipeline
Точка запуска торгового пайплайна.
"""

import asyncio
import logging
import yaml
import os
import sys

sys.path.insert(0, "/root/apex-system")

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
    logger.info("=" * 60)
    logger.info("⚡ APEX PROTOCOL™ — PIPELINE START")
    logger.info("=" * 60)

    from storage.db.init_db import init_db
    init_db()

    config = load_config()

    risk = config.get("risk", {})
    scanner = config.get("scanner", {})
    logger.info(
        f"Balance      : {risk.get('balance_usdt')} USDT\n"
        f"               Fixed size   : {risk.get('fixed_size_usdt')} USDT\n"
        f"               SL           : -{risk.get('sl_pct')}%\n"
        f"               TP1/TP2/TP3  : +{risk.get('tp1_pct')}% / +{risk.get('tp2_pct')}% / +{risk.get('tp3_pct')}%\n"
        f"               Max pairs    : {scanner.get('max_candidates')}\n"
        f"               Mode         : {config.get('mode')}"
    )

    try:
        from services.test_control import read as tc_read
        tc = tc_read()
        if tc.get("test_enabled") or tc.get("hourly_test_enabled"):
            logger.info(
                f"Test control : ACTIVE | mode={tc.get('mode')} | "
                f"manual_hour={tc.get('manual_hour_enabled')} | "
                f"selected_hour={tc.get('selected_hour')}"
            )
        else:
            logger.info("Test control : OFF — штатный режим по сессиям")
    except Exception:
        pass

    from pipelines.trade_pipeline import TradePipeline
    pipeline = TradePipeline(config)
    await pipeline.run_loop()


if __name__ == "__main__":
    asyncio.run(main())
