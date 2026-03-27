# result_storage.py

import csv
import os

FILE_PATH = "/root/apex-system/storage/simulation_results.csv"

HEADERS = [
    "symbol",
    "side",
    "entry_price",
    "close_price",
    "size",
    "pnl",
    "close_reason",
    "opened_at",
    "closed_at"
]


def ensure_file():
    if not os.path.exists(FILE_PATH):
        os.makedirs(os.path.dirname(FILE_PATH), exist_ok=True)

        with open(FILE_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(HEADERS)


def save_result(position: dict):
    ensure_file()

    row = [
        position.get("symbol"),
        position.get("side"),
        position.get("entry_price"),
        position.get("close_price"),
        position.get("size"),
        position.get("pnl"),
        position.get("close_reason"),
        position.get("opened_at"),
        position.get("closed_at"),
    ]

    with open(FILE_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(row)
