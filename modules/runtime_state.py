# runtime_state.py
# Shared state between processes via JSON file

import json
import os
from datetime import datetime

STATE_FILE = "/root/apex-system/storage/runtime_state.json"

# In-memory fallback (same process)
scanner_state = {
    "total_pairs": 0,
    "after_liquidity": 0,
    "after_volatility": 0,
    "after_structure": 0,
    "scored": 0,
    "top_score": 0,
    "candidates": 0,
    "signals": 0,
}


def load_runtime_state() -> dict:
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_runtime_state(data: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def update_scanner_state(
    total_pairs=0,
    after_liquidity=0,
    after_volatility=0,
    after_structure=0,
    scored=0,
    candidates=0,
    signals=0,
    top_score=0,
    after_ema_filter=0,
    sent_to_filter_raw=0,
    last_reject_reason="",
):
    # Update in-memory
    scanner_state["total_pairs"] = total_pairs
    scanner_state["after_liquidity"] = after_liquidity
    scanner_state["after_volatility"] = after_volatility
    scanner_state["after_structure"] = after_structure
    scanner_state["scored"] = scored
    scanner_state["top_score"] = top_score
    scanner_state["candidates"] = candidates
    scanner_state["signals"] = signals

    # Write to shared file
    state = load_runtime_state()
    state["scanner"] = {
        "total_pairs": total_pairs,
        "after_liquidity": after_liquidity,
        "after_volatility": after_volatility,
        "after_structure": after_structure,
        "scored": scored,
        "top_score": top_score,
        "candidates": candidates,
        "signals": signals,
        "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    state["debug"] = {
        "stage_pairs": total_pairs,
        "stage_liquidity": after_liquidity,
        "stage_volatility": after_volatility,
        "stage_structure": after_structure,
        "stage_scored": scored,
        "stage_ema_filter": after_ema_filter,
        "stage_sent_to_filter": sent_to_filter_raw,
        "stage_final": signals,
        "last_reject_reason": last_reject_reason,
    }
    save_runtime_state(state)


def get_scanner_state() -> dict:
    """Read scanner state from shared file."""
    state = load_runtime_state()
    return state.get("scanner", {
        "total_pairs": 0,
        "after_liquidity": 0,
        "after_volatility": 0,
        "after_structure": 0,
        "scored": 0,
        "top_score": 0,
        "candidates": 0,
        "signals": 0,
        "updated_at": None,
    })


def get_debug_state() -> dict:
    """Read debug state from shared file."""
    state = load_runtime_state()
    return state.get("debug", {
        "stage_pairs": 0,
        "stage_liquidity": 0,
        "stage_volatility": 0,
        "stage_structure": 0,
        "stage_scored": 0,
        "stage_ema_filter": 0,
        "stage_sent_to_filter": 0,
        "stage_final": 0,
        "last_reject_reason": "",
    })
