import os
import sys
import logging
from dotenv import load_dotenv

sys.path.insert(0, "/root/apex-system")

load_dotenv("/root/apex-system/.env")

from services.telegram.bot import create_app


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


def main():
    print("⚡ APPS SYSTEM BOT STARTING")

    app = create_app()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
