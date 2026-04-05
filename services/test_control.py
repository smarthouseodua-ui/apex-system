import json
import os
from datetime import datetime

STATE_FILE = "/root/apex-system/storage/test_control.json"

DEFAULT_STATE = {
    "test_enabled": False,
    "hourly_test_enabled": False,
    "manual_hour_enabled": False,
    "scanner_enabled": False,
    "entries_enabled": False,
    "monitor_enabled": False,
    "mode": "OFF",
    "test_balance": 1000.0,
    "manual_topup_total": 0.0,
    "active_filter": "SESSION_ORB_5M",
    "pairs_limit": 100,
    "selected_hour": None,
    "selected_hour_orb_high": None,
    "selected_hour_orb_low": None,
    "awaiting_topup_input": False,
    "awaiting_deposit_input": False,
    "deposit_action": None,
    "awaiting_param_input": None,
    "param_sl_pct": None,
    "param_tp1_pct": None,
    "param_tp2_pct": None,
    "param_tp3_pct": None,
    "param_leverage": None,
    "param_size_usdt": None,
    "param_risk_usdt": None,
    "ny_5m_active": False,
    "ny_5m_started_at": None,
    "strategy_mode": "DEFAULT",
    "reset_pending": False,
}


def read():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_STATE.copy()


def write(updates):
    state = read()
    state.update(updates)
    state["updated_at"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, indent=2, ensure_ascii=False, fp=f)
    return state
